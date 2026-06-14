import asyncio

from app.modem.at_commands import ATSerial, ATCommandError


class _FakeSerial:
    """Scripts modem replies for a sequence of writes. Each write triggers the
    next reply from `replies`."""
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
        if self._buf:
            out, self._buf = self._buf, b""
            return out
        await asyncio.sleep(0)
        return b""


def _make(replies):
    s = ATSerial("/dev/null")
    s._reader = _FakeSerial(replies)
    s._writer = s._reader
    return s


def test_send_two_parts_returns_refs_and_calls_callback_per_part():
    async def run():
        s = _make([
            b"\r\nOK\r\n",                       # AT+CMGF=0
            b"\r\n> ",                           # part 1 prompt
            b"\r\n+CMGS: 10\r\n\r\nOK\r\n",      # part 1 result
            b"\r\n> ",                           # part 2 prompt
            b"\r\n+CMGS: 11\r\n\r\nOK\r\n",      # part 2 result
            b"\r\nOK\r\n",                       # AT+CMGF=1 restore
        ])
        seen = []
        async def on_part(seq, ref):
            seen.append((seq, ref))
        refs = await s.send_sms_pdu(["00110000", "00110001"], on_part)
        return refs, seen
    refs, seen = asyncio.run(run())
    assert refs == [10, 11]
    assert seen == [(1, 10), (2, 11)]


def test_send_raises_clean_error_on_cms_and_stops():
    async def run():
        s = _make([
            b"\r\nOK\r\n",                       # AT+CMGF=0
            b"\r\n> ",                           # part 1 prompt
            b"\r\n+CMS ERROR: 305\r\n",          # part 1 fails
            b"\r\nOK\r\n",                       # AT+CMGF=1 restore
        ])
        seen = []
        async def on_part(seq, ref):
            seen.append((seq, ref))
        try:
            await s.send_sms_pdu(["00110000", "00110001"], on_part)
            return "no error", seen
        except ATCommandError as e:
            return str(e), seen
    msg, seen = asyncio.run(run())
    assert "305" in msg and "invalid text mode parameter" in msg
    assert seen == []
    return msg
