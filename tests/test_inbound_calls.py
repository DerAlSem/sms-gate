"""The reader learns that a call happened.

Until now `RING` and `+CLIP` fell to the `else` branch of `reader_loop` and were logged
as `Unhandled URC` — the comment there names an incoming call as exactly the case it was
left for. This is that case arriving.

Three things make this more than a parser. The modem reports **one** call many times —
fifteen `RING` / `+CLIP` pairs in sixteen seconds, measured on the production EP06-E on
18.09.2026 — so a handler that acts per line invents fifteen calls. The number arrives on
a *different line* from the event, so the two have to be joined without inventing a second
call when the join fails. And a call is not a message: writing it into `inbound_messages`
would corrupt the record that makes ordinary inbound traffic visible in the console.

The wire format is the captured one, not a guessed one:

    RING
    +CLIP: "+79261234888",145,,,,0

`145` is the type of address (international), and the trailing field is CLI validity —
`0` valid, `1` withheld by the caller, `2` unavailable to the network.
"""

import asyncio

import pytest

import app.modem.calls as calls_mod
import app.modem.manager as manager_mod
from app.db import queries
from app.db.connection import close_db, get_db, init_db
from app.db.migrate import run_migrations
from app.modem.calls import CallWatch
from app.modem.manager import ModemManager
from app.modem.parser import parse_clip
from app.settings_store import store

CALLER = "+79261234888"
CLIP = f'+CLIP: "{CALLER}",145,,,,0'
CLIP_WITHHELD = '+CLIP: "",128,,,,1'


class ScriptedPort:
    """Hands the loop a sequence of URC chunks, then goes quiet as a real port does.

    Quiet is a timeout, not a block: the loop treats that as "nothing to read" and comes
    back, which is what lets a test add a second call after the first has been handled. A
    port that blocked for ever would make the loop unreachable for the rest of the test.
    """

    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.in_service = True
        self.usable = True

    async def read_urc(self, timeout=1.0):
        if self._chunks:
            return self._chunks.pop(0)
        await asyncio.sleep(0.002)
        raise asyncio.TimeoutError


def _run(body):
    async def go():
        await init_db(":memory:")
        await run_migrations()
        await store.load()
        return await body()

    try:
        return asyncio.run(go())
    finally:
        asyncio.run(close_db())


def _manager(monkeypatch):
    m = ModemManager("/dev/null", "/dev/null")
    monkeypatch.setattr(manager_mod, "spawn_delivery_dispatch", lambda *a, **kw: None)
    monkeypatch.setattr(manager_mod, "notify", lambda *a, **kw: None)
    return m


async def _drive(m, chunks, *, settle=0.05):
    m._reader_link = ScriptedPort(chunks)
    task = asyncio.get_event_loop().create_task(m.reader_loop())
    await asyncio.sleep(settle)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def _calls() -> list[tuple]:
    db = await get_db()
    async with db.execute(
        "SELECT phone, raw_number, outcome FROM inbound_calls ORDER BY id"
    ) as cur:
        return [tuple(r) for r in await cur.fetchall()]


# --- the wire format -------------------------------------------------------------------

def test_the_captured_line_yields_the_callers_number():
    assert parse_clip(CLIP) == CALLER


def test_a_withheld_number_is_not_a_number():
    """`+CLIP` still arrives when the caller withheld their number; the field is empty and
    the validity says so. Reading that as a number would attribute a call to nobody."""
    assert parse_clip(CLIP_WITHHELD) is None


def test_a_number_the_network_marks_as_unavailable_is_not_used():
    """Validity 2: the network could not supply it. The field may still carry something;
    what it cannot carry is a claim about who called."""
    assert parse_clip('+CLIP: "+79261234888",145,,,,2') is None


def test_a_line_the_parser_cannot_read_is_not_half_read():
    assert parse_clip("+CLIP:") is None
    assert parse_clip("RING") is None


# --- one call, however many times the modem says it ------------------------------------

def test_a_call_is_recorded_once_with_the_callers_number(monkeypatch):
    async def body():
        m = _manager(monkeypatch)
        await _drive(m, [b"\r\nRING\r\n", (CLIP + "\r\n").encode()])
        return await _calls()

    rows = _run(body)
    assert rows == [(CALLER, CALLER, "unattributed")], rows


def test_fifteen_repetitions_of_one_call_are_one_call(monkeypatch):
    """The measurement this guard exists for: fifteen `RING` / `+CLIP` pairs in sixteen
    seconds, one call. A handler that acts per line reports fifteen."""
    async def body():
        m = _manager(monkeypatch)
        chunks = [b"\r\nRING\r\n", (CLIP + "\r\n").encode()] * 15
        await _drive(m, chunks)
        return await _calls()

    rows = _run(body)
    assert len(rows) == 1, f"one call became {len(rows)}"


