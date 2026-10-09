import asyncio

import pytest

import app.modem.manager as mgr
from app.modem.manager import ModemManager


@pytest.fixture(autouse=True)
def _fast_recovery(monkeypatch):
    """Recovery now waits for the modem to reattach before letting sends resume; these
    tests are about the ladder, not that wait."""
    monkeypatch.setattr(mgr, "_RECOVERY_SETTLE", 0.1)
    monkeypatch.setattr(mgr, "_RECOVERY_POLL", 0.005)
    monkeypatch.setattr(mgr, "_RECOVERY_TIMEOUT", 2.0)


class FakeSender:
    def __init__(self, reg_results):
        self.reg_results = list(reg_results)
        self.soft = 0
        self.hard = 0
        # Mirrors ATSerial, which the manager now asks about the link itself — and
        # about the caller-ID subscription it holds, which the snapshot reports.
        self.usable = True
        self.caller_id_subscribed = True
        self.link_lost = asyncio.Event()

    async def registration_ok(self):
        return self.reg_results.pop(0) if self.reg_results else False

    async def soft_recover(self):
        self.soft += 1

    async def hard_reset(self):
        self.hard += 1


def _mgr(reg_results):
    m = ModemManager("/dev/null", "/dev/null")
    m._sender = FakeSender(reg_results)
    return m


def test_ok_resets_counters():
    m = _mgr([True])
    m._wd_fails = 2
    m._wd_soft_tried = True
    assert asyncio.run(m._watchdog_step()) == "ok"
    assert m._wd_fails == 0 and m._wd_soft_tried is False


def test_below_threshold_waits():
    m = _mgr([False])
    assert asyncio.run(m._watchdog_step()) == "wait"
    assert m._wd_fails == 1


def test_threshold_triggers_soft():
    m = _mgr([False, False, False])
    assert asyncio.run(m._watchdog_step()) == "wait"
    assert asyncio.run(m._watchdog_step()) == "wait"
    assert asyncio.run(m._watchdog_step()) == "soft"
    assert m._sender.soft == 1 and m._wd_soft_tried is True and m._wd_fails == 0


def test_still_down_after_soft_hard_resets(monkeypatch):
    monkeypatch.setattr(mgr, "_hard_reset_on_cooldown", lambda: False)
    marked = []
    monkeypatch.setattr(mgr, "_mark_hard_reset", lambda: marked.append(True))
    m = _mgr([False] * 6)
    m._wd_soft_tried = True
    for _ in range(2):
        assert asyncio.run(m._watchdog_step()) == "wait"
    assert asyncio.run(m._watchdog_step()) == "hard"
    assert m._sender.hard == 1 and marked == [True]


def test_cooldown_blocks_hard_does_soft(monkeypatch):
    monkeypatch.setattr(mgr, "_hard_reset_on_cooldown", lambda: True)
    m = _mgr([False] * 3)
    m._wd_soft_tried = True
    for _ in range(2):
        assert asyncio.run(m._watchdog_step()) == "wait"
    assert asyncio.run(m._watchdog_step()) == "cooldown"
    assert m._sender.hard == 0 and m._sender.soft == 1


def test_cooldown_helpers_with_tmp_marker(monkeypatch, tmp_path):
    marker = tmp_path / "hr"
    monkeypatch.setattr(mgr, "_hard_reset_marker", lambda: marker)
    assert mgr._hard_reset_on_cooldown() is False
    mgr._mark_hard_reset()
    assert mgr._hard_reset_on_cooldown() is True
    marker.write_text("1.0")
    assert mgr._hard_reset_on_cooldown() is False


# ------------------------------------------------- the alert carries observations

import logging


