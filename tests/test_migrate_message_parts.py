"""Rebuilding `message_parts` onto `(message_id, seq)`.

SQLite cannot replace a primary key in place, so the table is rebuilt. The naive script
is unsafe in three separate ways and all three are pinned here:

  * `executescript` commits implicitly — a kill between `DROP` and `RENAME` leaves no
    `message_parts`, the base `CREATE TABLE IF NOT EXISTS` recreates the *old* shape
    empty on the next boot, and the service crash-loops with the part records gone;
  * a guard that reads the presence of a column instead of the shape of the primary key
    lies for ever once anyone adds that column;
  * a column-wise `MAX()` assembles a row that never existed and silently downgrades a
    confirmed part to outstanding.
"""
import asyncio
import logging

from app.db import queries
from app.db.connection import close_db, get_db, init_db
from app.db.migrate import run_migrations

# What `message_parts` looked like before this change: keyed on the number the modem
# chose, so the whole table could never hold more than 256 rows.
_OLD_PARTS_DDL = """
    CREATE TABLE message_parts (
        modem_ref   INTEGER PRIMARY KEY,
        message_id  INTEGER NOT NULL REFERENCES messages(id),
        seq         INTEGER NOT NULL,
        total       INTEGER NOT NULL,
        status      TEXT NOT NULL DEFAULT 'sent'
    )
"""


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


async def _downgrade_to_the_old_shape() -> None:
    """Put the database back the way an upgrading install finds it."""
    db = await get_db()
    await db.execute("DROP TABLE IF EXISTS message_parts")
    await db.execute(_OLD_PARTS_DDL)
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_message_parts_message ON message_parts(message_id)"
    )
    await db.commit()


async def _legacy_part(modem_ref: int, message_id: int, seq: int,
                       total: int = 1, status: str = "sent") -> None:
    db = await get_db()
    await db.execute(
        "INSERT INTO message_parts (modem_ref, message_id, seq, total, status) "
        "VALUES (?, ?, ?, ?, ?)",
        (modem_ref, message_id, seq, total, status),
    )
    await db.commit()


async def _parts_table_sql() -> str:
    db = await get_db()
    async with db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='message_parts'"
    ) as cursor:
        row = await cursor.fetchone()
    return " ".join((row[0] or "").split()).lower()


async def _indexes_on_parts() -> set[str]:
    db = await get_db()
    async with db.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='message_parts'"
    ) as cursor:
        return {row[0] for row in await cursor.fetchall()}


async def _all_parts() -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT message_id, seq, modem_ref, total, status, sent_at FROM message_parts "
        "ORDER BY message_id, seq"
    ) as cursor:
        return [dict(r) for r in await cursor.fetchall()]


def test_existing_parts_survive_with_status_and_a_backfilled_submit_time():
    """Task 3.4 — carried over intact, dated from the message they belong to."""
    async def body():
        mid = await queries.create_message("app1", "+7999", "hi")
        await queries.set_message_sent(mid, 42)
        db = await get_db()
        await db.execute("UPDATE messages SET sent_at = '2026-06-01 10:00:00'")
        await db.commit()

        await _downgrade_to_the_old_shape()
        await _legacy_part(42, mid, seq=1, total=2, status="delivered")
        await _legacy_part(43, mid, seq=2, total=2, status="sent")

        await run_migrations()
        return await _all_parts()

    parts = _run(body)
    assert [(p["seq"], p["status"], p["modem_ref"]) for p in parts] == [
        (1, "delivered", 42), (2, "sent", 43),
    ]
    assert all(p["sent_at"] == "2026-06-01 10:00:00" for p in parts), (
        "a per-segment submit time was never recorded, so it comes from the message"
    )


def test_the_rebuild_runs_once_and_the_guard_reads_the_key_shape():
    """Task 3.5 — idempotent, and idempotent on the fact that actually changed."""
    async def body():
        await _downgrade_to_the_old_shape()
        # A column anyone could have added with `_add_column_if_missing`. A guard that
        # tests for `sent_at` would now believe the rebuild had already happened, and
        # would believe it for ever.
        db = await get_db()
        await db.execute("ALTER TABLE message_parts ADD COLUMN sent_at TIMESTAMP")
        await db.commit()

        await run_migrations()
        first = await _parts_table_sql()
        await run_migrations()
        await run_migrations()
        return first, await _parts_table_sql()

    first, later = _run(body)
    assert "primary key (message_id, seq)" in first, (
        "the rebuild ran despite `sent_at` already being present"
    )
    assert later == first, "and running again changed nothing"


