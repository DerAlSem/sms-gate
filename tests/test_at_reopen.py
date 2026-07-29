"""Reopening a lost serial port in place.

The reopen itself is the easy part; the hazards are around it. The init sequence goes
through the lock-acquiring path, so a reopen that holds the lock and calls `init()`
deadlocks — and wrapped in the recovery timeout that deadlock reads as "recovery took five
minutes and achieved nothing", close enough to the incident it was meant to cure to be
mistaken for it. A reopen cancelled between close and open leaves the sender writing into
a port that no longer exists, because the gate that suspends sending reopens regardless.
Both are covered here.
"""

import asyncio

import pytest

import app.modem.at_commands as at
from app.modem.at_commands import (
    ATSerial, ATCommandError, CNMI_SUBSCRIBE, ModemTransportError,
)

# Captured at import, before any test patches the pacing down: what is under test is the
# relationship the shipped constants hold to each other, not the numbers a test runs with.
_SHIPPED_BUDGET = at._REOPEN_BUDGET
_SHIPPED_DEVICE_WAIT = at._DEVICE_WAIT


class _FakePort:
    """A serial fake that answers every write with OK, and records what it was asked."""

    def __init__(self, answer=b"\r\nOK\r\n"):
        self.answer = answer
        self.writes = []
        self.closed = False
        self._buf = b""

    def write(self, data):
        self.writes.append(data)
        if self.answer is not None:
            self._buf += self.answer

    async def drain(self):
        pass

    async def read(self, n):
        while not self._buf:
            await asyncio.sleep(0.001)
        out, self._buf = self._buf, b""
        return out

    def close(self):
        self.closed = True

    async def wait_closed(self):
        pass

    @property
    def commands(self):
        return [w.decode().strip() for w in self.writes]


def _opener(monkeypatch, outcomes):
    """Patch `open_serial_connection` with a scripted sequence of outcomes.

    Each entry is either an exception to raise or a `_FakePort` to hand back. The list of
    ports actually opened is returned so a test can inspect what was said to them.
    """
    opened = []

    async def fake_open(url, baudrate):
        outcome = outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        opened.append(outcome)
        return outcome, outcome

    monkeypatch.setattr(at.serial_asyncio, "open_serial_connection", fake_open)
    return opened


def _always_failing_opener(monkeypatch, exc):
    """An opener for a device that never comes back, however long it is given."""
    calls = []

    async def fake_open(url, baudrate):
        calls.append(url)
        raise exc

    monkeypatch.setattr(at.serial_asyncio, "open_serial_connection", fake_open)
    return calls


@pytest.fixture(autouse=True)
def _fast_attempts(monkeypatch):
    """Production pacing, not the behaviour under test — kept in proportion so a test can
    still tell "gave up too early" from "gave up"."""
    monkeypatch.setattr(at, "_REOPEN_DELAY", 0.01)
    monkeypatch.setattr(at, "_REOPEN_BUDGET", 1.0)


def _serial():
    s = ATSerial("/dev/ttyUSB2")
    s._usable = False           # as a lost link leaves it
    return s


def test_a_reopen_runs_the_whole_init_sequence_including_the_urc_subscription(monkeypatch):
    """A port that opens without being re-initialised is the worst outcome available: it
    accepts commands, so every health check passes, while no +CDS and no +CMTI ever
    arrive."""
    port = _FakePort()
    _opener(monkeypatch, [port])
    s = _serial()

    assert asyncio.run(s.reconnect()) is True
    assert port.commands == at.INIT_COMMANDS
    assert CNMI_SUBSCRIBE in port.commands
    assert s.usable is True
    assert s.reopens == 1


def test_a_reopen_holding_the_lock_does_not_deadlock_on_init(monkeypatch):
    """The regression this whole group exists to prevent: `asyncio.Lock` is not
    reentrant, and `init()` acquires the very lock `reconnect()` must hold."""
    _opener(monkeypatch, [_FakePort()])
    s = _serial()

    async def run():
        # Generous next to the ~0s the real thing takes, tight next to the 300s recovery
        # timeout inside which a deadlock would otherwise hide.
        return await asyncio.wait_for(s.reconnect(), timeout=5.0)

    assert asyncio.run(run()) is True


def test_a_missing_node_then_a_permission_error_then_success(monkeypatch):
    """A recreated node gets its ownership from udev, so the attempts just after a
    re-enumeration can fail on permission rather than on absence. Both are "not back
    yet"."""
    port = _FakePort()
    _opener(monkeypatch, [
        FileNotFoundError(2, "No such file or directory", "/dev/ttyUSB2"),
        PermissionError(13, "Permission denied", "/dev/ttyUSB2"),
        port,
    ])
    s = _serial()

    assert asyncio.run(s.reconnect()) is True
    assert port.commands == at.INIT_COMMANDS
    assert s.reopens == 1


def test_an_attempt_that_blocks_is_abandoned_at_its_own_bound(monkeypatch):
    """A bound on the number of attempts does not bound the wait: `open()` on a node udev
    has not finished with can block indefinitely."""
    port = _FakePort()
    calls = []

    async def fake_open(url, baudrate):
        calls.append(url)
        if len(calls) == 1:
            await asyncio.sleep(10)
        return port, port

    monkeypatch.setattr(at.serial_asyncio, "open_serial_connection", fake_open)
    monkeypatch.setattr(at, "_REOPEN_ATTEMPT_TIMEOUT", 0.05)
    s = _serial()

    assert asyncio.run(s.reconnect()) is True
    assert len(calls) == 2, "the blocked attempt must be abandoned, not waited out"


