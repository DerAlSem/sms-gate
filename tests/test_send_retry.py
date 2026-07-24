"""Retry behaviour of the sender and the scheduler.

The tests that matter most here are the ones asserting a message is *not* retried.
Losing a message costs an operator a manual resend; sending it twice puts a second
payment link or login code on a real person's handset, and cannot be taken back.
"""

import asyncio

import pytest

import app.modem.manager as manager_mod
from app.db import queries
from app.db.connection import close_db, get_db, init_db
from app.db.migrate import run_migrations
from app.modem.at_commands import ATCommandError
from app.modem.manager import ModemManager, OutgoingMessage
from app.settings_store import store

PHONE = "+79990000001"


class _Recorder:
    """Captures the two things a failure is supposed to produce for the outside world:
    a delivery webhook and an operator alert."""

    def __init__(self, monkeypatch):
        self.dispatched = []
        self.alerts = []
        monkeypatch.setattr(
            manager_mod, "spawn_delivery_dispatch",
            lambda mid, status, error=None: self.dispatched.append((mid, status, error)),
        )
        monkeypatch.setattr(
            manager_mod, "notify",
            lambda event, body, dedup_extra=None, phone=None: self.alerts.append(body),
        )

    @property
    def failures(self):
        return [d for d in self.dispatched if d[1] == "failed"]


async def _registered():
    return True


def _manager(send_impl):
    m = ModemManager("/dev/null", "/dev/null")
    m._sender.send_sms_pdu = send_impl
    # The send path now asks the modem whether it is on the network before transmitting;
    # these tests are about what happens once it does.
    m._sender.registration_state = _registered
    return m


def _run(body):
    async def go():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("app1", "token-app1")
        await store.load()
        return await body()
    try:
        return asyncio.run(go())
    finally:
        asyncio.run(close_db())


async def _state(message_id: int) -> dict:
    db = await get_db()
    async with db.execute(
        "SELECT status, attempts, error, last_attempt_error, next_attempt_at "
        "FROM messages WHERE id = ?", (message_id,),
    ) as cur:
        return dict(await cur.fetchone())


def _failing(error: str, *, pdu_submitted: bool = False, send_first_part: bool = False):
    async def send(parts, on_part_sent, **kw):
        if send_first_part:
            await on_part_sent(1, 42)
        raise ATCommandError(error, pdu_submitted=pdu_submitted)
    return send


# --------------------------------------------------------------------------- retrying


def test_a_transient_failure_defers_instead_of_failing(monkeypatch):
    rec = _Recorder(monkeypatch)

    async def body():
        m = _manager(_failing("no response from modem (timeout)"))
        mid = await queries.create_message("app1", PHONE, "hi")
        await m._send_one(OutgoingMessage(mid, PHONE, "hi", "app1"))
        return await _state(mid)

    state = _run(body)
    assert state["status"] == "pending"
    assert state["attempts"] == 1
    assert state["next_attempt_at"] is not None
    assert state["error"] is None
    assert state["last_attempt_error"] == "no response from modem (timeout)"
    # The whole point of D1: GM+ must not be told about a failure that resolves itself.
    assert rec.failures == []


def test_the_message_fails_once_the_budget_is_exhausted(monkeypatch):
    rec = _Recorder(monkeypatch)

    async def body():
        m = _manager(_failing("no response from modem (timeout)"))
        mid = await queries.create_message("app1", PHONE, "hi")
        msg = OutgoingMessage(mid, PHONE, "hi", "app1")
        for _ in range(4):                       # default budget: 3 delays + 1
            await m._send_one(msg)
        return mid, await _state(mid)

    mid, state = _run(body)
    assert state["status"] == "failed"
    assert state["attempts"] == 4
    assert state["error"] == "no response from modem (timeout)"
    assert rec.failures == [(mid, "failed", "no response from modem (timeout)")]
    assert any("after 4 attempts" in a for a in rec.alerts)


def test_retrying_can_be_switched_off(monkeypatch):
    """The declared rollback: an empty backoff gives every message one attempt."""
    _Recorder(monkeypatch)

    async def body():
        await store.set_many({"send_retry_backoff": ""})
        m = _manager(_failing("no response from modem (timeout)"))
        mid = await queries.create_message("app1", PHONE, "hi")
        await m._send_one(OutgoingMessage(mid, PHONE, "hi", "app1"))
        return await _state(mid)

    assert _run(body)["status"] == "failed"