def test_a_fresh_install_gets_the_new_shape_and_never_rebuilds(caplog):
    """Task 3.6 — the trap the base DDL sets for itself.

    The guard reads the DDL SQLite stored. If the base `CREATE TABLE` is written so the
    guard cannot match it, a brand-new database rebuilds `message_parts` on every single
    start, and nothing about that is visible from outside.
    """
    async def body():
        with caplog.at_level(logging.INFO, logger="app.db.migrate"):
            await run_migrations()      # second start
            await run_migrations()      # third
        return await _parts_table_sql()

    with caplog.at_level(logging.INFO, logger="app.db.migrate"):
        sql = _run(body)

    assert "primary key (message_id, seq)" in sql
    rebuilds = [r for r in caplog.records if "message_parts" in r.getMessage()
                and "rebuil" in r.getMessage().lower()]
    assert rebuilds == [], (
        "an empty database gets the new shape from the base DDL; the rebuild must not "
        f"run on any start. It ran {len(rebuilds)} time(s)."
    )


def test_a_legacy_duplicate_pair_keeps_the_confirmed_row():
    """Task 3.7 — one whole row per pair, and never the blend.

    The old key was `modem_ref` and never constrained `(message_id, seq)`, so the pair
    can repeat. A column-wise `MAX()` picks `'sent'` over `'delivered'` under BINARY
    collation; picking the *latest* row loses it just as surely, because the report that
    confirmed the earlier transmission arrived against the earlier row. A confirmed part
    downgraded to outstanding then feeds the sweep and tells the owning app that a
    delivery failed.
    """
    async def body():
        mid = await queries.create_message("app1", "+7999", "hi")
        await queries.set_message_sent(mid, 42)
        await _downgrade_to_the_old_shape()
        # inserted FIRST, so it holds the lower rowid: the confirmation belongs to the
        # earlier transmission of the same segment
        await _legacy_part(42, mid, seq=1, total=1, status="delivered")
        await _legacy_part(200, mid, seq=1, total=1, status="sent")

        await run_migrations()
        return await _all_parts()

    parts = _run(body)
    assert len(parts) == 1, "the duplicate did not abort the migration"
    assert parts[0]["status"] == "delivered", (
        "the confirmed row survived; a column-wise MAX() or a bare MAX(rowid) loses it"
    )
    assert parts[0]["modem_ref"] in (42, 200), "a whole row, not a blend of two"


def test_an_orphan_part_is_dropped():
    """A part whose message is gone is unattributable by definition, and carrying it
    forward would feed it back into the candidate set."""
    async def body():
        await _downgrade_to_the_old_shape()
        db = await get_db()
        # An orphan cannot be created with the constraint on — which is exactly why the
        # ones in the live database predate it, or outlived the message they named.
        await db.execute("PRAGMA foreign_keys = OFF")
        await _legacy_part(99, 4242, seq=1)     # no such message
        await db.execute("PRAGMA foreign_keys = ON")
        await run_migrations()
        return await _all_parts()

    assert _run(body) == []


def test_a_crashed_run_leaves_a_scratch_table_and_the_next_start_recovers():
    """Task 3.8 — `message_parts_v2` from a killed rebuild must not crash-loop."""
    async def body():
        mid = await queries.create_message("app1", "+7999", "hi")
        await queries.set_message_sent(mid, 42)
        await _downgrade_to_the_old_shape()
        await _legacy_part(42, mid, seq=1)

        db = await get_db()
        await db.execute("CREATE TABLE message_parts_v2 (junk INTEGER)")
        await db.commit()

        await run_migrations()
        return await _all_parts(), await _parts_table_sql()

    parts, sql = _run(body)
    assert "primary key (message_id, seq)" in sql
    assert len(parts) == 1 and parts[0]["modem_ref"] == 42


def test_both_indexes_exist_after_the_rebuild():
    """Task 3.9 — `DROP TABLE` takes its indexes with it, and the base script that
    created one has already run by then. The reference index is new and load-bearing:
    candidate lookup is a `modem_ref` scan over a table this change stops bounding at
    256 rows."""
    async def body():
        await _downgrade_to_the_old_shape()
        await run_migrations()
        return await _indexes_on_parts()

    names = _run(body)
    assert "idx_message_parts_message" in names
    assert "idx_message_parts_ref" in names


def test_a_fresh_install_has_both_indexes_too():
    assert {"idx_message_parts_message", "idx_message_parts_ref"} <= _run(_indexes_on_parts)
