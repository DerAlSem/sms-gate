import asyncio
import logging
import serial_asyncio

logger = logging.getLogger(__name__)

CTRL_Z = b'\x1a'
PROMPT = b'> '


class ATCommandError(Exception):
    pass


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
        assert self._reader
        buf = b''
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise ATCommandError(f"Timeout waiting for {expected!r}, got: {buf!r}")
            try:
                chunk = await asyncio.wait_for(self._reader.read(256), timeout=remaining)
                buf += chunk
                if expected in buf:
                    return buf.decode(errors='replace')
            except asyncio.TimeoutError:
                raise ATCommandError(f"Timeout waiting for {expected!r}, got: {buf!r}")

    async def command(self, cmd: str, timeout: float = 5.0) -> str:
        """Send AT command, return full response."""
        async with self._lock:
            await self._send(f"{cmd}\r".encode())
            response = await self._read_until(b'OK', timeout)
            if 'ERROR' in response:
                raise ATCommandError(f"Command {cmd!r} failed: {response.strip()}")
            return response

    async def send_sms(self, phone: str, text: str, timeout: float = 30.0) -> int:
        """Send SMS, return modem_ref on success."""
        from app.modem.parser import parse_cmgs_ref

        async with self._lock:
            await self._send(f'AT+CMGS="{phone}"\r'.encode())
            await self._read_until(b'> ', timeout=5.0)
            await self._send(text.encode() + CTRL_Z)
            response = await self._read_until(b'OK', timeout=timeout)

        if 'ERROR' in response:
            raise ATCommandError(f"SMS send failed: {response.strip()}")

        ref = parse_cmgs_ref(response)
        if ref is None:
            raise ATCommandError(f"Could not parse +CMGS ref from: {response!r}")
        return ref

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
        CMGF is restored to text mode before returning — sending stays text."""
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
        """Run modem initialization sequence."""
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