# ------------------------------------------------------------------- never retried


def test_a_failure_after_the_pdu_was_written_is_not_retried(monkeypatch):
    """The SMSC may already hold the message; the wire cannot tell us. This is the
    exact shape of six historical prod failures (`Timeout waiting for b'OK', got: b''`)
    that a text-only classifier would have duplicated."""
    rec = _Recorder(monkeypatch)

    async def body():
        m = _manager(_failing("no response from modem (timeout)", pdu_submitted=True))
        mid = await queries.create_message("app1", PHONE, "hi")
        await m._send_one(OutgoingMessage(mid, PHONE, "hi", "app1"))
        return mid, await _state(mid)

    mid, state = _run(body)
    assert state["status"] == "failed"
    assert state["next_attempt_at"] is None
    assert rec.failures == [(mid, "failed", "no response from modem (timeout)")]


def test_a_multipart_message_whose_first_part_went_out_is_not_retried(monkeypatch):
    """Resending would deliver part 1 twice, and reuse its concatenation reference.
    This is prod message 976: part 1 accepted, part 2 timed out."""
    rec = _Recorder(monkeypatch)

    async def body():
        m = _manager(_failing("no response from modem (timeout)", send_first_part=True))
        mid = await queries.create_message("app1", PHONE, "hi")
        await m._send_one(OutgoingMessage(mid, PHONE, "hi", "app1"))
        return await _state(mid)

    state = _run(body)
    assert state["status"] == "failed"
    assert state["next_attempt_at"] is None
    assert ("sent" in [d[1] for d in rec.dispatched])


def test_a_permanent_failure_is_not_retried(monkeypatch):
    rec = _Recorder(monkeypatch)

    async def body():
        m = _manager(_failing("+CMS ERROR 1 (unassigned number)"))
        mid = await queries.create_message("app1", PHONE, "hi")
        await m._send_one(OutgoingMessage(mid, PHONE, "hi", "app1"))
        return await _state(mid)

    state = _run(body)
    assert state["status"] == "failed"
    assert state["attempts"] == 1
    assert state["next_attempt_at"] is None
    assert len(rec.failures) == 1


# -------------------------------------------------------------------- robustness


def test_a_non_at_error_fails_the_message_and_leaves_the_sender_alive(monkeypatch):
    """Before this, anything but an ATCommandError escaped the loop and killed the
    sender silently — and with a scheduler running, the queue would fill forever."""
    rec = _Recorder(monkeypatch)

    async def body():
        async def boom(parts, on_part_sent, **kw):
            raise RuntimeError("database is locked")

        m = _manager(boom)
        mid = await queries.create_message("app1", PHONE, "hi")
        task = asyncio.create_task(m.sender_loop())
        await m.enqueue(mid, PHONE, "hi", "app1")
        await asyncio.wait_for(m._queue.join(), timeout=2)
        alive = not task.done()
        task.cancel()
        return alive, m._held, await _state(mid)

    alive, held, state = _run(body)
    assert alive, "the sender loop must survive an unexpected error"
    assert held == set(), "the held id must be released or the scheduler goes blind"
    assert state["status"] == "failed"
    assert len(rec.failures) == 1


# --------------------------------------------------------------------- scheduler


def test_the_scheduler_requeues_a_due_message(monkeypatch):
    _Recorder(monkeypatch)

    async def body():
        m = _manager(_failing("unused"))
        mid = await queries.create_message("app1", PHONE, "hi")
        db = await get_db()
        await db.execute(
            "UPDATE messages SET next_attempt_at = datetime('now', '-1 seconds') "
            "WHERE id = ?", (mid,))
        await db.commit()
        await m._retry_step()
        return mid, m._queue.qsize(), m._held

    mid, size, held = _run(body)
    assert size == 1
    assert held == {mid}


def test_the_scheduler_skips_a_message_the_sender_already_holds(monkeypatch):
    _Recorder(monkeypatch)

    async def body():
        m = _manager(_failing("unused"))
        mid = await queries.create_message("app1", PHONE, "hi")
        db = await get_db()
        await db.execute(
            "UPDATE messages SET next_attempt_at = datetime('now', '-1 seconds') "
            "WHERE id = ?", (mid,))
        await db.commit()
        m._held.add(mid)                     # already queued or in flight
        await m._retry_step()
        return m._queue.qsize()

    assert _run(body) == 0


