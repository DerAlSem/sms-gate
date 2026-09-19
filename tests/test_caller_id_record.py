"""The caller-ID subscription as a fact the gateway holds, not one it reads back.

`AT+CLIP?` does not answer on this device — given eight seconds on the live modem it
spent all eight and said nothing — and `AT+CLIP=?` answers a different question, namely
that the firmware knows the command. So a precondition that can only be read from the
modem is, on this modem, one that can never be read, and the rung that depends on it
would be switched off forever.

What the gateway *can* know is its own act: whether `AT+CLIP=1` was last issued
successfully on the link generation now in service. That record is the precondition.

Two failures are covered here, and they are different failures. A recovery that cycles
`CFUN` may take the subscription with it — the firmware's choice, not ours — and today
`soft_recover` re-issues `CNMI` and not `CLIP`, on a docstring whose own argument covers
both. And an `AT+CLIP=1` that was refused leaves the gateway believing nothing, which is
correct, provided it actually records the refusal rather than logging it and moving on.
"""

import asyncio

import pytest

import app.modem.at_commands as at
from app.modem.at_commands import ATCommandError, ATSerial, CNMI_SUBSCRIBE


class _Rec:
    """Replaces `ATSerial.command`: records calls, and may refuse chosen ones."""

    def __init__(self, raise_for=()):
        self.calls = []
        self.raise_for = set(raise_for)

    async def __call__(self, cmd, timeout=5.0):
        self.calls.append(cmd)
        if cmd in self.raise_for:
            raise ATCommandError(f"{cmd} failed")
        return "OK"


class _FakePort:
    """A serial fake that answers every write with OK and records what it was asked."""

    def __init__(self, refuse=None):
        self.writes = []
        self.closed = False
        self._buf = b""
        self._refuse = refuse.encode() if refuse else None

    def write(self, data):
        self.writes.append(data)
        refused = self._refuse is not None and self._refuse in data
        self._buf += b"\r\nERROR\r\n" if refused else b"\r\nOK\r\n"

    async def drain(self):
        pass

    async def read(self, n):
        while not self._buf:
            await asyncio.sleep(0.001)
        out, self._buf = self._buf, b""
        return out

    def close(self):
        self.closed = True

    async def wait_closed(self):
        pass

    @property
    def commands(self):
        return [w.decode().strip() for w in self.writes]


def _opener(monkeypatch, port):
    async def fake_open(url, baudrate):
        return port, port

    monkeypatch.setattr(at.serial_asyncio, "open_serial_connection", fake_open)


def _serial(rec=None):
    s = ATSerial("/dev/null")
    if rec is not None:
        s.command = rec
    return s


# --- 4.1 / 9.4 — the one-line omission in `soft_recover` -------------------------------

def test_soft_recover_re_issues_the_caller_id_subscription():
    """The omission this guard exists for, and the reason it will exist again.

    `soft_recover`'s own docstring argues that a URC subscription must not be assumed to
    survive a `CFUN` cycle, because losing it is silent and total. Caller ID is the same
    class of loss with a worse symptom: after an ordinary recovery IMS still reads `1,1`,
    so the rung is still offered, and `RING` simply arrives anonymous.
    """
    rec = _Rec()
    asyncio.run(_serial(rec).soft_recover())
    assert at.CLIP_SUBSCRIBE in rec.calls, (
        "a recovery that re-subscribes to +CDS and +CMTI and not to caller ID leaves the "
        "rung offered and every call anonymous"
    )
    assert rec.calls.index(CNMI_SUBSCRIBE) < rec.calls.index(at.CLIP_SUBSCRIBE), (
        "caller ID goes after the sequence that may not fail, as it does at init"
    )


def test_a_refused_caller_id_does_not_fail_the_recovery():
    """Caller ID is not worth a port at init, and it is not worth a recovery either.

    The positive control for the guard below: recovery completes, and the subscription
    was still attempted.
    """
    rec = _Rec(raise_for={at.CLIP_SUBSCRIBE})
    asyncio.run(_serial(rec).soft_recover())   # must not raise
    assert at.CLIP_SUBSCRIBE in rec.calls


# --- 4.2 / 4.3 / 9.3 — the record, and what it is made of ------------------------------

def test_the_record_holds_after_a_link_that_accepted_the_subscription(monkeypatch):
    """The positive control. Without it the negative guard below has executed nothing."""
    port = _FakePort()
    _opener(monkeypatch, port)
    s = ATSerial("/dev/ttyUSB2")
    s._usable = False

    assert asyncio.run(s.reconnect()) is True
    assert s.caller_id_subscribed is True


def test_the_record_does_not_hold_when_the_subscription_was_refused(monkeypatch):
    """`AT+CLIP=1` is allowed to fail and the port stays usable — that is settled. What
    this asserts is that the warning becomes a *fact*: the rung's precondition is not
    held, so the rung is not offered, rather than offered and silently anonymous."""
    port = _FakePort(refuse=at.CLIP_SUBSCRIBE)
    _opener(monkeypatch, port)
    s = ATSerial("/dev/ttyUSB2")
    s._usable = False

    assert asyncio.run(s.reconnect()) is True, "an optional extra must not fail the port"
    assert s.usable is True
    assert s.caller_id_subscribed is False


def test_the_record_is_not_read_back_from_the_modem(monkeypatch):
    """The whole reason the record exists. `AT+CLIP?` timed out on the live modem; a
    precondition that queries the device is one that can never be answered here."""
    port = _FakePort()
    _opener(monkeypatch, port)
    s = ATSerial("/dev/ttyUSB2")
    s._usable = False
    asyncio.run(s.reconnect())

    before = list(port.commands)
    assert s.caller_id_subscribed is True
    assert port.commands == before, "reading the record must not talk to the modem"
    assert not any("CLIP?" in c or "CLIP=?" in c for c in port.commands)


def test_a_lost_link_voids_the_record():
    """The record is per link generation. A link that is gone proves nothing about a
    subscription issued on the one before it."""
    s = ATSerial("/dev/null")
    s._clip_subscribed = True
    s._writer = object()
    assert s.caller_id_subscribed is True

    asyncio.run(s.close())
    assert s.caller_id_subscribed is False


def test_a_recovery_that_loses_caller_id_loses_the_record_with_it():
    """The pair to the first guard: re-issuing is half of it, believing the result is the
    other half. A `CFUN` cycle after which `AT+CLIP=1` is refused must leave the gateway
    knowing it does not hold the subscription."""
    s = _serial(_Rec(raise_for={at.CLIP_SUBSCRIBE}))
    s._clip_subscribed = True
    s._writer = object()
    asyncio.run(s.soft_recover())
    assert s.caller_id_subscribed is False


def test_a_recovery_that_keeps_caller_id_restores_the_record():
    """And its positive control: a recovery on a modem that accepts the subscription
    leaves the rung's precondition held."""
    s = _serial(_Rec())
    s._clip_subscribed = False
    s._writer = object()
    asyncio.run(s.soft_recover())
    assert s.caller_id_subscribed is True
