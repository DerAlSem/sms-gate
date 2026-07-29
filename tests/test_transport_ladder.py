"""The recovery ladder meeting a lost link rather than an unhappy radio.

Two failures put the gateway down for five hours on 2026-07-29, and the second is the
subtler one. First, the poll raised instead of answering, so no failure was ever counted
and the ladder stood still. But even a corrected count would not have saved it: every rung
of this ladder is an AT command, and a port that is gone cannot carry one — each rung would
have raised in turn, aborting the step before it could return the rung whose service exit
is the only thing that reopens the port.

So the rungs are escalation *levels*, and the remedy at each level belongs to the cause.
"""

import asyncio

import pytest

import app.modem.manager as mgr
from app.modem.manager import ModemManager
from app.modem.at_commands import ATCommandError, ModemTransportError
from app.modem.health import (
    ModemHealth,
    OK,
    WAIT,
    SOFT,
    COOLDOWN,
    HARD,
    REGISTRATION,
    TRANSPORT,
)


@pytest.fixture(autouse=True)
def _fast_recovery(monkeypatch):
    monkeypatch.setattr(mgr, "_RECOVERY_SETTLE", 0.1)
    monkeypatch.setattr(mgr, "_RECOVERY_POLL", 0.005)
    monkeypatch.setattr(mgr, "_RECOVERY_TIMEOUT", 2.0)


def _health():
    return ModemHealth(fail_threshold=3, stall_threshold=3)


def _decide(h, **kw):
    kw.setdefault("registered", True)
    kw.setdefault("stalled", False)
    kw.setdefault("hard_reset_allowed", True)
    kw.setdefault("link_lost", False)
    return h.decide(**kw)


# --- the pure ladder ----------------------------------------------------------


def test_a_lost_link_acts_on_the_first_observation():
    """Three polls exist to absorb one unlucky registration sample. A port that cannot
    be written is not a sample, and waiting three minutes to act on it buys nothing."""
    h = _health()
    assert _decide(h, link_lost=True) == SOFT
    assert h.cause == TRANSPORT


def test_a_lost_link_that_persists_reaches_the_service_exit():
    h = _health()
    assert _decide(h, link_lost=True) == SOFT
    assert _decide(h, link_lost=True) == HARD


def test_the_exit_for_a_lost_link_is_not_gated_by_the_hard_reset_cooldown():
    """The cooldown exists so the modem is not hammered with resets. Exiting is not a
    reset — nothing is being hammered — and the supervisor's own restart limits bound it.
    Gating it would leave the gateway unusable for up to half an hour."""
    h = _health()
    _decide(h, link_lost=True)
    assert _decide(h, link_lost=True, hard_reset_allowed=False) == HARD


def test_a_registration_outage_still_needs_three_polls():
    h = _health()
    assert _decide(h, registered=False) == WAIT
    assert _decide(h, registered=False) == WAIT
    assert _decide(h, registered=False) == SOFT


def test_the_ladder_restarts_when_a_registration_outage_becomes_a_lost_link():
    """Progress up the ladder belongs to the problem that earned it."""
    h = _health()
    _decide(h, registered=False)
    _decide(h, registered=False)
    assert _decide(h, registered=False) == SOFT
    assert h.cause == REGISTRATION
    # The link goes; the soft recovery already performed was for a different problem.
    assert _decide(h, link_lost=True) == SOFT
    assert h.cause == TRANSPORT


def test_a_restored_link_clears_the_ladder():
    h = _health()
    _decide(h, link_lost=True)
    assert _decide(h) == OK
    assert h.cause is None


# --- the ladder driven through the manager ------------------------------------


class _DeadLinkSender:
    """A sender whose port is gone: every AT exchange raises, as it would in production."""

    def __init__(self):
        self.soft = 0
        self.hard = 0
        self.usable = False
        self.link_lost = asyncio.Event()
        self.link_lost.set()

    async def registration_ok(self):
        raise ModemTransportError("link to /dev/ttyUSB2 lost: gone")

    async def soft_recover(self):
        self.soft += 1
        raise ModemTransportError("link to /dev/ttyUSB2 lost: gone")

    async def hard_reset(self):
        self.hard += 1
        raise ModemTransportError("link to /dev/ttyUSB2 lost: gone")


def _mgr(sender):
    m = ModemManager("/dev/null", "/dev/null")
    m._sender = sender
    return m


def test_a_dead_port_reaches_the_exit_instead_of_looping():
    """The incident itself: the poll raised, escaped the step, and was swallowed 316
    times over five hours while the ladder never advanced a single rung."""
    m = _mgr(_DeadLinkSender())
    first = asyncio.run(m._watchdog_step())
    second = asyncio.run(m._watchdog_step())
    assert (first, second) == (SOFT, HARD)