def _diag_sender(reg_results, *, at_ok=True, sim="READY", op="MTS"):
    """A sender that can also answer the diagnostics sweep the alert now collects."""
    s = FakeSender(reg_results)
    replies = {
        "AT": "OK",
        "AT+CPIN?": f"+CPIN: {sim}\r\nOK",
        "AT+CEREG?": "+CEREG: 0,2\r\nOK",
        "AT+CREG?": "+CREG: 0,2\r\nOK",
        "AT+CGREG?": "+CGREG: 0,2\r\nOK",
        "AT+CSQ": "+CSQ: 21,99\r\nOK",
        "AT+COPS?": f'+COPS: 0,0,"{op}",7\r\nOK',
        "AT+CSCA?": 'OK',
        "AT+QNWINFO": "OK",
        "AT+QCSQ": "OK",
    }

    async def command(cmd, timeout=None):
        if not at_ok:
            raise TimeoutError("no response from modem")
        return replies.get(cmd, "OK")

    s.command = command
    s.link_snapshot = lambda: {}
    s.in_service = True
    return s


def _mgr_diag(reg_results, **kw):
    m = ModemManager("/dev/null", "/dev/null")
    m._sender = _diag_sender(reg_results, **kw)
    return m


def _escalate(m, rungs=3):
    for _ in range(rungs - 1):
        asyncio.run(m._watchdog_step())
    return asyncio.run(m._watchdog_step())


def test_cooldown_alert_carries_the_readings(monkeypatch, caplog):
    monkeypatch.setattr(mgr, "_hard_reset_on_cooldown", lambda: True)
    m = _mgr_diag([False] * 12)
    with caplog.at_level(logging.ERROR, logger="app.modem.manager"):
        for _ in range(8):
            if asyncio.run(m._watchdog_step()) == "cooldown":
                break
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "the cooldown rung must still alert"
    text = errors[-1].getMessage()
    assert "SIM=READY" in text
    assert "MTS" in text


def test_alert_no_longer_asserts_the_antenna(monkeypatch, caplog):
    """The 2026-09-06 defect, pinned: the text named the two things that were working."""
    monkeypatch.setattr(mgr, "_hard_reset_on_cooldown", lambda: True)
    m = _mgr_diag([False] * 12)
    with caplog.at_level(logging.ERROR, logger="app.modem.manager"):
        for _ in range(8):
            if asyncio.run(m._watchdog_step()) == "cooldown":
                break
    text = caplog.records[-1].getMessage()
    assert "check antenna/operator" not in text


def test_alert_template_stays_constant_so_suppression_survives(monkeypatch, caplog):
    """TelegramAlertHandler dedups on record.msg — the TEMPLATE, not the text. The
    snapshot therefore has to ride as an argument; a formatted-in snapshot would make
    every escalation a new signature and turn one alert per window into a wall of them."""
    monkeypatch.setattr(mgr, "_hard_reset_on_cooldown", lambda: True)
    templates = set()
    for operator in ("MTS", "MegaFon"):
        m = _mgr_diag([False] * 12, op=operator)
        caplog.clear()
        with caplog.at_level(logging.ERROR, logger="app.modem.manager"):
            for _ in range(8):
                if asyncio.run(m._watchdog_step()) == "cooldown":
                    break
        rec = caplog.records[-1]
        assert operator in rec.getMessage()
        templates.add(rec.msg)
    assert len(templates) == 1, f"one signature expected, got {templates}"


def test_alert_says_so_when_the_modem_did_not_answer(monkeypatch, caplog):
    monkeypatch.setattr(mgr, "_hard_reset_on_cooldown", lambda: True)
    m = _mgr_diag([False] * 12, at_ok=False)
    with caplog.at_level(logging.ERROR, logger="app.modem.manager"):
        for _ in range(8):
            if asyncio.run(m._watchdog_step()) == "cooldown":
                break
    text = caplog.records[-1].getMessage()
    assert "unavailable" in text.lower()


def test_the_ladder_itself_is_unchanged(monkeypatch):
    """This change touches text only. Same rungs, same order, same remedy counts."""
    monkeypatch.setattr(mgr, "_hard_reset_on_cooldown", lambda: False)
    monkeypatch.setattr(mgr, "_mark_hard_reset", lambda: None)
    m = _mgr_diag([False] * 12)
    rungs = [asyncio.run(m._watchdog_step()) for _ in range(5)]
    assert rungs == ["wait", "wait", "soft", "wait", "wait"]
    assert asyncio.run(m._watchdog_step()) == "hard"
    assert m._sender.soft == 1 and m._sender.hard == 1
