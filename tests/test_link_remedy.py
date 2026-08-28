"""The remedy for a lost link: reopen the port, for as long as it takes.

Before this, every re-enumeration cost a process restart — the in-memory send queue
dropped, startup re-run, a restart cycle in the journal — for a device that was physically
absent for a few seconds. Reopening in place turned that into a pause.

What changed on 2026-08-28 is the far end of the same ladder. Reopening used to be bounded
by a budget that ended in a service restart, and a restart cannot reopen a device that is
not plugged in: its only observable effect was to spend the supervisor's restart limits
until it gave up altogether, taking the admin console with it. So the budget is gone and
the linker keeps trying.

What has to stay true is the shape around the reopen: sending suspended for its whole
duration and resumed however it ended, one alert per outage, and the ladder coming all the
way down once the link is back.
"""

import asyncio

import pytest

import app.modem.manager as mgr
from app.modem.at_commands import ModemTransportError
from app.modem.manager import ModemManager


@pytest.fixture(autouse=True)
def _fast_recovery(monkeypatch):
    monkeypatch.setattr(mgr, "_RECOVERY_SETTLE", 0.05)
    monkeypatch.setattr(mgr, "_RECOVERY_POLL", 0.005)
    monkeypatch.setattr(mgr, "_RECOVERY_TIMEOUT", 2.0)
    monkeypatch.setattr(mgr, "_LINK_RETRY_BASE", 0.005)
    monkeypatch.setattr(mgr, "_LINK_RETRY_CEILING", 0.02)


class FakeSender:
    """A command port whose link can be lost and whose reopen can be scripted."""

    def __init__(self, reopen=True, on_reconnect=None):
        self.usable = False
        self.link_lost = asyncio.Event()
        self.reopens = 0
        self._reopen = reopen
        self._on_reconnect = on_reconnect
        self.port = "/dev/ttyUSB2"

    @property
    def in_service(self):
        """A scripted port carries no transport, so `usable` is the whole answer."""
        return self.usable

    async def registration_ok(self):
        # As `ATSerial` does: on a link that is gone there is no question to answer.
        if not self.usable:
            raise ModemTransportError("link to /dev/ttyUSB2 is not open")
        return True

    async def reconnect(self, *, init=True):
        if self._on_reconnect:
            await self._on_reconnect()
        if not self._reopen:
            # As `ATSerial.reconnect` does when an attempt fails: whoever retries should
            # not spend another whole interval rediscovering this.
            self.link_lost.set()
            return False
        self.usable = True
        self.reopens += 1
        return True

    async def list_all_sms(self, timeout=10.0):
        return "OK"

    def link_snapshot(self):
        return {"link": "open" if self.usable else "lost",
                "link_last_good": "—", "link_reopens": self.reopens}


def _mgr(sender):
    m = ModemManager("/dev/null", "/dev/null")
    m._sender = sender
    # The URC port is not what these tests are about; leave it in service so `ensure_link`
    # goes straight to the command port.
    m._reader_link._writer = object()
    return m


def _linker_pass(m):
    """One turn of the linker: close the gate, try to bring the link up, reopen it."""
    return m._recover(m.ensure_link)


def test_the_link_is_reopened_rather_than_the_service_restarted():
    sender = FakeSender()
    m = _mgr(sender)

    asyncio.run(_linker_pass(m))
    assert sender.reopens == 1
    assert sender.usable is True


def test_sending_stays_suspended_for_the_duration_of_a_reopen():
    seen = []

    async def slow_reopen():
        seen.append(("during", None))
        await asyncio.sleep(0.05)

    sender = FakeSender(on_reconnect=slow_reopen)
    m = _mgr(sender)

    async def run():
        watcher = asyncio.create_task(_linker_pass(m))
        await asyncio.sleep(0.02)
        gate_during = m._modem_gate.is_set()
        await watcher
        return gate_during, m._modem_gate.is_set()

    during, after = asyncio.run(run())
    assert during is False, "a reopen must not run with the sender writing into the port"
    assert after is True


def test_sending_resumes_even_when_the_reopen_raises():
    """`_recover` reopens the gate in its `finally`; a remedy that blew up must not leave
    the gateway unable to send for ever."""

    async def boom():
        raise RuntimeError("udev exploded")

    m = _mgr(FakeSender(on_reconnect=boom))

    asyncio.run(_linker_pass(m))
    assert m._modem_gate.is_set() is True


def test_attempts_that_keep_failing_do_not_end_the_process(monkeypatch):
    """This is the reversal. The restart used to be what an exhausted reopen earned; now
    there is nothing to exhaust, because a restart cannot reopen a device that is not
    plugged in — and on 2026-08-28 the attempt to do so took the console down with it."""
    from app.settings_store import store

    monkeypatch.setitem(store._cache, "modem_watchdog_enabled", "true")
    monkeypatch.setattr(mgr, "_WD_INTERVAL", 0.01)
    exits = []
    monkeypatch.setattr(mgr.os, "_exit", lambda code: exits.append(code))
    monkeypatch.setattr(mgr, "notify", lambda *a, **kw: None)

    sender = FakeSender(reopen=False)
    m = _mgr(sender)

    async def run():
        watchdog = asyncio.create_task(m.watchdog_loop())
        linker = asyncio.create_task(m.linker_loop())
        await asyncio.sleep(0.3)
        watchdog.cancel()
        linker.cancel()

    asyncio.run(run())
    assert exits == [], "a device that is not there is not a reason to die"
    assert sender.usable is False
    # The gate is left open between attempts on purpose. Holding it shut would park the
    # sender on its backstop for minutes; open, the sender meets the missing link itself
    # and holds each message with its attempt count intact, which is the outcome the
    # spec asks for.
    assert m._modem_gate.is_set() is True


