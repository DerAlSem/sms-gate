import asyncio

from app.modem.manager import ModemManager
from app.modem.at_commands import ATCommandError


class FakeSender:
    def __init__(self, responses, raise_for=()):
        self.responses = responses
        self.raise_for = set(raise_for)
        self.calls = []

    in_service = True
    # As the real link reports it: the record, not a query.
    caller_id_subscribed = True

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
    # `calls` belongs with `gateway`: both are what the gateway knows about itself,
    # and neither costs the modem a command — which is why they survive a wedged one.
    assert [item["key"] for item in out] == ["gateway", "calls", "alive"]
    assert "error" in out[1]
    assert sender.calls == ["AT"]


def test_collect_reports_what_the_gateway_believes():
    sender = FakeSender({})
    m = _mgr(sender)
    m._modem_gate.clear()
    out = asyncio.run(m.collect_diagnostics())
    assert out[0]["key"] == "gateway"
    assert out[0]["parsed"]["recovering"] is True


# ------------------------------------------- the sweep carries an outcome, not a string

from app.modem.parser import VALUE, REFUSAL, SILENCE, FAILURE


class ReplyingSender(FakeSender):
    """A sender whose failures carry what the modem actually said, as the real one does."""

    def __init__(self, responses, refuse=None):
        super().__init__(responses)
        self.refuse = refuse or {}

    async def command(self, cmd, timeout=5.0):
        self.calls.append(cmd)
        if cmd in self.refuse:
            said = self.refuse[cmd]
            raise ATCommandError(f"{cmd}: {said}", response=said)
        return self.responses.get(cmd, "OK")


def _sweep(**kw):
    sender = ReplyingSender({"AT": "OK", **kw.pop("responses", {})}, **kw)
    return {i["key"]: i for i in asyncio.run(_mgr(sender).collect_diagnostics())}


def test_a_refusal_is_carried_as_a_refusal_with_what_the_modem_said():
    """`AT+CIREG?` on this build. The row must not claim the firmware lacks the command
    — only that the modem would not carry it out — and must show its words."""
    by_key = _sweep(refuse={"AT+CIREG?": "\r\nERROR\r\n"})
    assert by_key["ims_reg"]["outcome"] == REFUSAL
    assert "ERROR" in by_key["ims_reg"]["raw"]


def test_the_sim_fault_stays_a_fault():
    """The positive control. Without it, an implementation that renders everything as
    "not measured" passes: this is the reading that named the 2026-09-06 outage."""
    by_key = _sweep(refuse={"AT+CPIN?": "+CME ERROR: 13"})
    assert by_key["sim"]["outcome"] == FAILURE


def test_a_command_that_never_answered_is_a_silence():
    by_key = _sweep(refuse={"AT+CLIP?": ""})
    assert by_key["clip"]["outcome"] == SILENCE


def test_an_answered_row_is_a_value():
    by_key = _sweep(responses={"AT+CPIN?": "+CPIN: READY"})
    assert by_key["sim"]["outcome"] == VALUE
    assert by_key["sim"]["parsed"] == {"state": "READY"}


def test_the_voice_route_is_read_by_the_sweep():
    """Task 2.2: a register read the firmware answers out of its own memory — the
    vendor's maximum response time is 300 ms, so it is on the local budget."""
    by_key = _sweep(responses={'AT+QCFG="ims"': '+QCFG: "ims",1,1'})
    assert by_key["ims"]["parsed"]["config"] == "enabled compulsorily"
    assert by_key["ims"]["parsed"]["volte"] == "VoLTE enabled"
