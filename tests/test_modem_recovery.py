import asyncio

from app.modem.at_commands import ATSerial, ATCommandError


class Rec:
    """Replaces ATSerial.command: records calls, returns canned responses."""
    def __init__(self, responses=None, raise_for=()):
        self.calls = []
        self.responses = responses or {}
        self.raise_for = set(raise_for)

    async def __call__(self, cmd, timeout=5.0):
        self.calls.append(cmd)
        if cmd in self.raise_for:
            raise ATCommandError(f"{cmd} failed")
        return self.responses.get(cmd, "OK")


def _serial(rec):
    s = ATSerial("/dev/null")
    s.command = rec
    return s


def test_registration_ok_true_home_and_roaming():
    assert asyncio.run(_serial(Rec({"AT+CEREG?": "+CEREG: 0,1"})).registration_ok()) is True
    assert asyncio.run(_serial(Rec({"AT+CEREG?": "+CEREG: 2,5"})).registration_ok()) is True


def test_registration_ok_false_not_registered_and_error():
    assert asyncio.run(_serial(Rec({"AT+CEREG?": "+CEREG: 0,0"})).registration_ok()) is False
    assert asyncio.run(_serial(Rec(raise_for={"AT+CEREG?"})).registration_ok()) is False


def test_soft_recover_sequence():
    rec = Rec()
    asyncio.run(_serial(rec).soft_recover())
    assert rec.calls == ["AT+CFUN=4", "AT+CFUN=1", "AT+COPS=0"]


def test_hard_reset_issues_cfun_and_swallows_error():
    rec = Rec(raise_for={"AT+CFUN=1,1"})
    asyncio.run(_serial(rec).hard_reset())
    assert rec.calls == ["AT+CFUN=1,1"]
