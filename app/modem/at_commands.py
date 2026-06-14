import asyncio
import logging
import serial_asyncio

from app.modem.parser import describe_at_error

logger = logging.getLogger(__name__)

CTRL_Z = b'\x1a'
PROMPT = b'> '


class ATCommandError(Exception):
    pass


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

    async def _read_until(self, expected: bytes, timeout: float) -> str:
        """Read until `expected` is seen. Returns early (without raising) when the
        modem emits a final error result code so callers can surface a clean
        message instead of blocking until `timeout` and dumping raw bytes."""
        assert self._reader
        buf = b''
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise ATCommandError(_clean_error(buf, expected))
            try:
                chunk = await asyncio.wait_for(self._reader.read(256), timeout=remaining)
                buf += chunk
                if expected in buf or b'ERROR' in buf:
                    return buf.decode(errors='replace')
            except asyncio.TimeoutError:
                raise ATCommandError(_clean_error(buf, expected))

    async def command(self, cmd: str, timeout: float = 5.0) -> str:
        """Send AT command, return full response."""
        async with self._lock:
            await self._send(f"{cmd}\r".encode())
            response = await self._read_until(b'OK', timeout)
            if 'ERROR' in response:
                raise ATCommandError(f"{cmd}: {describe_at_error(response)}")
            return response

    async def send_sms_pdu(self, parts, on_part_sent, timeout: float = 30.0):
        """Send one or more SMS-SUBMIT PDUs in PDU mode. Calls
        `await on_part_sent(seq, ref)` right after each part's +CMGS so the
        caller persists the part before the next is sent. Returns the list of
        modem refs. Raises ATCommandError on the first failing part (remaining
        parts are not sent)."""
        from app.modem.pdu_encode import tpdu_length
        from app.modem.parser import parse_cmgs_ref

        refs = []
        async with self._lock:
            await self._set_cmgf_unlocked(0)
            try:
                for seq, pdu in enumerate(parts, start=1):
                    await self._send(f"AT+CMGS={tpdu_length(pdu)}\r".encode())
                    prompt = await self._read_until(b'> ', timeout=5.0)
                    if 'ERROR' in prompt:
                        raise ATCommandError(describe_at_error(prompt))
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
            finally:
                await self._set_cmgf_unlocked(1)
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
