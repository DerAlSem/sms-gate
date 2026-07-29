"""The link to the modem going away, as distinct from the modem answering badly.

On 2026-07-29 the USB modem re-enumerated at 01:28:27. Every device node was recreated
and the gateway's descriptors went stale, but `serial.SerialException` is not
`ATCommandError`, so it escaped `registration_state()` and `_watchdog_step()` before the
recovery ladder was ever consulted, and `watchdog_loop`'s `except Exception: continue`
swallowed it 316 times over five hours while the service reported itself healthy.

These tests pin the distinction the codebase lacked: a modem that answers badly is one
thing, a port that is no longer there is another, and only the first has an AT remedy.
"""

import asyncio
import time

import pytest
import serial

from app.modem.at_commands import (
    ATSerial,
    ATCommandError,
    ModemTransportError,
    ModemFailure,
)

_GONE = "device reports readiness to read but returned no data (device disconnected or multiple access on port?)"


class _DeadSerial:
    """A port whose device has gone away.

    Faithful to how pyserial-asyncio actually fails, which is the reason the incident
    was mis-handled in the first place: `write()` does not raise — it succeeds against a
    transport that is already dead — and the exception surfaces from `drain()`, where the
    stored read error is re-raised. A fake that raised from `write()` would let a broken
    implementation pass.

    `mode="eof"` models the other presentation: a cleanly closed stream raises nothing at
    all and simply returns no bytes, for ever.
    """

    def __init__(self, mode="raise"):
        self.mode = mode
        self.writes = []
        self.reads = 0

    def write(self, data):
        self.writes.append(data)

    async def drain(self):
        if self.mode == "raise":
            raise serial.SerialException(_GONE)

    async def read(self, n):
        self.reads += 1
        if self.mode == "eof":
            return b""
        raise serial.SerialException(_GONE)

    def close(self):
        pass

    async def wait_closed(self):
        pass