def test_the_rule_is_the_gap_and_not_the_number():
    """The collapsing rule on its own, on a clock the test holds.

    Stated apart from the reader because it is a rule about time, and because the number
    is not part of it: the number arrives on a different line from the event that starts
    the call, and often does not arrive at all. Ringing is a cadence of about a second,
    so anything inside the gap is the call already ringing and anything past it is a new
    one.
    """
    watch = CallWatch(gap=10.0)
    first, is_new = watch.observe(now=1000.0)
    assert is_new is True
    # `RING` … `+CLIP` … and thirteen more pairs, all one call.
    for tick in range(1, 16):
        same, is_new = watch.observe(now=1000.0 + tick)
        assert is_new is False, f"repetition at +{tick}s was read as a new call"
        assert same is first
    # The ringing stopped, and later somebody calls again.
    second, is_new = watch.observe(now=1100.0)
    assert is_new is True, "a call after the ringing stopped is a new call"
    assert second is not first


def test_two_calls_far_enough_apart_are_two_calls(monkeypatch):
    """The positive control at the reader. A rule that answers "one call" to everything
    has distinguished nothing — and this is the level where that would show up as one
    verification confirmed by a call that arrived for another."""
    class _Clock:
        now = 1000.0

        @classmethod
        def monotonic(cls):
            return cls.now

    monkeypatch.setattr(calls_mod, "time", _Clock)

    async def body():
        m = _manager(monkeypatch)
        m._reader_link = ScriptedPort([b"\r\nRING\r\n", (CLIP + "\r\n").encode()])
        task = asyncio.get_event_loop().create_task(m.reader_loop())
        await asyncio.sleep(0.05)
        _Clock.now += 120.0          # the ringing stopped two minutes ago
        m._reader_link._chunks.extend([b"\r\nRING\r\n", (CLIP + "\r\n").encode()])
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return await _calls()

    rows = _run(body)
    assert len(rows) == 2, f"two calls became {len(rows)}"


def test_a_ring_with_no_number_is_still_a_call(monkeypatch):
    """`RING` needs no subscription and arrives on its own. A call nobody can name is
    still a call that happened, and it is the only symptom of a caller-ID subscription
    lost without a `CFUN` cycle."""
    async def body():
        m = _manager(monkeypatch)
        await _drive(m, [b"\r\nRING\r\n"] * 5)
        return await _calls()

    rows = _run(body)
    assert rows == [(None, None, "no_number")], rows


def test_a_withheld_number_leaves_the_call_nameless_and_is_no_fault(monkeypatch, caplog):
    """With the subscription held, an anonymous call means the caller withheld their
    number — an ordinary outcome. It confirms nothing and it is not a malfunction."""
    async def body():
        m = _manager(monkeypatch)
        await _drive(m, [b"\r\nRING\r\n", (CLIP_WITHHELD + "\r\n").encode()])
        return await _calls()

    with caplog.at_level("ERROR"):
        rows = _run(body)
    assert rows == [(None, None, "no_number")], rows
    assert not [r for r in caplog.records if r.levelname == "ERROR"], (
        "a caller who withholds their number is not an error"
    )


def test_a_clip_without_its_ring_still_records_the_call(monkeypatch):
    """The join must not be the thing that loses the event. A lost `RING` — a truncated
    read, a reopened port mid-call — leaves the number arriving alone."""
    async def body():
        m = _manager(monkeypatch)
        await _drive(m, [(CLIP + "\r\n").encode()])
        return await _calls()

    rows = _run(body)
    assert rows == [(CALLER, CALLER, "unattributed")], rows


# --- canonicalisation, per AGENTS.md: before storage, never after ----------------------

def test_the_number_is_canonicalised_before_it_is_stored(monkeypatch):
    """A national-format caller has to match a number stored in E.164, and matching is
    not the place to discover that. The raw form is kept beside it, because what the
    network said is evidence and our reading of it is not."""
    async def body():
        m = _manager(monkeypatch)
        await _drive(m, [b"\r\nRING\r\n", b'+CLIP: "89261234888",129,,,,0\r\n'])
        return await _calls()

    rows = _run(body)
    assert rows == [(CALLER, "89261234888", "unattributed")], rows


