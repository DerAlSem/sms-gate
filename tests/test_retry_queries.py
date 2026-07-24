"""Persistence behind retrying: the attempt counter, the schedule, and which
`pending` messages the scheduler is allowed to claim."""

import asyncio

from app.db import queries
from app.db.connection import close_db, get_db, init_db
from app.db.migrate import run_migrations


def _with_db(coro):
    async def run():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("app1", "token-app1")
        return await coro()
    try:
        return asyncio.run(run())
    finally:
        asyncio.run(close_db())


async def _backdate(message_id: int, seconds: int) -> None:
    """Age a message's creation, so the scheduler's grace window can be exercised
    without the test sleeping."""
    db = await get_db()
    await db.execute(
        "UPDATE messages SET created_at = datetime('now', ? || ' seconds') WHERE id = ?",
        (f"-{seconds}", message_id),
    )
    await db.commit()


def test_migration_adds_the_retry_columns_and_is_idempotent():
    async def body():
        await run_migrations()          # run_migrations runs on every start
        await run_migrations()
        db = await get_db()
        async with db.execute("PRAGMA table_info(messages)") as cur:
            return {row[1] async for row in cur}

    cols = _with_db(body)
    assert "attempts" in cols
    assert "next_attempt_at" in cols


def test_a_new_message_starts_with_no_attempts_and_no_schedule():
    async def body():
        mid = await queries.create_message("app1", "+79990000001", "hi")
        db = await get_db()
        async with db.execute(
            "SELECT status, attempts, next_attempt_at FROM messages WHERE id = ?", (mid,)
        ) as cur:
            return await cur.fetchone()

    row = _with_db(body)
    assert row["status"] == "pending"
    assert row["attempts"] == 0
    assert row["next_attempt_at"] is None


def test_scheduling_a_retry_bumps_attempts_and_keeps_the_message_pending():
    async def body():
        mid = await queries.create_message("app1", "+79990000001", "hi")
        await queries.schedule_message_retry(mid, 30, "no response from modem (timeout)")
        db = await get_db()
        async with db.execute(
            "SELECT status, attempts, error, next_attempt_at FROM messages WHERE id = ?",
            (mid,),
        ) as cur:
            first = await cur.fetchone()
        await queries.schedule_message_retry(mid, 120, "no response from modem (timeout)")
        async with db.execute("SELECT attempts FROM messages WHERE id = ?", (mid,)) as cur:
            second = await cur.fetchone()
        return dict(first), second["attempts"]

    first, attempts_after_second = _with_db(body)
    assert first["status"] == "pending"
    assert first["attempts"] == 1
    assert first["error"] == "no response from modem (timeout)"
    assert first["next_attempt_at"] is not None
    assert attempts_after_second == 2


def test_a_freshly_accepted_message_is_not_claimed_by_the_scheduler():
    """It is already in the in-memory queue; claiming it would send it twice."""
    async def body():
        await queries.create_message("app1", "+79990000001", "hi")
        return await queries.due_pending_messages()

    assert _with_db(body) == []


def test_a_message_stranded_by_a_restart_is_claimed_once_it_is_old_enough():
    async def body():
        mid = await queries.create_message("app1", "+79990000001", "hi")
        await _backdate(mid, 120)
        rows = await queries.due_pending_messages()
        return mid, [dict(r) for r in rows]

    mid, rows = _with_db(body)
    assert [r["id"] for r in rows] == [mid]
    assert rows[0]["phone"] == "+79990000001"
    assert rows[0]["text"] == "hi"
    assert rows[0]["app_id"] == "app1"


def test_a_retry_is_claimed_only_once_it_is_due():
    async def body():
        mid = await queries.create_message("app1", "+79990000001", "hi")
        await queries.schedule_message_retry(mid, 300, "timeout")
        not_yet = await queries.due_pending_messages()
        await queries.schedule_message_retry(mid, -1, "timeout")   # now in the past
        due = await queries.due_pending_messages()
        return [r["id"] for r in not_yet], [r["id"] for r in due], mid

    not_yet, due, mid = _with_db(body)
    assert not_yet == []
    assert due == [mid]


def test_a_finished_message_is_never_claimed():
    async def body():
        sent = await queries.create_message("app1", "+79990000001", "one")
        failed = await queries.create_message("app1", "+79990000002", "two")
        await _backdate(sent, 120)
        await _backdate(failed, 120)
        await queries.set_message_sent(sent, 10)
        await queries.set_message_failed(failed, "+CMS ERROR 1 (unassigned number)")
        return await queries.due_pending_messages()

    assert _with_db(body) == []