class _TalkingSerial:
    """A live port that answers each write with a canned reply."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.writes = []
        self._buf = b""

    def write(self, data):
        self.writes.append(data)
        if self._replies:
            self._buf += self._replies.pop(0)

    async def drain(self):
        pass

    async def read(self, n):
        while not self._buf:
            await asyncio.sleep(0.005)
        out, self._buf = self._buf, b""
        return out


def _make(transport):
    s = ATSerial("/dev/null")
    s._reader = transport
    s._writer = transport
    return s


# --- the distinction itself ---------------------------------------------------


def test_a_vanished_port_raises_a_transport_failure_not_an_at_failure():
    async def run():
        s = _make(_DeadSerial())
        with pytest.raises(ModemTransportError):
            await s.command("AT+CEREG?", timeout=0.3)

    asyncio.run(run())


def test_a_modem_that_answers_badly_still_raises_an_at_failure():
    """The other side of the distinction: the link is fine, the modem said no."""

    async def run():
        s = _make(_TalkingSerial([b"\r\n+CMS ERROR: 500\r\n"]))
        with pytest.raises(ATCommandError) as exc:
            await s.command("AT+CMGS=1", timeout=0.5)
        assert not isinstance(exc.value, ModemTransportError)

    asyncio.run(run())


def test_transport_failure_is_a_sibling_of_at_failure_not_a_subclass():
    """A subclass would be absorbed by every existing `except ATCommandError`.

    The worst of those is `registration_state()`, which turns a caught AT failure into
    "could not tell" — and the send path is required to read "could not tell" as
    permission to transmit. A transport failure absorbed there makes the gateway write
    messages into a port that no longer exists, with no line of code looking wrong.
    """
    assert not issubclass(ModemTransportError, ATCommandError)
    assert not issubclass(ATCommandError, ModemTransportError)
    assert issubclass(ModemTransportError, ModemFailure)
    assert issubclass(ATCommandError, ModemFailure)


def test_a_handler_for_at_failures_does_not_absorb_a_lost_link():
    async def run():
        s = _make(_DeadSerial())
        with pytest.raises(ModemTransportError):
            try:
                await s.command("AT", timeout=0.3)
            except ATCommandError:  # the nine existing handlers look like this
                pytest.fail("a lost link was absorbed by an AT-failure handler")

    asyncio.run(run())


def test_a_cleanly_closed_stream_is_a_lost_link_not_a_command_timeout():
    """A closed stream returns no bytes rather than raising.

    Watching only for exceptions turns this into an ordinary `no response from modem
    (timeout)` — an *AT* failure — which routes the fault straight back into the handling
    this whole change exists to bypass.
    """

    async def run():
        s = _make(_DeadSerial(mode="eof"))
        with pytest.raises(ModemTransportError):
            await s.command("AT", timeout=0.3)

    asyncio.run(run())


def test_a_closed_stream_does_not_spin_until_the_deadline():
    """`_read_until` had no empty-chunk check, so EOF made it loop with nothing to
    wait on — burning the whole timeout instead of failing at once."""

    async def run():
        s = _make(_DeadSerial(mode="eof"))
        started = time.monotonic()
        with pytest.raises(ModemTransportError):
            await s.command("AT", timeout=5.0)
        return time.monotonic() - started

    elapsed = asyncio.run(run())
    assert elapsed < 1.0, f"spun for {elapsed:.1f}s instead of failing on the closed stream"


def test_a_command_after_a_lost_link_fails_at_once():
    """Otherwise every consumer rediscovers the same dead port through its own timeout."""

    async def run():
        transport = _DeadSerial()
        s = _make(transport)
        with pytest.raises(ModemTransportError):
            await s.command("AT", timeout=0.3)

        writes_before = len(transport.writes)
        started = time.monotonic()
        with pytest.raises(ModemTransportError):
            await s.command("AT+CSQ", timeout=5.0)
        return time.monotonic() - started, writes_before, len(transport.writes)

    elapsed, before, after = asyncio.run(run())
    assert elapsed < 0.5, f"took {elapsed:.1f}s to rediscover a link already known to be lost"
    assert after == before, "wrote to a port known to be gone"


def test_a_write_against_a_known_lost_link_does_not_look_successful():
    """`write()` on a closed transport does not raise, so without the usable flag a
    caller believes a command went out when nothing did."""

    async def run():
        transport = _DeadSerial()
        s = _make(transport)
        with pytest.raises(ModemTransportError):
            await s.command("AT", timeout=0.3)
        with pytest.raises(ModemTransportError):
            await s._send(b"AT\r")

    asyncio.run(run())


class _DiesAfterSerial:
    """A live port that goes away at the Nth write.

    Lets a test put the loss exactly where it matters: after the PDU and its Ctrl-Z
    have gone out, which is the one moment when retrying would put a second copy on
    someone's handset.
    """

    def __init__(self, replies, die_at_write):
        self._replies = list(replies)
        self._die_at = die_at_write
        self.writes = []
        self._buf = b""
        self.dead = False

    def write(self, data):
        self.writes.append(data)
        if len(self.writes) >= self._die_at:
            self.dead = True
            return
        if self._replies:
            self._buf += self._replies.pop(0)

    async def drain(self):
        if self.dead:
            raise serial.SerialException(_GONE)

    async def read(self, n):
        if self.dead:
            raise serial.SerialException(_GONE)
        while not self._buf:
            await asyncio.sleep(0.005)
        out, self._buf = self._buf, b""
        return out


def _dying_sender():
    # writes: 1 AT+CMGF=0, 2 AT+CMGS=<len>, 3 the PDU + Ctrl-Z <- the link dies here
    return _make(_DiesAfterSerial([b"\r\nOK\r\n", b"> "], die_at_write=3))


def test_a_link_lost_after_the_pdu_records_that_the_message_was_written():
    """The blocking defect: the flag is set by an `isinstance` check.

    Against `ATCommandError` alone a sibling transport class fails that check, so a link
    that died *after* the PDU and Ctrl-Z went out reports that nothing was written. The
    hold-instead-of-fail rule then retries the message while the SMSC may already hold
    it — a duplicate SMS, produced by the change written to prevent harm.

    Asserted here, at the transport, because this is where the flag is set; asserting it
    a layer up passes trivially against a hand-built exception.
    """

    async def run():
        s = _dying_sender()

        async def on_part(seq, ref):
            pytest.fail("no part should be reported sent")

        with pytest.raises(ModemFailure) as exc:
            await s.send_sms_pdu(["0011000A"], on_part, timeout=0.3, prompt_timeout=0.3)
        return exc.value

    error = asyncio.run(run())
    assert isinstance(error, ModemTransportError)
    assert error.pdu_submitted is True, (
        "a link lost after the write reported the message as never transmitted"
    )


def test_a_failing_mode_restore_does_not_replace_the_original_failure():
    """`_restore_cmgf_unlocked` runs in a `finally`, so anything it raises replaces the
    exception already on its way out — taking the written-bytes record with it."""

    async def run():
        s = _dying_sender()

        async def on_part(seq, ref):
            pass

        with pytest.raises(ModemFailure) as exc:
            await s.send_sms_pdu(["0011000A"], on_part, timeout=0.3, prompt_timeout=0.3)
        return exc.value

    error = asyncio.run(run())
    # The restore fails too, against the same dead link. If it had replaced the original,
    # the flag would be gone.
    assert error.pdu_submitted is True


# --- the device being absent when the service starts ---------------------------


class _AbsentThenPresent:
    """`open_serial_connection` as it behaves across a re-enumeration.

    Two ways to be "not back yet", and both must be tolerated: the node does not exist,
    and — briefly after it is recreated — it exists but this process may not open it,
    because udev has not yet applied the ownership the service runs under.
    """

    def __init__(self, failures):
        self.failures = list(failures)
        self.calls = 0

    async def __call__(self, url=None, baudrate=None):
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        transport = _TalkingSerial([b"\r\nOK\r\n"] * 20)
        return transport, transport


def test_a_device_absent_at_startup_is_waited_for(monkeypatch):
    """A restart provoked by a lost link lands while the device is still gone: a
    re-enumerating modem takes longer to come back than the supervisor takes to restart
    the service. Treating that as fatal turns the remedy into the failure."""
    import app.modem.at_commands as at

    opener = _AbsentThenPresent([
        FileNotFoundError("no such device"),
        PermissionError("udev has not applied the group yet"),
    ])
    monkeypatch.setattr(at.serial_asyncio, "open_serial_connection", opener)
    monkeypatch.setattr(at, "_DEVICE_WAIT_POLL", 0.01)

    async def run():
        s = ATSerial("/dev/ttyUSB2")
        await s.connect(wait_for_device=1.0)
        return s.usable

    assert asyncio.run(run()) is True
    assert opener.calls == 3, "the wait gave up on a device that was only briefly absent"


def test_a_device_that_never_appears_ends_startup_rather_than_hanging(monkeypatch):
    """Bounded: a gateway that hangs in startup for ever is not visibly broken, it is
    just gone — which is the failure mode this whole change exists to remove."""
    import app.modem.at_commands as at

    opener = _AbsentThenPresent([FileNotFoundError("no such device")] * 500)
    monkeypatch.setattr(at.serial_asyncio, "open_serial_connection", opener)
    monkeypatch.setattr(at, "_DEVICE_WAIT_POLL", 0.01)

    async def run():
        s = ATSerial("/dev/ttyUSB2")
        started = time.monotonic()
        with pytest.raises(ModemTransportError):
            await s.connect(wait_for_device=0.2)
        return time.monotonic() - started

    elapsed = asyncio.run(run())
    assert elapsed < 2.0, f"startup hung for {elapsed:.1f}s instead of ending at its bound"
