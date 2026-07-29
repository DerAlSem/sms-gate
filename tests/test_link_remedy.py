"""The remedy for a lost link: reopen the port, and restart only once that has failed.

Before this, every re-enumeration cost a process restart — the in-memory send queue
dropped, startup re-run, a restart cycle in the journal — for a device that was physically
absent for a few seconds. What has to stay true is the shape around the reopen: sending
suspended for its whole duration and resumed however it ended, and the restart still
reached when reopening does not work.
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


class FakeSender:
    """A command port whose link can be lost and whose reopen can be scripted."""

    def __init__(self, reopen=True, on_reconnect=None):
        self.usable = False
        self.link_lost = asyncio.Event()
        self.reopens = 0
        self._reopen = reopen
        self._on_reconnect = on_reconnect
        self.port = "/dev/ttyUSB2"

    async def registration_ok(self):
        # As `ATSerial` does: on a link that is gone there is no question to answer.
        if not self.usable:
            raise ModemTransportError("link to /dev/ttyUSB2 is not open")
        return True

    async def reconnect(self, *, init=True):
        if self._on_reconnect:
            await self._on_reconnect()
        if not self._reopen:
            # As `ATSerial.reconnect` does when its budget runs out: whoever escalates
            # should not spend another whole interval rediscovering this.
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
    return m


def test_the_gentle_rung_reopens_the_link_rather_than_waiting_for_a_restart():
    sender = FakeSender()
    m = _mgr(sender)

    assert asyncio.run(m._watchdog_step()) == "soft"
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
        watcher = asyncio.create_task(m._watchdog_step())
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

    assert asyncio.run(m._watchdog_step()) == "soft"
    assert m._modem_gate.is_set() is True


def test_exhausted_attempts_still_reach_the_service_exit():
    """The restart did not go away — it became what an exhausted reopen earns."""
    sender = FakeSender(reopen=False)
    m = _mgr(sender)

    assert asyncio.run(m._watchdog_step()) == "soft"
    assert sender.usable is False
    assert asyncio.run(m._watchdog_step()) == "hard"
    assert m._modem_gate.is_set() is True, "the restart path must not strand the gate"


def test_a_self_healing_reopen_alerts_once_and_says_it_healed(monkeypatch):
    """Found on prod 2026-07-29: the reopen sent three red alerts for a pause that healed
    itself in fourteen seconds, where the restart it replaced sent one. Alerting more for
    a better outcome teaches an operator to stop reading them — which is the masked fault
    the reopen count exists to prevent, reached from the other side."""
    sent = []
    monkeypatch.setattr(mgr, "notify", lambda *a, **kw: sent.append((a, kw)))

    m = _mgr(FakeSender())
    asyncio.run(m._watchdog_step())

    assert len(sent) == 1, f"one alert per outage, once the outcome is known: {sent}"
    (event, text), kwargs = sent[0]
    assert event == "link"
    assert "without restarting" in text, "the alert must say the gateway survived it"
    assert kwargs["dedup_extra"] == "/dev/ttyUSB2", "a flapping modem is one per window"


def test_the_steps_on_the_way_to_a_reopen_do_not_alert(caplog):
    """The alert handler listens at ERROR. Nothing on the successful path may reach it —
    the failure rungs still do."""
    import logging

    m = _mgr(FakeSender())
    with caplog.at_level(logging.DEBUG):
        asyncio.run(m._watchdog_step())

    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors == [], f"a self-healing reopen must raise no ERROR: {errors}"


def test_a_reopen_that_failed_still_alerts_loudly(caplog):
    import logging

    m = _mgr(FakeSender(reopen=False))
    with caplog.at_level(logging.DEBUG):
        asyncio.run(m._watchdog_step())

    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("restarted" in e for e in errors), errors


def test_giving_up_on_a_lost_link_exits_without_the_hard_reset_settle(monkeypatch):
    """The settle exists so nothing touches a modem the gateway has just reset. A lost
    link is reached without issuing one AT command, so there is nothing rebooting to wait
    for — and on prod 2026-07-29 the device came back five seconds after the reopen gave
    up, while the gateway spent the next forty seconds not looking."""
    from app.settings_store import store

    monkeypatch.setitem(store._cache, "modem_watchdog_enabled", "true")
    monkeypatch.setattr(mgr, "_WD_HARD_RESET_SETTLE", 30.0)
    monkeypatch.setattr(mgr, "_WD_INTERVAL", 0.01)
    exits = []
    monkeypatch.setattr(mgr.os, "_exit", lambda code: exits.append(code))

    m = _mgr(FakeSender(reopen=False))

    async def run():
        task = asyncio.create_task(m.watchdog_loop())
        started = asyncio.get_event_loop().time()
        while not exits:
            await asyncio.sleep(0.01)
            if asyncio.get_event_loop().time() - started > 5.0:
                break
        task.cancel()
        return asyncio.get_event_loop().time() - started

    elapsed = asyncio.run(run())
    assert exits == [1]
    assert elapsed < 5.0, f"waited {elapsed:.0f}s on a settle that protects nothing"


def test_a_deliberate_reset_still_gets_its_settle(monkeypatch):
    """The other half: a modem that *was* reset must not be restarted into mid-reboot."""
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
    sender = FakeSender()
    m = _mgr(sender)

    assert asyncio.run(m._watchdog_step()) == "soft"
    assert asyncio.run(m._watchdog_step()) == "ok"
    assert m._health.cause is None