def test_no_at_remedy_is_issued_against_a_port_that_is_gone():
    """Every rung of the registration ladder is an AT command. Spending them on a
    missing port is the incident's failure mode reached by a different route."""
    sender = _DeadLinkSender()
    m = _mgr(sender)
    asyncio.run(m._watchdog_step())
    asyncio.run(m._watchdog_step())
    assert sender.soft == 0, "a radio cycle was issued into a port that is not there"
    assert sender.hard == 0, "a modem reset was issued into a port that is not there"


class _RaisingSender:
    """A live-looking port whose remedies fail — the rung cannot be carried out."""

    def __init__(self):
        self.soft = 0
        self.hard = 0
        self.usable = True
        self.link_lost = asyncio.Event()

    async def registration_ok(self):
        return False

    async def soft_recover(self):
        self.soft += 1
        raise ModemTransportError("port vanished mid-recovery")

    async def hard_reset(self):
        self.hard += 1
        raise ModemTransportError("port vanished mid-reset")


def test_a_remedy_that_cannot_be_carried_out_does_not_abort_the_ladder():
    """`_recover` caught only `asyncio.TimeoutError`, and `hard_reset` only an AT
    failure, so a rung that raised took the whole step with it — and the step is what
    returns the level that ends the process."""
    sender = _RaisingSender()
    m = _mgr(sender)
    levels = [asyncio.run(m._watchdog_step()) for _ in range(6)]
    assert SOFT in levels, f"the ladder never attempted a remedy: {levels}"
    assert levels[-1] in (HARD, COOLDOWN), f"the ladder stalled instead of escalating: {levels}"


class _UnpollableSender:
    """A poll that fails in some way nobody anticipated."""

    def __init__(self):
        self.soft = 0
        self.usable = True
        self.link_lost = asyncio.Event()

    async def registration_ok(self):
        raise RuntimeError("something nobody wrote a handler for")

    async def soft_recover(self):
        self.soft += 1

    async def hard_reset(self):
        pass


def test_a_poll_that_cannot_be_completed_counts_as_a_failed_poll():
    """The watchdog acts on doubt, and an exception is a stronger form of doubt than a
    negative answer. A poll whose failure is discarded leaves the ladder standing still
    for as long as the fault lasts."""
    m = _mgr(_UnpollableSender())
    levels = [asyncio.run(m._watchdog_step()) for _ in range(3)]
    assert levels == [WAIT, WAIT, SOFT], levels


# --- the switch, and who notices first ----------------------------------------


def test_a_lost_link_is_acted_on_even_when_the_watchdog_is_disabled(monkeypatch):
    """The switch exists so an operator can take over judgement about an unhealthy
    *modem*. A port that does not exist is not that kind of judgement call — there is no
    policy under which the right answer is to keep writing to it — so silencing the
    watchdog must not silently opt out of ever recovering the port."""
    monkeypatch.setattr(mgr, "_WD_INTERVAL", 0.01)
    monkeypatch.setattr(mgr, "_WD_HARD_RESET_SETTLE", 0.01)
    # Through the cache, not `setattr` on the store: the settings are served by
    # `__getattr__`, so patching the attribute writes a real one — and monkeypatch's undo
    # restores the value it read *through* `__getattr__`, leaving the setting pinned as an
    # instance attribute for every test that runs after this one.
    monkeypatch.setitem(mgr.store._cache, "modem_watchdog_enabled", "false")

    exits = []
    monkeypatch.setattr(mgr.os, "_exit", lambda code: exits.append(code))

    m = _mgr(_DeadLinkSender())

    async def run():
        # The loop exits by calling os._exit, which the patch turns into a record; give
        # it a couple of ticks and then stop it.
        task = asyncio.get_event_loop().create_task(m.watchdog_loop())
        await asyncio.sleep(0.15)
        task.cancel()

    asyncio.run(run())
    assert exits, "the link stayed unusable for ever because the watchdog was switched off"


def test_the_send_paths_observation_wakes_the_watchdog_without_waiting_a_full_interval():
    """`_wait_for_tick` returns as soon as the link is reported gone, instead of
    sleeping out the poll interval that the sender already has the answer for."""

    async def run():
        sender = _DeadLinkSender()  # its link_lost event is already set
        m = _mgr(sender)
        started = asyncio.get_event_loop().time()
        await m._wait_for_tick()
        return asyncio.get_event_loop().time() - started, sender.link_lost.is_set()

    elapsed, still_set = asyncio.run(run())
    assert elapsed < 1.0, f"waited {elapsed:.1f}s for news it already had"
    assert not still_set, "the wake signal was not cleared, so the loop would spin"
