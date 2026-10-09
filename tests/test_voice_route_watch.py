"""The watcher inside the watchdog's tick — the dangerous half.

What this pins is not the state machine (that is `test_voice_route.py`) but the three
ways placing an observation here has already gone wrong in this codebase: it can be
switched off by a setting meant for something else, it can stop the recovery ladder
advancing, and it can swallow the exit that must follow a hard reset.
"""

import asyncio

import pytest

import app.modem.manager as mgr
import app.modem.voice_route as vr
from app.modem.manager import ModemManager


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(mgr, "_RECOVERY_SETTLE", 0.01)
    monkeypatch.setattr(mgr, "_RECOVERY_POLL", 0.005)
    monkeypatch.setattr(mgr, "_WD_HARD_RESET_SETTLE", 0.01)


class FakeSender:
    """Answers the two things the tick asks: registration, and the IMS register."""

    # `health_snapshot` reads this off the sender; the healthy default, as the
    # page-suite fakes on master already have it.
    caller_id_subscribed = True

    def __init__(self, *, registered=True, ims='+QCFG: "ims",1,1', raise_ims=False):
        self.registered = registered
        self.ims = ims
        self.raise_ims = raise_ims
        self.usable = True
        self.in_service = True
        self.link_lost = asyncio.Event()
        self.commands = []
        self.soft = 0
        self.hard = 0

    async def registration_ok(self):
        return self.registered

    async def command(self, cmd, timeout=5.0):
        self.commands.append(cmd)
        if self.raise_ims:
            raise RuntimeError("the port is having a bad day")
        return self.ims

    async def soft_recover(self):
        self.soft += 1

    async def hard_reset(self):
        self.hard += 1

    def link_snapshot(self):
        return {"link": "open", "link_last_good": "—", "link_reopens": 0}


def _mgr(sender):
    m = ModemManager("/dev/null", "/dev/null")
    m._sender = sender
    return m


@pytest.fixture
def delivered(monkeypatch):
    """What actually reached the notifier — not what the latch believes.

    `notify()` returns silently for an event type it does not know, so a test that
    asserts on the watcher's own state would be green while nothing was delivered.
    """
    sent = []
    monkeypatch.setattr(mgr, "notify",
                        lambda event, text, **kw: sent.append((event, text)))
    return sent


def test_the_alert_is_delivered_and_not_merely_latched(delivered):
    m = _mgr(FakeSender(ims='+QCFG: "ims",1,0'))
    asyncio.run(m._observe_voice_route())
    assert [e for e, _ in delivered] == [vr.ROUTE]


def test_the_two_conditions_are_delivered_as_different_events(delivered):
    """The ERROR handler dedups per template and `notify` per event type; one shared
    signature would let whichever came second hide behind the first."""
    m = _mgr(FakeSender(ims='+QCFG: "ims",2,0'))
    asyncio.run(m._observe_voice_route())
    assert sorted(e for e, _ in delivered) == sorted([vr.CONFIG, vr.ROUTE])


def test_the_module_off_the_network_raises_no_route_alert(delivered):
    m = _mgr(FakeSender(registered=False, ims='+QCFG: "ims",1,0'))
    for _ in range(5):
        asyncio.run(m._observe_voice_route())
    assert [e for e, _ in delivered if e == vr.ROUTE] == []


def test_the_configuration_is_still_read_off_the_network(delivered):
    """It is a local register, answered out of the module's own memory while it is
    still attaching — and a deploy coming up on a drifted configuration should say so
    at once rather than wait for an attach."""
    m = _mgr(FakeSender(registered=False, ims='+QCFG: "ims",0,0'))
    asyncio.run(m._observe_voice_route())
    assert [e for e, _ in delivered] == [vr.CONFIG]


def test_observing_runs_above_the_watchdog_switch(monkeypatch, delivered):
    """The switch governs remedies, not observation. An operator silencing the watchdog
    to investigate a flapping registration must not thereby opt out of ever learning
    the voice route is gone."""
    monkeypatch.setitem(mgr.store._cache, "modem_watchdog_enabled", "false")
    sender = FakeSender(ims='+QCFG: "ims",1,0')
    m = _mgr(sender)
    asyncio.run(_one_tick(m))
    assert [e for e, _ in delivered] == [vr.ROUTE]
    assert sender.soft == 0 and sender.hard == 0


async def _one_tick(m):
    """Drive exactly one pass of the loop body, then stop it."""
    ticks = {"n": 0}

    async def once():
        if ticks["n"]:
            raise asyncio.CancelledError
        ticks["n"] += 1

    m._wait_for_tick = once
    with pytest.raises(asyncio.CancelledError):
        await m.watchdog_loop()


def test_a_raising_reading_does_not_stop_the_ladder(monkeypatch, delivered):
    """Placed before the decision, a raising read stops the ladder advancing for as long
    as the fault lasts — and the fault is exactly when the ladder is needed."""
    monkeypatch.setattr(mgr, "_hard_reset_on_cooldown", lambda: False)
    sender = FakeSender(registered=False, raise_ims=True)
    m = _mgr(sender)
    m._wd_soft_tried = True
    m._wd_fails = 10
    assert asyncio.run(m._observe_voice_route()) is not None
    assert asyncio.run(m._watchdog_step()) == "hard"
    assert sender.hard == 1


def test_a_raising_reading_is_recorded_as_unmeasured(delivered):
    m = _mgr(FakeSender(raise_ims=True))
    asyncio.run(m._observe_voice_route())
    assert m.health_snapshot()["voice_route"] == "not measured"


def test_the_exit_after_a_hard_reset_still_happens(monkeypatch, delivered):
    """Placed at the end of the tick, the observation swallows the returned rung and
    with it the settle and the `os._exit(1)` that must follow a hard reset."""
    monkeypatch.setattr(mgr, "_hard_reset_on_cooldown", lambda: False)
    monkeypatch.setattr(mgr, "_mark_hard_reset", lambda: None)
    exits = []
    monkeypatch.setattr(mgr.os, "_exit", lambda code: exits.append(code))
    sender = FakeSender(registered=False, raise_ims=True)
    m = _mgr(sender)
    m._wd_soft_tried = True
    m._wd_fails = 10
    asyncio.run(_one_tick(m))
    assert sender.hard == 1
    assert exits == [1]


def test_the_tick_reads_the_register_once(delivered):
    m = _mgr(FakeSender())
    asyncio.run(m._observe_voice_route())
    assert m._sender.commands == ['AT+QCFG="ims"']


def test_the_registration_poll_is_not_paid_for_twice(monkeypatch, delivered):
    """The observation needs the registration answer and so does the step. Two answers
    from two moments are not a pair, and a second `AT+CEREG?` per tick is a command
    added to the path that is worst exactly when the port is worst."""
    polls = {"n": 0}
    sender = FakeSender()

    async def counted():
        polls["n"] += 1
        return True

    sender.registration_ok = counted
    m = _mgr(sender)
    asyncio.run(_one_tick(m))
    assert polls["n"] == 1


def test_the_page_reports_the_route_and_when_it_was_measured(delivered):
    m = _mgr(FakeSender())
    asyncio.run(m._observe_voice_route())
    snap = m.health_snapshot()
    assert snap["voice_route"] == "available"
    assert snap["voice_route_config"] == "enabled compulsorily"
    assert snap["voice_route_measured"] != "—"
