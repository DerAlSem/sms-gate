import asyncio
import logging
import serial_asyncio

from app.modem.parser import describe_at_error
from app.modem.diag import decode_reg

logger = logging.getLogger(__name__)

# The URC subscription that makes the modem report delivery reports (+CDS) and inbound
# messages (+CMTI). Named because it has to survive every path that resets the modem.
CNMI_SUBSCRIBE = 'AT+CNMI=2,1,2,1,0'

CTRL_Z = b'\x1a'
ESC = b'\x1b'
PROMPT = b'> '

# After a failed read the modem may still be emitting its (late) reply. Discard
# bytes until the port has been quiet for `_DRAIN_QUIET`, giving up after
# `_DRAIN_BUDGET` so a chatty modem cannot hold the serial lock open.
_DRAIN_QUIET = 0.3
_DRAIN_BUDGET = 2.0

# How long startup waits for a device that has not come back yet, and how often it looks.
# The bound is chosen against the unit's restart policy, not in isolation: with
# `RestartSec=30` a failed start costs 90s, so five of them span 450s and cannot exhaust
# `StartLimitBurst=5` inside its 300s window. A fast crash — a bad `.env`, an import
# error — still trips that limit within seconds, which is what it is for.
_DEVICE_WAIT = 60.0
_DEVICE_WAIT_POLL = 2.0


class ModemFailure(Exception):
    """Anything that stopped an exchange with the modem.

    Exists so a caller with no stake in *why* can handle both kinds in one place, while
    the callers whose behaviour differs name them apart. Most of the existing handlers
    are the former; only three are the latter.

    `pdu_submitted` says whether message bytes had already been written to the modem
    when this failed. It is the difference between a failure that can be retried and
    one that must not be: once the PDU and its Ctrl-Z are out, the SMSC may have
    accepted the message even though we never saw the confirmation, and sending it
    again would put a second copy on someone's handset. It lives on the base class
    because the fact is about the message, not about which way the exchange broke.
    """

    def __init__(self, message: str, *, pdu_submitted: bool = False) -> None:
        super().__init__(message)
        self.pdu_submitted = pdu_submitted


class ATCommandError(ModemFailure):
    """The modem answered badly, or did not answer. The link itself is usable."""


class ModemTransportError(ModemFailure):
    """The link to the modem is gone — the port cannot be read or written at all.

    Deliberately a *sibling* of `ATCommandError` rather than a subclass. A subclass
    would be absorbed silently by every existing `except ATCommandError`, and the worst
    of those is `registration_state()`: it turns a caught AT failure into "could not
    tell", which the send path is required to read as permission to transmit, on the
    deliberate reasoning that not knowing is not a refusal. A lost link folded in there
    makes the gateway write messages into a port that no longer exists.

    The two also have disjoint cures. Every remedy for a misbehaving modem is an AT
    command, and none of them can reach a modem whose port is gone.
    """


def _clean_error(buf: bytes, expected: bytes) -> str:
    """Human-readable error for a read that ended without `expected`."""
    text = buf.decode(errors='replace')
    if 'ERROR' in text:
        return describe_at_error(text)
    if not buf.strip():
        return "no response from modem (timeout)"
    return f"timeout waiting for {expected.decode(errors='replace')!r}, got: {text.strip()!r}"


