"""Deletion, now that the eligibility rule has a bound and the ledger outlives the row.

The refusal to delete an `expired` message was justified by an eligibility that never
ended. It ends now — and the refusal stands, on a second reason: an `expired` message is
one whose outcome the gateway never learned, and the record of an unanswered question is
not the operator's routine tidying. The eligibility rule may acquire a bound without the
deletion rule acquiring one.
"""
import asyncio

from app.db import queries
from app.db.connection import close_db, get_db, init_db
from app.db.migrate import run_migrations


def _run(body):
    async def go():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("app1", "token-app1")
        return await body()
    try:
        return asyncio.run(go())
    finally:
        asyncio.run(close_db())


async def _age_everything(days: int) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE messages SET created_at = datetime('now', ? || ' days'), "
        "sent_at = datetime('now', ? || ' days')", (f"-{days}", f"-{days}")
    )
    await db.execute(
        "UPDATE message_parts SET sent_at = datetime('now', ? || ' days')", (f"-{days}",)
    )
    await db.commit()


def test_an_expired_message_past_the_window_still_cannot_be_deleted():
    """Task 7.5, first half — thirty days old, so no report can reach it any more."""
    async def body():
        mid = await queries.create_message("app1", "+79031680015", "hi")
        await queries.set_message_sent(mid, 42)
        await queries.add_message_part(mid, 42, 1, 1)
        await _age_everything(30)
        await queries.expire_stale_messages(60)
        refusal = await queries.delete_outbound(mid)
        db = await get_db()
        async with db.execute(
            "SELECT status FROM messages WHERE id = ?", (mid,)
        ) as cur:
            row = await cur.fetchone()
        return refusal, row["status"] if row else None

    refusal, status = _run(body)
    assert refusal is not None, (
        "an expired message is one whose outcome the gateway never learned; the record "
        "of an unanswered question is not routine tidying"
    )
    assert status == "expired", "and nothing was removed"


def test_deleting_an_eligible_message_leaves_its_delivery_reports():
    """Task 7.5, second half — the ledger is the account of what the network said, not
    part of the message. It carries the recipient's number and outlives the row, and it
    is removed by its own retention rather than by this operation."""
    async def body():
        mid = await queries.create_message("app1", "+79031680015", "hi")
        await queries.set_message_sent(mid, 42)
        await queries.add_message_part(mid, 42, 1, 1)
        await queries.record_delivery_report(
            raw_line="+CDS: 6,42,...", outcome="attributed", modem_ref=42,
            message_id=mid, seq=1, recipient="+79031680015",
        )
        await queries.set_part_delivered(mid, 1)
        await queries.set_message_delivered(mid)
        await _age_everything(2)

        refusal = await queries.delete_outbound(mid)
        db = await get_db()
        async with db.execute("SELECT COUNT(*) FROM delivery_reports") as cur:
            reports = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM message_parts") as cur:
            parts = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM messages") as cur:
            messages = (await cur.fetchone())[0]
        return refusal, reports, parts, messages

    refusal, reports, parts, messages = _run(body)
    assert refusal is None, "an audit table must not be able to refuse a deletion"
    assert (messages, parts) == (0, 0), "the message and its part records are gone"
    assert reports == 1, "and the account of what the network said remains"
