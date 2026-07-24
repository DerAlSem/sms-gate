"""Transport recovery after a failed AT read.

A read that times out leaves the serial stream in an unknown state: the modem may
still emit its (late) reply, and — worse — after `AT+CMGS=` it may be sitting at the
`> ` prompt, where every subsequent byte we write is swallowed as message text
instead of being executed. Both desync the stream for the *next* command, which is
how one timeout cascades into unrelated failures
(prod 2026-07-24: id 976 timed out, id 977 then read `OK` where `> ` was due).
"""

import asyncio

import pytest

from app.modem.at_commands import ATSerial, ATCommandError


class _DelayedSerial:
    """Serial fake whose replies can arrive *after* the reader gave up.

    `replies[i]` answers the i-th write and lands `delays[i]` seconds later; a
    `None` reply means the modem stays silent for that write. Unlike a
    write-triggered fake, `read` blocks until bytes exist, so `asyncio.wait_for`
    timeouts behave as they do against a real port.
    """

    def __init__(self, replies, delays=None):
        self._replies = list(replies)
        self._delays = list(delays or [])
        self.writes = []
        self._buf = b""
        self._tasks = []

    def write(self, data):
        self.writes.append(data)
        if not self._replies:
            return
        reply = self._replies.pop(0)
        delay = self._delays.pop(0) if self._delays else 0.0
        if reply is None:
            return
        if delay <= 0:
            self._buf += reply
            return

        async def _later():
            await asyncio.sleep(delay)
            self._buf += reply

        self._tasks.append(asyncio.get_event_loop().create_task(_later()))

    async def drain(self):
        pass

    async def read(self, n):
        while not self._buf:
            await asyncio.sleep(0.005)
        out, self._buf = self._buf, b""
        return out


def _make(replies, delays=None):
    s = ATSerial("/dev/null")
    s._reader = _DelayedSerial(replies, delays)
    s._writer = s._reader
    return s


def test_late_reply_is_discarded_so_next_command_reads_its_own_answer():
    """The cascade regression: a reply arriving after its read timed out must not
    be handed to the next command."""

    async def run():
        s = _make(
            replies=[
                b"\r\n+CSQ: 20,99\r\n\r\nOK\r\n",   # arrives too late for its own read
                b"\r\n+CEREG: 0,1\r\n\r\nOK\r\n",   # the next command's own reply
            ],
            delays=[0.15, 0.0],
        )
        with pytest.raises(ATCommandError):
            await s.command("AT+CSQ", timeout=0.05)
        # Give the late reply time to land, exactly as it would in production.
        await asyncio.sleep(0.2)
        return await s.command("AT+CEREG?", timeout=1.0)

    response = asyncio.run(run())
    assert "+CEREG" in response
    assert "CSQ" not in response


def test_failed_send_aborts_the_cmgs_prompt_with_esc():
    """After a prompt timeout the modem may be waiting for PDU text; ESC cancels
    it so the CMGF restore is executed rather than sent as message body."""

    async def run():
        s = _make(
            replies=[
                b"\r\nOK\r\n",   # AT+CMGF=0
                None,            # AT+CMGS= — modem never prompts
                None,            # ESC abort
                b"\r\nOK\r\n",   # AT+CMGF=1 restore
            ],
            delays=[0, 0, 0, 0],
        )

        async def on_part(seq, ref):
            raise AssertionError("no part should be reported")

        with pytest.raises(ATCommandError):
            await s.send_sms_pdu(["00110000"], on_part, prompt_timeout=0.05)
        return s._writer.writes

    writes = asyncio.run(run())
    assert b"\x1b" in writes, f"no ESC abort was written: {writes!r}"
    esc = writes.index(b"\x1b")
    restore = next(i for i, w in enumerate(writes) if b"CMGF=1" in w)
    assert esc < restore, "ESC must precede the CMGF restore, else it is eaten as text"


def test_cmgf_restore_failure_does_not_mask_the_real_send_error():
    """The original failure is what the operator and the app need to see; a
    best-effort mode restore must not overwrite it."""

    async def run():
        s = _make(
            replies=[
                b"\r\nOK\r\n",   # AT+CMGF=0
                None,            # AT+CMGS= — silence, the real failure
                None,            # ESC abort
                None,            # AT+CMGF=1 restore also fails
            ],
        )

        async def on_part(seq, ref):
            raise AssertionError("no part should be reported")

        try:
            await s.send_sms_pdu(["00110000"], on_part, prompt_timeout=0.05)
        except ATCommandError as e:
            return str(e)
        return "no error"

    message = asyncio.run(run())
    assert "no response from modem" in message
    assert "CMGF" not in message
