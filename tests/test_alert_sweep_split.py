"""Gathering an alert's evidence costs no more than the evidence itself.

The alert path runs while the modem is by definition already misbehaving, and it holds
the command port for the whole sweep — so every command on it delays the alert, the
recovery behind it, and any send queued behind the lock. Today it ran the entire
fourteen-command sweep to print four readings.
"""

import asyncio

from app.modem.manager import ModemManager, _DIAG_QUERIES
from app.modem.diag import ALERT_KEYS, summarise_for_alert


class CountingSender:
    in_service = True
    # `health_snapshot` reads this off the sender; the healthy default, as the
    # page-suite fakes on master already have it.
    caller_id_subscribed = True

    def __init__(self):
        self.calls = []

    async def command(self, cmd, timeout=5.0):
        self.calls.append(cmd)
        return {
            "AT+CPIN?": "+CPIN: READY",
            "AT+CREG?": "+CREG: 0,1",
            "AT+CSQ": "+CSQ: 17,99",
            "AT+COPS?": '+COPS: 0,0,"Tele2",7',
        }.get(cmd, "OK")

    def link_snapshot(self):
        return {"link": "open", "link_last_good": "—", "link_reopens": 0}


def _mgr():
    m = ModemManager("/dev/null", "/dev/null")
    m._sender = CountingSender()
    return m


def _alert_commands(mgr) -> list[str]:
    asyncio.run(mgr._alert_observations())
    return [c for c in mgr._sender.calls if c != "AT"]


def test_the_alert_asks_only_for_what_it_prints():
    mgr = _mgr()
    asked = _alert_commands(mgr)
    wanted = [cmd for key, cmd, _, _ in _DIAG_QUERIES if key in ALERT_KEYS]
    assert sorted(asked) == sorted(wanted)
    assert len(asked) == len(ALERT_KEYS)


def test_a_reading_added_to_the_page_does_not_lengthen_the_alert():
    """The pressure this removes: without it, every reading added to the page lengthens
    every future incident, and the page is the only place a fault is visible."""
    before = len(_alert_commands(_mgr()))
    assert before < len(_DIAG_QUERIES)
    assert before == len(ALERT_KEYS)


def test_what_the_alert_prints_and_what_it_asks_for_are_one_declaration():
    """Split into two lists they drift, and the drift is silent in the worst direction:
    a reading never asked for renders as `?`, which is exactly how a modem that failed
    to answer renders."""
    mgr = _mgr()
    line = asyncio.run(mgr._alert_observations())
    assert "?" not in line, line
    asked = set(_alert_commands(mgr))
    for key in ALERT_KEYS:
        cmd = next(c for k, c, _, _ in _DIAG_QUERIES if k == key)
        assert cmd in asked, f"{key} is printed but never asked for"


def test_the_alert_still_says_so_when_the_modem_answers_nothing():
    """The behaviour `_alert_observations` exists for, which must survive the split."""
    class Dead(CountingSender):
        async def command(self, cmd, timeout=5.0):
            self.calls.append(cmd)
            raise TimeoutError("nothing")

    mgr = ModemManager("/dev/null", "/dev/null")
    mgr._sender = Dead()
    assert "observations unavailable" in asyncio.run(mgr._alert_observations())
