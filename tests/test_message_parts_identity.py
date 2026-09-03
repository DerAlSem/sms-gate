"""A part is identified by its message and segment, not by the number the network chose.

`modem_ref` is one octet. It was the PRIMARY KEY of `message_parts`, and parts were
written with `INSERT OR REPLACE` — so every 257th send did not add a row, it *overwrote*
the row of the message that held that reference before. The table could never hold more
than 256 rows, and production held exactly 256.
"""
import asyncio

import pytest

from app.db import queries
from app.db.connection import close_db, get_db, init_db
from app.db.migrate import run_migrations


def _with_db(coro):
    async def run():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("app1", "tok1", "test")
        return await coro()
    try:
        return asyncio.run(run())
    finally:
        asyncio.run(close_db())


async def _mark_part(message_id: int, seq: int, status: str) -> None:
    """Set a part's status directly. Phase 3 is about the row's identity, not about who
    writes to it — the status writers are rewritten in phase 4 and this test must not
    depend on their shape."""
    db = await get_db()
    await db.execute(
        "UPDATE message_parts SET status = ? WHERE message_id = ? AND seq = ?",
        (status, message_id, seq),
    )
    await db.commit()


async def _parts_of(message_id: int) -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT seq, modem_ref, status, sent_at FROM message_parts "
        "WHERE message_id = ? ORDER BY seq",
        (message_id,),
    ) as cursor:
        return [dict(row) for row in await cursor.fetchall()]


def test_a_reused_reference_leaves_both_part_records():
    """Task 3.1 — the defect itself. The earlier message keeps its record and its status."""
    async def body():
        old = await queries.create_message("app1", "+79001112233", "first")
        await queries.set_message_sent(old, 42)
        await queries.add_message_part(old, 42, seq=1, total=1)
        await _mark_part(old, 1, "delivered")

        new = await queries.create_message("app1", "+79004445566", "later, same ref")
        await queries.set_message_sent(new, 42)
        await queries.add_message_part(new, 42, seq=1, total=1)

        return await _parts_of(old), await _parts_of(new)

    old_parts, new_parts = _with_db(body)
    assert len(old_parts) == 1, "the earlier message's part record survived the reuse"
    assert old_parts[0]["status"] == "delivered", "and it kept the status it had"
    assert len(new_parts) == 1
    assert new_parts[0]["modem_ref"] == 42


def test_recording_part_two_does_not_disturb_part_one():
    """Task 3.2 — segments of one message are separate rows with separate statuses."""
    async def body():
        mid = await queries.create_message("app1", "+7999", "long")
        await queries.set_message_sent(mid, 10)
        await queries.add_message_part(mid, 10, seq=1, total=2)
        await _mark_part(mid, 1, "delivered")
        await queries.add_message_part(mid, 11, seq=2, total=2)
        return await _parts_of(mid)

    parts = _with_db(body)
    assert [p["seq"] for p in parts] == [1, 2]
    assert parts[0]["status"] == "delivered"
    assert parts[1]["status"] == "sent"


def test_part_two_carries_its_own_submit_time():
    """Task 3.3 — the message's `sent_at` dates the message, not the segment."""
    async def body():
        mid = await queries.create_message("app1", "+7999", "long")
        await queries.set_message_sent(mid, 10)
        await queries.add_message_part(mid, 10, seq=1, total=2)
        db = await get_db()
        # The message and its first part are an hour old; the second segment is accepted
        # now. A `sent_at` copied from the message would read an hour old too.
        await db.execute("UPDATE messages SET sent_at = datetime('now', '-1 hour')")
        await db.execute("UPDATE message_parts SET sent_at = datetime('now', '-1 hour')")
        await db.commit()
        await queries.add_message_part(mid, 11, seq=2, total=2)

        async with db.execute("SELECT sent_at FROM messages WHERE id = ?", (mid,)) as cur:
            message_sent_at = (await cur.fetchone())[0]
        return message_sent_at, await _parts_of(mid)

    message_sent_at, parts = _with_db(body)
    assert parts[1]["sent_at"] is not None
    assert parts[1]["sent_at"] != message_sent_at, (
        "part 2's recorded time is when part 2 was accepted"
    )
    assert parts[1]["sent_at"] > parts[0]["sent_at"]


def test_a_part_records_its_submit_time_at_all():
    async def body():
        mid = await queries.create_message("app1", "+7999", "hi")
        await queries.set_message_sent(mid, 10)
        await queries.add_message_part(mid, 10, seq=1, total=1)
        return await _parts_of(mid)

    assert _with_db(body)[0]["sent_at"] is not None


def test_recording_the_same_segment_twice_raises():
    """Task 3.7a, half one — the reference and submit time are not silently discarded.

    `INSERT OR REPLACE` used to swallow this. On the new key it is a fault: the same
    segment of the same message cannot legitimately be accepted twice.
    """
    import sqlite3

    async def body():
        mid = await queries.create_message("app1", "+7999", "hi")
        await queries.set_message_sent(mid, 10)
        await queries.add_message_part(mid, 10, seq=1, total=1)
        with pytest.raises(sqlite3.IntegrityError):
            await queries.add_message_part(mid, 200, seq=1, total=1)
        return await _parts_of(mid)

    parts = _with_db(body)
    assert len(parts) == 1
    assert parts[0]["modem_ref"] == 10, "the first record stands"
