import asyncio

from app.modem.manager import ModemManager
from app.modem.at_commands import ATCommandError


class FakeSender:
    def __init__(self, responses, raise_for=()):
        self.responses = responses
        self.raise_for = set(raise_for)
        self.calls = []

    async def command(self, cmd, timeout=5.0):
        self.calls.append(cmd)
        if cmd in self.raise_for:
            raise ATCommandError(f"{cmd} failed")
        return self.responses.get(cmd, "OK")

    def link_snapshot(self):
        # The snapshot now carries the link's own state alongside the modem's.
        return {"link": "open", "link_last_good": "—", "link_reopens": 0}


def _mgr(sender):
    m = ModemManager("/dev/null", "/dev/null")
    m._sender = sender
    return m


def test_collect_parses_and_captures_errors():
    responses = {
        "AT": "OK",
        "AT+CPIN?": "+CPIN: READY",
        "AT+CEREG?": "+CEREG: 0,1",
        "AT+CSQ": "+CSQ: 17,99",
        "AT+COPS?": '+COPS: 0,0,"Tele2",7',
        "AT+CSCA?": '+CSCA: "+79262000331",145',
    }
    sender = FakeSender(responses, raise_for={"AT+QCSQ"})
    out = asyncio.run(_mgr(sender).collect_diagnostics())
    by_key = {i["key"]: i for i in out}
    assert by_key["sim"]["parsed"] == {"state": "READY"}
    assert by_key["eps_reg"]["parsed"]["status"] == "registered (home)"
    assert by_key["signal"]["parsed"]["dbm"] == -79
    assert "error" in by_key["signal_lte"]
    assert "raw" not in by_key["signal_lte"]
    assert "AT" in sender.calls


def test_collect_short_circuits_on_dead_modem():
    """A wedged modem still gets the gateway's own view first — that is precisely when
    the operator needs to know whether a recovery is running and the radio is off on
    purpose."""
    sender = FakeSender({}, raise_for={"AT"})
    out = asyncio.run(_mgr(sender).collect_diagnostics())
    assert [item["key"] for item in out] == ["gateway", "alive"]
    assert "error" in out[1]
    assert sender.calls == ["AT"]


def test_collect_reports_what_the_gateway_believes():
    sender = FakeSender({})
    m = _mgr(sender)
    m._modem_gate.clear()
    out = asyncio.run(m.collect_diagnostics())
    assert out[0]["key"] == "gateway"
    assert out[0]["parsed"]["recovering"] is True