def test_a_number_blacklisted_while_pending_is_not_retried(monkeypatch):
    """Both other enqueue paths check the blacklist; a retry must not be the way round
    it. The block can land mid-ladder, from a delivery report on another message."""
    rec = _Recorder(monkeypatch)

    async def body():
        m = _manager(_failing("unused"))
        mid = await queries.create_message("app1", PHONE, "hi")
        db = await get_db()
        await db.execute(
            "UPDATE messages SET next_attempt_at = datetime('now', '-1 seconds') "
            "WHERE id = ?", (mid,))
        await db.commit()
        for _ in range(store.blacklist_threshold):
            await queries.record_permanent_fail(PHONE, "gone", store.blacklist_threshold)
        await m._retry_step()
        return m._queue.qsize(), await _state(mid)

    size, state = _run(body)
    assert size == 0
    assert state["status"] == "failed"
    assert "blacklisted" in state["error"]
    assert len(rec.failures) == 1


def test_the_scheduler_gives_up_on_a_message_that_outlived_its_budget(monkeypatch):
    """Nothing else sweeps `pending`, so without this the app polling it never sees a
    terminal status."""
    rec = _Recorder(monkeypatch)

    async def body():
        m = _manager(_failing("unused"))
        mid = await queries.create_message("app1", PHONE, "hi")
        await queries.begin_message_attempt(mid)         # died mid-send: no schedule
        db = await get_db()
        await db.execute(
            "UPDATE messages SET created_at = datetime('now', '-4000 seconds') "
            "WHERE id = ?", (mid,))
        await db.commit()
        await m._retry_step()
        return mid, m._queue.qsize(), await _state(mid)

    mid, size, state = _run(body)
    assert size == 0, "a message past its deadline must not be sent"
    assert state["status"] == "failed"
    assert rec.failures == [(mid, "failed", "never transmitted")]


def test_a_failing_scheduler_tick_does_not_stop_the_scheduler(monkeypatch):
    _Recorder(monkeypatch)

    async def body():
        m = _manager(_failing("unused"))
        calls = []

        async def boom():
            calls.append(1)
            raise RuntimeError("database is locked")

        m._retry_step = boom
        task = asyncio.create_task(m.retry_loop(interval_seconds=0.01))
        await asyncio.sleep(0.1)
        alive = not task.done()
        task.cancel()
        return alive, len(calls)

    alive, calls = _run(body)
    assert alive
    assert calls > 1, "the loop must keep ticking after a failure"


def test_the_whole_ladder_fits_inside_the_deadline(monkeypatch):
    """The ladder and the deadline are derived from the same setting, so they must not
    disagree — the first version's margin was too thin and the fourth attempt fell
    outside it whenever attempts ran slowly, silently making a four-attempt budget a
    three-attempt one."""
    _Recorder(monkeypatch)

    async def body():
        m = _manager(_failing("no response from modem (timeout)"))
        mid = await queries.create_message("app1", PHONE, "hi")
        msg = OutgoingMessage(mid, PHONE, "hi", "app1")
        db = await get_db()
        deadline = m._retry_deadline()
        backoff = store.send_retry_backoff_parsed
        elapsed = 0
        hops = []

        for delay in backoff:
            await m._send_one(msg)                     # this attempt runs and fails
            # Wall clock between two attempts: the failing exchange, the scheduled
            # delay, and one scheduler tick of granularity.
            elapsed += 37 + delay + 15
            await db.execute(
                "UPDATE messages SET created_at = datetime('now', ? || ' seconds'), "
                "next_attempt_at = datetime('now', '-1 seconds') WHERE id = ?",
                (f"-{elapsed}", mid),
            )
            await db.commit()
            due = [r["id"] for r in await queries.due_pending_messages(deadline)]
            stale = [r["id"] for r in await queries.stale_pending_messages(deadline)]
            hops.append((mid in due, mid in stale))

        await m._send_one(msg)                         # the final attempt
        return hops, await _state(mid), m._health.budget_exhausted

    hops, state, exhausted = _run(body)
    assert hops == [(True, False)] * 3, (
        f"every retry must still be due and not yet swept, got {hops}")
    assert state["attempts"] == 4, "the ladder must actually run four attempts"
    assert state["status"] == "failed"
    assert exhausted is True, "an exhausted ladder is evidence the modem cannot send"