def test_the_linker_keeps_trying_until_the_device_comes_back(monkeypatch):
    monkeypatch.setattr(mgr, "notify", lambda *a, **kw: None)
    sender = FakeSender(reopen=False)
    m = _mgr(sender)

    async def run():
        linker = asyncio.create_task(m.linker_loop())
        await asyncio.sleep(0.1)
        sender._reopen = True           # the modem is plugged back in
        for _ in range(200):
            await asyncio.sleep(0.01)
            if sender.usable:
                break
        linker.cancel()

    asyncio.run(run())
    assert sender.usable is True, "the linker must pick the device up without a restart"


def test_a_self_healing_reopen_alerts_once_and_says_it_healed(monkeypatch):
    """Found on prod 2026-07-29: the reopen sent three red alerts for a pause that healed
    itself in fourteen seconds, where the restart it replaced sent one. Alerting more for
    a better outcome teaches an operator to stop reading them — which is the masked fault
    the reopen count exists to prevent, reached from the other side."""
    sent = []
    monkeypatch.setattr(mgr, "notify", lambda *a, **kw: sent.append((a, kw)))

    m = _mgr(FakeSender())
    asyncio.run(_linker_pass(m))

    assert len(sent) == 1, f"one alert per outage, once the outcome is known: {sent}"
    (event, text), kwargs = sent[0]
    assert event == "link"
    assert "without restarting" in text, "the alert must say the gateway survived it"
    assert kwargs["dedup_extra"] == "/dev/ttyUSB2", "a flapping modem is one per window"


def test_the_steps_on_the_way_to_a_reopen_do_not_alert(caplog):
    """The alert handler listens at ERROR. Nothing on the successful path may reach it —
    the failure path still does."""
    import logging

    m = _mgr(FakeSender())
    with caplog.at_level(logging.DEBUG):
        asyncio.run(_linker_pass(m))

    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors == [], f"a self-healing reopen must raise no ERROR: {errors}"


def test_a_modem_that_is_not_there_is_announced_loudly_and_once(monkeypatch, caplog):
    """The gateway can no longer announce an unreachable modem by dying, so this is the
    only thing that says so. Once per episode, not once per attempt: a notification per
    attempt is how an operator learns to stop reading them."""
    import logging

    sent = []
    monkeypatch.setattr(mgr, "notify", lambda *a, **kw: sent.append((a, kw)))
    m = _mgr(FakeSender(reopen=False))

    async def run():
        linker = asyncio.create_task(m.linker_loop())
        await asyncio.sleep(0.2)
        linker.cancel()

    with caplog.at_level(logging.DEBUG):
        asyncio.run(run())

    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("No modem" in e for e in errors), errors
    link_alerts = [a for a, k in sent if a[0] == "link"]
    assert len(link_alerts) == 1, f"one per episode, not one per attempt: {sent}"


def test_a_deliberate_reset_still_gets_its_settle(monkeypatch):
    """The other half: a modem that *was* reset must not be restarted into mid-reboot.
    This is the one exit the watchdog still has, and it belongs to the modem rather than
    to the link."""
    from app.settings_store import store

    monkeypatch.setitem(store._cache, "modem_watchdog_enabled", "true")
    monkeypatch.setattr(mgr, "_WD_HARD_RESET_SETTLE", 0.3)
    monkeypatch.setattr(mgr, "_hard_reset_on_cooldown", lambda: False)
    monkeypatch.setattr(mgr, "_mark_hard_reset", lambda: None)
    monkeypatch.setattr(mgr, "_WD_INTERVAL", 0.01)
    exits = []
    monkeypatch.setattr(mgr.os, "_exit", lambda code: exits.append(code))

    sender = FakeSender()
    sender.usable = True                       # the link is fine; the radio is not
    sender.registration_ok = lambda: _false()
    sender.soft_recover = _noop
    sender.hard_reset = _noop
    m = _mgr(sender)

    async def run():
        task = asyncio.create_task(m.watchdog_loop())
        started = asyncio.get_event_loop().time()
        while not exits and asyncio.get_event_loop().time() - started < 5.0:
            await asyncio.sleep(0.01)
        task.cancel()
        return asyncio.get_event_loop().time() - started

    elapsed = asyncio.run(run())
    assert exits == [1], "the registration ladder must still reach the exit"
    assert elapsed >= 0.3, "a modem that was reset must not be restarted into its reboot"


async def _false():
    return False


async def _noop():
    return None


def test_a_reopened_link_lets_the_ladder_come_all_the_way_down():
    """The watchdog no longer acts on a lost link, but it must still see one — and stop
    counting it against the radio once the linker has put the port back."""
    sender = FakeSender()
    m = _mgr(sender)

    assert asyncio.run(m._watchdog_step()) == "wait", "the linker owns the port"
    assert m._health.fails == 0, "a lost link must not accumulate against the radio"

    asyncio.run(_linker_pass(m))
    assert asyncio.run(m._watchdog_step()) == "ok"
    assert m._health.cause is None
