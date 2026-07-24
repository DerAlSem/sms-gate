"""Send failures as evidence the modem needs recovery, and the gate that stops
recovery from manufacturing the failures it reacts to.

Two loops share one modem here, so most of these tests are about what happens *between*
them: the sender contributes evidence, the watchdog acts on it, and each has to leave the
other in a workable state.
"""

import asyncio

import pytest

import app.modem.manager as mgr
from app.modem.manager import ModemManager


class FakeSender:
    def __init__(self, reg_results=(), recover_raises=False):
        self.reg_results = list(reg_results)
        self.soft = 0
        self.hard = 0
        self._recover_raises = recover_raises
        self.gate_open_during_recovery = None

    async def registration_ok(self):
        return self.reg_results.pop(0) if self.reg_results else False

    async def soft_recover(self):
        self.soft += 1
        if self._recover_raises:
            raise RuntimeError("modem is not listening")

    async def hard_reset(self):
        self.hard += 1


def _mgr(reg_results=(), **kw):
    m = ModemManager("/dev/null", "/dev/null")
    m._sender = FakeSender(reg_results, **kw)
    return m


def _fail(m, message_id, *, error="no response from modem (timeout)", exhausted=False):
    m._note_send_failure(message_id, error, exhausted=exhausted)


# ------------------------------------------------------------------ the stall signal


def test_three_distinct_messages_stall_the_modem():
    m = _mgr()
    _fail(m, 1)
    _fail(m, 2)
    assert m._stalled is False
    _fail(m, 3)
    assert m._stalled is True


def test_one_message_failing_repeatedly_is_evidence_about_its_destination():
    """Its four attempts are one message. Only exhausting the ladder — eight minutes
    with nothing getting out — makes it evidence about the modem."""
    m = _mgr()
    for _ in range(3):
        _fail(m, 1)
    assert m._stalled is False


def test_a_message_that_exhausts_its_whole_budget_stalls_the_modem():
    m = _mgr()
    _fail(m, 1, exhausted=True)
    assert m._stalled is True


def test_a_successful_send_clears_the_evidence():
    m = _mgr()
    _fail(m, 1)
    _fail(m, 2)
    m._note_send_success()
    _fail(m, 3)
    assert m._stalled is False


def test_permanent_failures_are_neutral():
    """They say something about the number, not the modem — and must not clear a stall
    either, or a stream of bad numbers would mask a dead radio."""
    m = _mgr()
    for i in (1, 2, 3):
        _fail(m, i, error="+CMS ERROR 1 (unassigned number)")
    assert m._stalled is False

    _fail(m, 4)
    _fail(m, 5)
    _fail(m, 6, error="+CMS ERROR 1 (unassigned number)")
    _fail(m, 7)
    assert m._stalled is True


def test_a_message_rejected_before_the_modem_is_neutral():
    m = _mgr()
    for i in (1, 2, 3):
        _fail(m, i, error="message too long: 8 parts > max 6")
    assert m._stalled is False


# ---------------------------------------------------------------- driving the ladder


def test_a_stall_fails_the_health_check_even_when_registration_is_fine():
    m = _mgr([True, True, True])
    _fail(m, 1, exhausted=True)
    assert asyncio.run(m._watchdog_step()) == "wait"
    assert m._wd_fails == 1


def test_a_stall_escalates_on_the_existing_ladder():
    m = _mgr([True] * 3)
    _fail(m, 1, exhausted=True)
    assert asyncio.run(m._watchdog_step()) == "wait"
    _fail(m, 2, exhausted=True)
    assert asyncio.run(m._watchdog_step()) == "wait"
    _fail(m, 3, exhausted=True)
    assert asyncio.run(m._watchdog_step()) == "soft"
    assert m._sender.soft == 1


def test_recovery_consumes_the_evidence():
    """Otherwise a stall declared on a quiet gateway survives — nothing being sent that
    could clear it — and drives the ladder to a service restart on evidence already
    acted upon."""
    m = _mgr([True] * 6)
    for _ in range(3):
        _fail(m, 1, exhausted=True)
        asyncio.run(m._watchdog_step())
    assert m._sender.soft == 1
    assert m._stalled is False, "recovery must consume what it reacted to"

    # An hour of silence: no sends, so nothing can clear a stall — and none remains.
    for _ in range(3):
        assert asyncio.run(m._watchdog_step()) == "ok"
    assert m._sender.hard == 0