def test_a_caller_that_is_not_a_number_at_all_is_not_stored_as_one(monkeypatch):
    """Service callers exist and short codes exist. "No usable caller number" covers
    them: nothing can be matched against it, and pretending otherwise would put a
    non-number where a phone number is expected."""
    async def body():
        m = _manager(monkeypatch)
        await _drive(m, [b"\r\nRING\r\n", b'+CLIP: "112",129,,,,0\r\n'])
        return await _calls()

    rows = _run(body)
    assert rows == [(None, "112", "no_number")], rows


# --- a call is not a message, and the reader says nothing to the modem -----------------

def test_a_call_is_not_filed_among_inbound_messages(monkeypatch):
    """The record that makes ordinary inbound traffic visible in the console is not the
    place for an event that carries no text."""
    async def body():
        m = _manager(monkeypatch)
        await _drive(m, [b"\r\nRING\r\n", (CLIP + "\r\n").encode()])
        db = await get_db()
        async with db.execute("SELECT COUNT(*) FROM inbound_messages") as cur:
            return (await cur.fetchone())[0]

    assert _run(body) == 0


def test_the_reader_issues_no_at_command_for_a_call(monkeypatch):
    """`ATH` stays out until the sequence has been measured end to end on the live modem
    — that it ends an *unanswered* incoming call on this firmware is an assertion, and it
    needs the command port the sender holds. Confirmation never depended on it."""
    async def body():
        m = _manager(monkeypatch)
        issued = []

        async def spy(cmd, timeout=5.0):
            issued.append(cmd)
            return "OK"

        m._sender.command = spy
        await _drive(m, [b"\r\nRING\r\n", (CLIP + "\r\n").encode()])
        return issued

    assert _run(body) == []


# --- what an operator can see ----------------------------------------------------------

def test_calls_without_a_number_are_counted_for_an_operator(monkeypatch):
    """The only detector for a subscription dropped without a `CFUN` cycle. The record
    the gateway keeps of its own `AT+CLIP=1` cannot see that happen; a rate of nameless
    calls can."""
    async def body():
        m = _manager(monkeypatch)
        await _drive(m, [b"\r\nRING\r\n", (CLIP + "\r\n").encode()])
        m._calls._gap = 0.0
        await _drive(m, [b"\r\nRING\r\n"])
        return (
            await queries.count_inbound_calls(),
            await queries.count_calls_without_number(),
        )

    assert _run(body) == (2, 1)


def test_the_operator_page_says_whether_caller_id_is_held(monkeypatch):
    """The record separates "the caller withheld their number" from "we never had caller
    ID at all", and an operator looking at a page full of nameless calls is exactly who
    needs that separation made for them."""
    async def body():
        m = _manager(monkeypatch)
        m._sender._clip_subscribed = True
        m._sender._writer = object()
        held = m.health_snapshot()["caller_id"]
        m._sender._clip_subscribed = False
        return held, m.health_snapshot()["caller_id"]

    assert _run(body) == ("held", "not held")


def test_the_operator_page_carries_the_count_of_nameless_calls(monkeypatch):
    """4.4 — and it survives a modem that has stopped answering, because a sweep that
    stops at the first dead query would hide precisely the counter that says the modem
    has changed its behaviour."""
    async def body():
        m = _manager(monkeypatch)
        await _drive(m, [b"\r\nRING\r\n", (CLIP + "\r\n").encode()])
        m._calls._gap = 0.0
        await _drive(m, [b"\r\nRING\r\n"])
        diag = await m.collect_diagnostics()
        return [d for d in diag if d["key"] == "calls"]

    entries = _run(body)
    assert len(entries) == 1, f"no calls entry on the diagnostics page: {entries}"
    assert entries[0]["parsed"] == {"calls_total": 2, "calls_without_number": 1}


def test_a_call_that_cannot_be_recorded_does_not_take_the_reader_with_it(
    monkeypatch, caplog
):
    """The guard `+CDS` already has, on the path this change adds.

    Losing `reader_loop` is silent and total — no delivery reports and no inbound SMS —
    and a call now reaches the database from it. A locked table or a disk error must cost
    the call, not the loop: the `+CMTI` behind it is somebody's message.
    """
    async def body():
        m = _manager(monkeypatch)

        async def boom(*a, **kw):
            raise RuntimeError("the database said no")

        monkeypatch.setattr(queries, "record_inbound_call", boom)
        await _drive(m, [b"\r\nRING\r\n", b'+CMTI: "ME",7\r\n'])
        return m._inbound_indices.qsize()

    with caplog.at_level("ERROR"):
        queued = _run(body)
    assert queued == 1, "the message notification behind the call was lost with the loop"
    assert any("call" in r.getMessage().lower() for r in caplog.records), (
        "a call that could not be recorded must reach the operator, not vanish"
    )