class ATSerial:
    def __init__(self, port: str, baudrate: int = 115200) -> None:
        self._port = port
        self._baudrate = baudrate
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        # Whether the link is believed open. Set by `connect`, cleared the moment the
        # port is found gone, so a link already known to be lost fails fast instead of
        # being rediscovered one command timeout at a time. Tests that install a
        # transport directly start from an open link.
        self._usable = True
        # Set when the link is found gone, so whoever is responsible for acting can be
        # woken at once. The send path meets the loss first and at the moment it matters;
        # leaving it to be rediscovered by the next periodic poll spends a minute knowing
        # the answer. Consumers clear it after taking it.
        self.link_lost = asyncio.Event()

    @property
    def usable(self) -> bool:
        return self._usable

    async def connect(self, wait_for_device: float = 0.0) -> None:
        """Open the port, optionally waiting for the device to come back first.

        A device absent at startup is the same fault as one lost in flight, seen at a
        different moment — and the moment is not ours to choose. A restart provoked by a
        lost link lands while the modem is still re-enumerating, because it takes longer
        to return than a supervisor takes to restart a service. Treating that as fatal
        turns the remedy into the failure: the gateway restarts, cannot open the port,
        exits, and repeats until its supervisor gives up altogether.

        Two ways to be "not back yet", and both are tolerated. The node may not exist; and
        just after it is recreated it may exist while this process still may not open it,
        because udev has not yet applied the ownership the service runs under.
        """
        deadline = asyncio.get_event_loop().time() + wait_for_device
        while True:
            try:
                self._reader, self._writer = await serial_asyncio.open_serial_connection(
                    url=self._port, baudrate=self._baudrate
                )
                break
            except OSError as e:
                if asyncio.get_event_loop().time() >= deadline:
                    self._usable = False
                    raise ModemTransportError(
                        f"{self._port} did not appear within {wait_for_device:.0f}s: {e}"
                    ) from e
                logger.warning("Waiting for %s: %s", self._port, e)
                await asyncio.sleep(_DEVICE_WAIT_POLL)
        self._usable = True
        self.link_lost.clear()
        logger.info("Opened serial port %s", self._port)

    async def close(self) -> None:
        self._usable = False
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()
            logger.info("Closed serial port %s", self._port)

    def _lose_link(self, reason: str) -> ModemTransportError:
        """Mark the link unusable and build the failure describing it.

        Marking matters as much as raising. Without it each consumer rediscovers the
        same dead port by waiting out its own timeout, and — worse — a write to a closed
        transport does not raise at all, so a caller can believe a command went out when
        nothing did.
        """
        if self._usable:
            logger.error("Lost the link to %s: %s", self._port, reason)
        self._usable = False
        self.link_lost.set()
        return ModemTransportError(f"link to {self._port} lost: {reason}")

    def _check_usable(self) -> None:
        if not self._usable:
            raise ModemTransportError(f"link to {self._port} is not open")

    async def _send(self, data: bytes) -> None:
        self._check_usable()
        assert self._writer
        try:
            self._writer.write(data)
            await self._writer.drain()
        except (OSError, RuntimeError) as e:
            # serial.SerialException derives from OSError, and this is where it
            # surfaces: `write()` succeeds against a transport that is already dead and
            # `drain()` re-raises the error the reader stored.
            raise self._lose_link(f"{type(e).__name__}: {e}") from e

    async def _drain(self) -> bytes:
        """Discard whatever the modem is still emitting, until the port goes quiet.

        A read that gave up leaves its reply in flight; without this the *next*
        command reads the previous command's answer and every subsequent one is a
        reply out of phase."""
        assert self._reader
        discarded = b''
        deadline = asyncio.get_event_loop().time() + _DRAIN_BUDGET
        while True:
            remaining = min(_DRAIN_QUIET, deadline - asyncio.get_event_loop().time())
            if remaining <= 0:
                break
            try:
                chunk = await asyncio.wait_for(self._reader.read(256), timeout=remaining)
            except asyncio.TimeoutError:
                break
            except OSError as e:
                self._lose_link(f"{type(e).__name__}: {e}")
                break
            if not chunk:
                # End of stream, not silence: a live port with nothing to say blocks
                # until the timeout above. This is the link closing under us.
                self._lose_link("end of stream")
                break
            discarded += chunk
        if discarded:
            logger.warning(
                "Discarded %d stale byte(s) after a failed read: %r",
                len(discarded), discarded[:200],
            )
        return discarded

    async def _failed(self, buf: bytes, expected: bytes) -> ModemFailure:
        """Build the error for an unsuccessful read and leave the port usable."""
        error = ATCommandError(_clean_error(buf, expected))
        await self._drain()
        if not self._usable:
            # The drain found the port gone. The caller is owed the link failure, not
            # the timeout that was only its symptom — they have different cures.
            return ModemTransportError(f"link to {self._port} lost while draining")
        return error

    async def _read_until(self, expected: bytes, timeout: float) -> str:
        """Read until `expected` is seen. Returns early (without raising) when the
        modem emits a final error result code so callers can surface a clean
        message instead of blocking until `timeout` and dumping raw bytes.

        On failure the stream is drained before raising, so one timeout does not
        desync every command that follows.

        A read that ends the stream, or errors outright, is the link going away rather
        than the modem being slow, and is raised as such. Without the end-of-stream case
        a closed port produces no exception at all: `read` returns nothing, immediately
        and for ever, so this loop spins to its deadline and then reports an ordinary AT
        timeout — routing a lost link straight back into the handling that cannot fix
        it."""
        self._check_usable()
        assert self._reader
        buf = b''
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise await self._failed(buf, expected)
            try:
                chunk = await asyncio.wait_for(self._reader.read(256), timeout=remaining)
            except asyncio.TimeoutError:
                raise await self._failed(buf, expected) from None
            except OSError as e:
                raise self._lose_link(f"{type(e).__name__}: {e}") from e
            if not chunk:
                raise self._lose_link("end of stream")
            buf += chunk
            if expected in buf or b'ERROR' in buf:
                return buf.decode(errors='replace')

    async def command(self, cmd: str, timeout: float = 5.0) -> str:
        """Send AT command, return full response."""
        async with self._lock:
            await self._send(f"{cmd}\r".encode())
            response = await self._read_until(b'OK', timeout)
            if 'ERROR' in response:
                raise ATCommandError(f"{cmd}: {describe_at_error(response)}")
            return response

    async def _abort_prompt_unlocked(self) -> None:
        """Cancel a pending `> ` prompt with ESC.

        A modem left at the prompt treats everything we write next as message
        text, so the mode restore below — and any later command — would be
        silently eaten rather than executed. Best-effort: the send has already
        failed, and its error is the one worth reporting."""
        try:
            await self._send(ESC)
            await self._drain()
        except Exception:
            logger.warning("Could not abort the CMGS prompt", exc_info=True)

    async def _restore_cmgf_unlocked(self) -> None:
        """Return the modem to the text-mode default without masking a failure
        that is already on its way to the caller.

        Catches the shared base rather than only an AT failure. This runs in a `finally`,
        so an exception raised here *replaces* the one already propagating — and on a lost
        link this restore is exactly what fails. The caller would lose both the reason the
        send failed and, worse, the record of whether the message had already been
        written: a message reported as untransmitted when the SMSC may hold it is a
        duplicate SMS on someone's handset.
        """
        try:
            await self._set_cmgf_unlocked(1)
        except ModemFailure as e:
            logger.warning("Could not restore CMGF=1: %s", e)

    async def send_sms_pdu(self, parts, on_part_sent, timeout: float = 30.0,
                           prompt_timeout: float = 5.0):
        """Send one or more SMS-SUBMIT PDUs in PDU mode. Calls
        `await on_part_sent(seq, ref)` right after each part's +CMGS so the
        caller persists the part before the next is sent. Returns the list of
        modem refs. Raises ATCommandError on the first failing part (remaining
        parts are not sent); the port is left clean for the next send."""
        from app.modem.pdu_encode import tpdu_length
        from app.modem.parser import parse_cmgs_ref

        refs = []
        submitted = False
        async with self._lock:
            await self._set_cmgf_unlocked(0)
            try:
                for seq, pdu in enumerate(parts, start=1):
                    await self._send(f"AT+CMGS={tpdu_length(pdu)}\r".encode())
                    prompt = await self._read_until(b'> ', timeout=prompt_timeout)
                    if 'ERROR' in prompt:
                        raise ATCommandError(describe_at_error(prompt))
                    # Past this point the SMSC may hold the message whatever we see
                    # next, so every failure from here is un-retryable.
                    submitted = True
                    await self._send(pdu.encode() + CTRL_Z)
                    response = await self._read_until(b'OK', timeout=timeout)
                    if 'ERROR' in response:
                        raise ATCommandError(describe_at_error(response))
                    ref = parse_cmgs_ref(response)
                    if ref is None:
                        raise ATCommandError(
                            f"Could not parse +CMGS ref from: {response!r}"
                        )
                    refs.append(ref)
                    await on_part_sent(seq, ref)
                    submitted = False       # this part is accounted for
            except BaseException as exc:
                # `ModemFailure`, not `ATCommandError`: a lost link is a sibling class, so
                # an `isinstance` against the AT failure alone would let a link that died
                # after the PDU and Ctrl-Z were written report that nothing was written.
                # The hold-instead-of-fail rule would then retry it, and the SMSC may
                # already hold the message.
                if isinstance(exc, ModemFailure) and submitted:
                    exc.pdu_submitted = True
                await self._abort_prompt_unlocked()
                raise
            finally:
                await self._restore_cmgf_unlocked()
        return refs

    async def _cmgr_unlocked(self, index: int, timeout: float) -> str:
        await self._send(f'AT+CMGR={index}\r'.encode())
        response = await self._read_until(b'OK', timeout)
        if 'ERROR' in response:
            raise ATCommandError(f"CMGR {index} failed: {response.strip()}")
        return response

    async def _cmgl_unlocked(self, timeout: float) -> str:
        # In PDU mode stat is numeric: 4 = ALL
        await self._send(b'AT+CMGL=4\r')
        response = await self._read_until(b'OK', timeout)
        if 'ERROR' in response:
            raise ATCommandError(f"CMGL failed: {response.strip()}")
        return response

    async def _set_cmgf_unlocked(self, mode: int, timeout: float = 2.0) -> None:
        await self._send(f'AT+CMGF={mode}\r'.encode())
        response = await self._read_until(b'OK', timeout)
        if 'ERROR' in response:
            raise ATCommandError(f"CMGF={mode} failed: {response.strip()}")

    async def read_sms(self, index: int, timeout: float = 5.0) -> str:
        """Read SMS at index in PDU mode (UDH concat metadata survives).
        CMGF is restored to the text-mode default before returning; every
        send/read path toggles CMGF around its own operation."""
        async with self._lock:
            await self._set_cmgf_unlocked(0)
            try:
                return await self._cmgr_unlocked(index, timeout)
            finally:
                await self._set_cmgf_unlocked(1)

    async def delete_sms(self, index: int, timeout: float = 5.0) -> None:
        await self.command(f'AT+CMGD={index}', timeout=timeout)

    async def list_all_sms(self, timeout: float = 10.0) -> str:
        """List all stored SMS in PDU mode."""
        async with self._lock:
            await self._set_cmgf_unlocked(0)
            try:
                return await self._cmgl_unlocked(timeout)
            finally:
                await self._set_cmgf_unlocked(1)

    async def check_registration(self) -> str:
        """Query network registration status (AT+CREG?)."""
        return await self.command('AT+CREG?')

    async def registration_state(self) -> bool | None:
        """True registered, False definitively not, None when we could not tell.

        The third case is the point. `registration_ok` below folds "the query failed"
        into False, which is right for the watchdog — a modem that cannot answer is
        unhealthy. It is wrong for deciding whether to send: not knowing is not a
        refusal, and a gateway that stops sending whenever it cannot ask a question is
        worse than one that tries and reports a real failure.
        """
        try:
            resp = await self.command("AT+CEREG?", timeout=4.0)
        except ATCommandError:
            return None
        stat = decode_reg(resp).get("stat")
        if stat is None:
            return None
        return stat in (1, 5)

    async def registration_ok(self) -> bool:
        """True if the modem is EPS-registered (CEREG stat 1=home or 5=roaming).

        An unanswerable modem counts as not registered: the watchdog acts on doubt.
        """
        return await self.registration_state() is True

    async def soft_recover(self) -> None:
        """RF off/on + auto operator reselect — re-attaches without a modem reboot.

        `CNMI` is re-applied afterwards on purpose. Whether a firmware keeps the URC
        subscription across a `CFUN` cycle is not something we can assume, and losing it
        is silent and total: no `+CDS` means every message expires, no `+CMTI` means
        every inbound SMS is missed, and no health check would notice. Re-issuing it is
        idempotent and costs one command.
        """
        await self.command("AT+CFUN=4", timeout=5.0)
        await self.command("AT+CFUN=1", timeout=10.0)
        await self.command("AT+COPS=0", timeout=15.0)
        await self.command(CNMI_SUBSCRIBE, timeout=5.0)

    async def hard_reset(self) -> None:
        """Full modem reset (CFUN=1,1). The port drops as the modem reboots, so the
        command may not return OK — swallow that."""
        try:
            await self.command("AT+CFUN=1,1", timeout=5.0)
        except ModemFailure:
            # Widened from the AT failure alone: the port drops as the modem reboots, and
            # on a link that was already gone this raises a transport failure instead —
            # which would otherwise escape and abort the escalation that ordered the reset.
            pass

    async def init(self) -> None:
        """Run modem initialization sequence.

        Sending now goes through PDU mode (send_sms_pdu toggles CMGF=0 per send
        and bakes SRR/VP into the PDU itself), so CMGF=1 / CSCS / CSMP here only
        set a sane text-mode default for any manual AT use — they no longer
        affect outbound SMS. CNMI is what matters: it enables +CDS/+CMTI."""
        commands = [
            'AT',
            'ATE0',
            'AT+CMGF=1',
            'AT+CSCS="GSM"',
            CNMI_SUBSCRIBE,
            'AT+CSMP=49,167,0,0',
        ]
        for cmd in commands:
            await self.command(cmd)
            logger.info("AT init: %s OK", cmd)