def test_a_healthy_send_after_a_stall_restores_the_health_check():
    m = _mgr([True, True])
    _fail(m, 1, exhausted=True)
    assert asyncio.run(m._watchdog_step()) == "wait"
    m._note_send_success()
    assert asyncio.run(m._watchdog_step()) == "ok"
    assert m._wd_fails == 0


def test_a_disabled_watchdog_discards_the_evidence(monkeypatch):
    """With the watchdog off, recovery is the operator's job — so the gateway must not
    keep accumulating a suspicion nothing will ever act on."""
    monkeypatch.setattr(mgr, "_WD_INTERVAL", 0.01)
    monkeypatch.setattr(mgr.store, "modem_watchdog_enabled", False, raising=False)

    async def body():
        m = _mgr([True] * 5)
        _fail(m, 1, exhausted=True)
        task = asyncio.create_task(m.watchdog_loop())
        await asyncio.sleep(0.05)
        task.cancel()
        return m._stalled, m._sender.soft, m._sender.hard

    stalled, soft, hard = asyncio.run(body())
    assert stalled is False
    assert (soft, hard) == (0, 0), "a disabled watchdog must not recover anything"


# -------------------------------------------------------------------- the quiesce gate


def test_sending_is_suspended_while_recovery_runs():
    async def body():
        m = _mgr([True] * 3)
        seen = []

        async def watch_gate():
            await asyncio.sleep(0.01)
            seen.append(m._send_gate.is_set())

        for _ in range(2):
            _fail(m, 1, exhausted=True)
            await m._watchdog_step()

        async def slow_recover():
            m._sender.soft += 1
            await asyncio.sleep(0.05)

        m._sender.soft_recover = slow_recover
        _fail(m, 2, exhausted=True)
        watcher = asyncio.create_task(watch_gate())
        await m._watchdog_step()
        await watcher
        return seen, m._send_gate.is_set()

    seen, after = asyncio.run(body())
    assert seen == [False], "the gate must be closed while the radio is being cycled"
    assert after is True, "and reopened afterwards"


def test_the_gate_reopens_even_if_recovery_raises():
    """A gate left closed by an exception would stop the gateway sending at all until
    the next restart — the worst outcome in this change."""
    async def body():
        m = _mgr([True] * 3, recover_raises=True)
        for _ in range(3):
            _fail(m, 1, exhausted=True)
            try:
                await m._watchdog_step()
            except RuntimeError:
                pass
        return m._send_gate.is_set()

    assert asyncio.run(body()) is True


def test_the_hard_path_leaves_sending_suspended_until_the_process_exits(monkeypatch):
    """The service sleeps 40s after a hard reset before exiting; releasing the sender
    into a rebooting modem would manufacture the failures the gate exists to prevent."""
    monkeypatch.setattr(mgr, "_hard_reset_on_cooldown", lambda: False)
    monkeypatch.setattr(mgr, "_mark_hard_reset", lambda: None)

    async def body():
        m = _mgr([True] * 6)
        m._wd_soft_tried = True
        for _ in range(3):
            _fail(m, 1, exhausted=True)
            action = await m._watchdog_step()
        return action, m._send_gate.is_set()

    action, gate_open = asyncio.run(body())
    assert action == "hard"
    assert gate_open is False


def test_the_gate_timeout_outlasts_the_hard_reset_settle():
    assert mgr._SEND_GATE_TIMEOUT > mgr._WD_HARD_RESET_SETTLE


def test_a_stuck_gate_does_not_hold_the_sender_forever(monkeypatch):
    monkeypatch.setattr(mgr, "_SEND_GATE_TIMEOUT", 0.05)

    async def body():
        m = _mgr()
        m._send_gate.clear()
        await m._await_send_gate()          # must return rather than hang
        return True

    assert asyncio.run(asyncio.wait_for(body(), timeout=2)) is True
