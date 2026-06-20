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
    sender = FakeSender({}, raise_for={"AT"})
    out = asyncio.run(_mgr(sender).collect_diagnostics())
    assert len(out) == 1
    assert out[0]["key"] == "alive" and "error" in out[0]
    assert sender.calls == ["AT"]