def test_a_failing_init_makes_the_attempt_fail(monkeypatch):
    """A port that opens but will not initialise must not be handed back as usable."""
    bad, good = _FakePort(answer=b"\r\nERROR\r\n"), _FakePort()
    _opener(monkeypatch, [bad, good])
    s = _serial()

    assert asyncio.run(s.reconnect()) is True
    assert good.commands == at.INIT_COMMANDS
    assert bad.closed is True, "the port that would not initialise must be let go of"


def test_the_budget_is_the_same_wait_the_startup_path_gives_the_same_device():
    """One question — how long can this device take to come back — must have one answer.
    Two of them is how they drift, and the smaller one wins in the path that matters."""
    assert _SHIPPED_BUDGET == _SHIPPED_DEVICE_WAIT


def test_the_budget_outlasts_a_device_that_takes_its_time(monkeypatch):
    """The prod 2026-07-29 regression. A five-attempt budget is twelve seconds, which
    reads like a budget until you notice what it is a budget *for*: the device was merely
    still absent, and the gateway restarted itself over it — while the startup path would
    have waited a full minute for that very node."""
    port = _FakePort()
    calls = []

    async def fake_open(url, baudrate):
        calls.append(url)
        if len(calls) <= 12:
            raise FileNotFoundError(2, "No such file or directory", url)
        return port, port

    monkeypatch.setattr(at.serial_asyncio, "open_serial_connection", fake_open)
    monkeypatch.setattr(at, "_REOPEN_DELAY", 0.02)
    s = _serial()

    assert asyncio.run(s.reconnect()) is True, "gave up while the device was still coming"
    assert len(calls) == 13
    assert port.commands == at.INIT_COMMANDS


def test_exhausted_budget_leaves_the_link_explicitly_unusable(monkeypatch):
    monkeypatch.setattr(at, "_REOPEN_BUDGET", 0.05)
    calls = _always_failing_opener(monkeypatch, FileNotFoundError(2, "gone"))
    s = _serial()

    assert asyncio.run(s.reconnect()) is False
    assert s.usable is False
    assert s.reopens == 0
    assert len(calls) > 1, "the budget must buy more than a single look"
    assert s.link_lost.is_set(), "whoever escalates should not wait out another interval"


def test_giving_up_is_bounded_even_when_the_device_never_returns(monkeypatch):
    """The budget is a deadline, so a device that stays gone costs that and no more."""
    monkeypatch.setattr(at, "_REOPEN_BUDGET", 0.2)
    monkeypatch.setattr(at, "_REOPEN_DELAY", 0.01)
    _always_failing_opener(monkeypatch, FileNotFoundError(2, "gone"))
    s = _serial()

    async def run():
        started = asyncio.get_event_loop().time()
        assert await s.reconnect() is False
        return asyncio.get_event_loop().time() - started

    elapsed = asyncio.run(run())
    assert 0.2 <= elapsed < 1.0, f"gave up after {elapsed:.2f}s, budget was 0.2s"


def test_a_cancelled_reopen_leaves_the_link_unusable_and_the_next_send_fails_at_once(
    monkeypatch,
):
    """Recovery runs under an outer timeout, so a reopen that takes too long is cancelled
    where it stands — possibly between closing the old port and opening the new one —
    while the gate that suspends sending reopens regardless."""
    port = _FakePort()

    async def fake_open(url, baudrate):
        await asyncio.sleep(10)
        return port, port

    monkeypatch.setattr(at.serial_asyncio, "open_serial_connection", fake_open)
    s = _serial()
    s._usable = True                      # the link the reopen is about to replace
    s._writer = s._reader = _FakePort()

    async def run():
        task = asyncio.create_task(s.reconnect())
        await asyncio.sleep(0.05)         # let it get past the close
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # The sender resumes here, against whatever the reopen left behind.
        started = asyncio.get_event_loop().time()
        with pytest.raises(ModemTransportError):
            await s.command("AT+CSQ", timeout=5.0)
        return asyncio.get_event_loop().time() - started

    elapsed = asyncio.run(run())
    assert elapsed < 0.5, "a lost link must fail fast, not one command timeout at a time"


def test_a_listening_port_is_reopened_without_an_init_sequence(monkeypatch):
    """The URC port has no writer, so it cannot issue commands at all — the subscription
    that matters is applied through the command port and takes effect for both."""
    port = _FakePort()
    _opener(monkeypatch, [port])
    s = _serial()

    assert asyncio.run(s.reconnect(init=False)) is True
    assert port.commands == []
    assert s.usable is True


def test_a_command_waits_for_a_reopen_rather_than_acting_on_a_half_replaced_port(
    monkeypatch,
):
    port = _FakePort()
    order = []

    async def fake_open(url, baudrate):
        order.append("open")
        await asyncio.sleep(0.05)
        return port, port

    monkeypatch.setattr(at.serial_asyncio, "open_serial_connection", fake_open)
    s = _serial()

    async def run():
        reopen = asyncio.create_task(s.reconnect())
        await asyncio.sleep(0.01)

        async def other():
            await s.command("AT+CSQ", timeout=1.0)
            order.append("command")

        await asyncio.gather(reopen, other())

    asyncio.run(run())
    assert order == ["open", "command"]
    assert port.commands[:len(at.INIT_COMMANDS)] == at.INIT_COMMANDS


def test_init_failures_still_surface_as_at_failures(monkeypatch):
    """`init()` moved onto the unlocked path; its contract must not have moved with it."""
    _opener(monkeypatch, [_FakePort(answer=b"\r\nERROR\r\n")])
    s = ATSerial("/dev/ttyUSB2")

    async def run():
        await s.connect()
        await s.init()

    with pytest.raises(ATCommandError):
        asyncio.run(run())
