import asyncio

import app.modem.manager as mgr
from app.modem.manager import ModemManager


class FakeSender:
    def __init__(self, reg_results):
        self.reg_results = list(reg_results)
        self.soft = 0
        self.hard = 0

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
