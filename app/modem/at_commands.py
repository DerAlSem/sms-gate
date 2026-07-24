import asyncio
import logging
import serial_asyncio

from app.modem.parser import describe_at_error
from app.modem.diag import decode_reg

logger = logging.getLogger(__name__)

CTRL_Z = b'\x1a'
ESC = b'\x1b'
PROMPT = b'> '

# After a failed read the modem may still be emitting its (late) reply. Discard
# bytes until the port has been quiet for `_DRAIN_QUIET`, giving up after
# `_DRAIN_BUDGET` so a chatty modem cannot hold the serial lock open.
_DRAIN_QUIET = 0.3
_DRAIN_BUDGET = 2.0


class ATCommandError(Exception):
    """A failed AT exchange.

    `pdu_submitted` says whether message bytes had already been written to the modem
    when this failed. It is the difference between a failure that can be retried and
    one that must not be: once the PDU and its Ctrl-Z are out, the SMSC may have
    accepted the message even though we never saw the confirmation, and sending it
    again would put a second copy on someone's handset.
    """

    def __init__(self, message: str, *, pdu_submitted: bool = False) -> None:
        super().__init__(message)
        self.pdu_submitted = pdu_submitted


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

    async def connect(self) -> None:
        self._reader, self._writer = await serial_asyncio.open_serial_connection(
            url=self._port, baudrate=self._baudrate
        )
        logger.info("Opened serial port %s", self._port)

    async def close(self) -> None:
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()
            logger.info("Closed serial port %s", self._port)

    async def _send(self, data: bytes) -> None:
        assert self._writer
        self._writer.write(data)
        await self._writer.drain()

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
            if not chunk:
                break
            discarded += chunk
        if discarded:
            logger.warning(
                "Discarded %d stale byte(s) after a failed read: %r",
                len(discarded), discarded[:200],
            )
        return discarded

    async def _failed(self, buf: bytes, expected: bytes) -> ATCommandError:
        """Build the error for an unsuccessful read and leave the port usable."""
        error = ATCommandError(_clean_error(buf, expected))
        await self._drain()
        return error

    async def _read_until(self, expected: bytes, timeout: float) -> str:
        """Read until `expected` is seen. Returns early (without raising) when the
        modem emits a final error result code so callers can surface a clean
        message instead of blocking until `timeout` and dumping raw bytes.

        On failure the stream is drained before raising, so one timeout does not
        desync every command that follows."""
        assert self._reader
        buf = b''
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise await self._failed(buf, expected)
            try:
                chunk = await asyncio.wait_for(self._reader.read(256), timeout=remaining)
                buf += chunk
                if expected in buf or b'ERROR' in buf:
                    return buf.decode(errors='replace')
            except asyncio.TimeoutError:
                raise await self._failed(buf, expected) from None

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
        that is already on its way to the caller."""
        try:
            await self._set_cmgf_unlocked(1)
        except ATCommandError as e:
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
                if isinstance(exc, ATCommandError) and submitted:
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

    async def registration_ok(self) -> bool:
        """True if the modem is EPS-registered (CEREG stat 1=home or 5=roaming)."""
        try:
            resp = await self.command("AT+CEREG?", timeout=4.0)
        except ATCommandError:
            return False
        return decode_reg(resp).get("stat") in (1, 5)

    async def soft_recover(self) -> None:
        """RF off/on + auto operator reselect — re-attaches without a modem reboot."""
        await self.command("AT+CFUN=4", timeout=5.0)
        await self.command("AT+CFUN=1", timeout=10.0)
        await self.command("AT+COPS=0", timeout=15.0)

    async def hard_reset(self) -> None:
        """Full modem reset (CFUN=1,1). The port drops as the modem reboots, so the
        command may not return OK — swallow that."""
        try:
            await self.command("AT+CFUN=1,1", timeout=5.0)
        except ATCommandError:
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
            'AT+CNMI=2,1,2,1,0',
            'AT+CSMP=49,167,0,0',
        ]
        for cmd in commands:
            await self.command(cmd)
            logger.info("AT init: %s OK", cmd)
