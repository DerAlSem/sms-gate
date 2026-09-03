"""The ledger itself: a record for every +CDS, and a retention that actually runs.

Storage only. What gets recorded for which outcome is behaviour, and lives with the
attribution tests.
"""
import asyncio
import json

from app.db import queries
from app.db.connection import close_db, get_db, init_db
from app.db.migrate import run_migrations


def _run(coro):
    async def go():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("app1", "tok1", "test")
        return await coro()
    try:
        return asyncio.run(go())
    finally:
        asyncio.run(close_db())


async def _records() -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM delivery_reports ORDER BY id"
    ) as cursor:
        return [dict(r) for r in await cursor.fetchall()]


def test_only_the_raw_line_and_the_outcome_are_required():
    """A line the parser cannot read has nothing else to record, and it is exactly the
    line that must not become the one event leaving no trace."""
    async def body():
        await queries.record_delivery_report(
            raw_line="+CDS: something the parser could not read",
            outcome="unparsable",
        )
        return await _records()

    records = _run(body)
    assert len(records) == 1
    row = records[0]
    assert row["raw_line"] == "+CDS: something the parser could not read"
    assert row["outcome"] == "unparsable"
    assert row["received_at"] is not None
    for optional in ("modem_ref", "recipient", "submitted_at", "discharged_at",
                     "status_code", "decided_by", "message_id", "seq", "candidates"):
        assert row[optional] is None, f"{optional} must be optional"


def test_a_full_record_keeps_every_field_it_was_given():
    async def body():
        mid = await queries.create_message("app1", "+79031680015", "hi")
        await queries.record_delivery_report(
            raw_line="+CDS: 6,42,...",
            outcome="attributed",
            modem_ref=42,
            recipient="+79031680015",
            submitted_at="2026-04-17 09:00:01",
            discharged_at="2026-04-17 09:00:03",
            status_code=0,
            decided_by="sole",
            message_id=mid,
            seq=1,
            candidates=[{"message_id": mid, "seq": 1, "outcome": "chosen"}],
            window_hours=168,
            strict=False,
        )
        return await _records()

    row = _run(body)[0]
    assert (row["modem_ref"], row["status_code"], row["seq"]) == (42, 0, 1)
    assert row["decided_by"] == "sole"
    assert row["recipient"] == "+79031680015"
    assert json.loads(row["candidates"]) == [
        {"message_id": 1, "seq": 1, "outcome": "chosen"}
    ]
    assert row["window_hours"] == 168
    assert row["strict"] == 0, "the switch value in force is recorded, not looked up later"


def test_the_record_outlives_the_message_it_names():
    """`message_id` is deliberately not a foreign key. With `PRAGMA foreign_keys = ON` a
    declared reference would turn every deletion of a message that has reports into a
    refusal — an operator surface breaking on an audit table."""
    async def body():
        mid = await queries.create_message("app1", "+7999", "hi")
        await queries.set_message_sent(mid, 42)
        await queries.add_message_part(mid, 42, seq=1, total=1)
        await queries.set_message_delivered(mid)
        await queries.record_delivery_report(
            raw_line="+CDS: 6,42,...", outcome="attributed", modem_ref=42, message_id=mid,
        )
        db = await get_db()
        await db.execute("UPDATE messages SET created_at = datetime('now', '-2 days')")
        await db.commit()
        refusal = await queries.delete_outbound(mid)
        return refusal, await _records()

    refusal, records = _run(body)
    assert refusal is None, "an audit table must not be able to refuse a deletion"
    assert len(records) == 1, "the account of what the network said outlives the row"


def test_pruning_removes_what_is_past_the_retention_and_nothing_newer():
    """Task 2.9."""
    async def body():
        await queries.record_delivery_report(raw_line="old", outcome="unplaced")
        await queries.record_delivery_report(raw_line="fresh", outcome="unplaced")
        db = await get_db()
        await db.execute(
            "UPDATE delivery_reports SET received_at = datetime('now', '-31 days') "
            "WHERE raw_line = 'old'"
        )
        await db.commit()
        gone = await queries.prune_delivery_reports(30 * 24 * 3600)
        return gone, [r["raw_line"] for r in await _records()]

    gone, remaining = _run(body)
    assert gone == 1
    assert remaining == ["fresh"]


def test_the_ledger_has_its_indexes():
    async def body():
        db = await get_db()
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND tbl_name='delivery_reports'"
        ) as cursor:
            return {r[0] for r in await cursor.fetchall()}

    names = _run(body)
    assert {"idx_delivery_reports_at", "idx_delivery_reports_ref"} <= names
