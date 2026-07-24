"""Persistence behind retrying.

The load-bearing idea: `next_attempt_at` is both the schedule and the claim marker. It
is cleared the instant a message is handed to the modem, so a message whose attempt was
cut short — by a crash, a hard reset, anything — has no schedule and can never be picked
up again. A duplicate SMS on a real handset is the worst outcome in this system, worse
than a message an operator has to push by hand.
"""

import asyncio

from app.db import queries
from app.db.connection import close_db, get_db, init_db
from app.db.migrate import run_migrations

DEADLINE = 570          # what ModemManager derives from the default backoff


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


async def _age(message_id: int, seconds: int) -> None:
    """Age a message by `seconds`, so the windows can be exercised without sleeping."""
    db = await get_db()
    await db.execute(
        """
        UPDATE messages
        SET created_at = datetime(created_at, ? || ' seconds'),
            next_attempt_at = datetime(next_attempt_at, ? || ' seconds')
        WHERE id = ?
        """,
        (f"-{seconds}", f"-{seconds}", message_id),
    )
    await db.commit()


async def _row(message_id: int):
    db = await get_db()
    async with db.execute(
        "SELECT status, attempts, error, last_attempt_error, next_attempt_at "
        "FROM messages WHERE id = ?",
        (message_id,),
    ) as cur:
        return dict(await cur.fetchone())


def test_migration_adds_the_retry_columns_and_is_idempotent():
    async def body():
        await run_migrations()          # run_migrations runs on every start
        await run_migrations()
        db = await get_db()
        async with db.execute("PRAGMA table_info(messages)") as cur:
            return {row[1] async for row in cur}

    cols = _with_db(body)
    assert {"attempts", "next_attempt_at", "last_attempt_error"} <= cols


def test_a_new_message_is_unattempted_but_recoverable():
    async def body():
        mid = await queries.create_message("app1", "+79990000001", "hi")
        return await _row(mid)

    row = _with_db(body)
    assert row["status"] == "pending"
    assert row["attempts"] == 0
    assert row["error"] is None
    # Set, so a restart that loses the in-memory queue can still recover it.
    assert row["next_attempt_at"] is not None


def test_claiming_a_message_counts_the_attempt_and_clears_its_schedule():
    async def body():
        mid = await queries.create_message("app1", "+79990000001", "hi")
        first = await queries.begin_message_attempt(mid)
        claimed = await _row(mid)
        await queries.schedule_message_retry(mid, 30, "timeout")
        second = await queries.begin_message_attempt(mid)
        return first, claimed, second

    first, claimed, second = _with_db(body)
    assert first == 1
    assert second == 2
    assert claimed["next_attempt_at"] is None


def test_a_message_being_transmitted_is_never_due_however_long_it_takes():
    """The crash-mid-send guard: no schedule means no resend, so the SMSC can never be
    handed the same message twice."""
    async def body():
        mid = await queries.create_message("app1", "+79990000001", "hi")
        await queries.begin_message_attempt(mid)
        await _age(mid, 3600)               # a very slow multipart send, or a crash
        return await queries.due_pending_messages(DEADLINE)

    assert _with_db(body) == []


def test_scheduling_a_retry_leaves_the_message_pending_and_error_untouched():
    """`error` keeps meaning "why this finally failed"; a consumer reading it must not
    see a failure while the message is still on its way."""
    async def body():
        mid = await queries.create_message("app1", "+79990000001", "hi")
        await queries.begin_message_attempt(mid)
        await queries.schedule_message_retry(mid, 30, "no response from modem (timeout)")
        return await _row(mid)

    row = _with_db(body)
    assert row["status"] == "pending"
    assert row["error"] is None
    assert row["last_attempt_error"] == "no response from modem (timeout)"
    assert row["attempts"] == 1             # scheduling does not count an attempt
    assert row["next_attempt_at"] is not None


def test_a_freshly_accepted_message_is_not_claimed_by_the_scheduler():
    """It is already in the in-memory queue; claiming it would send it twice."""
    async def body():
        await queries.create_message("app1", "+79990000001", "hi")
        return await queries.due_pending_messages(DEADLINE)

    assert _with_db(body) == []


def test_a_message_stranded_by_a_restart_is_claimed_once_it_is_due():
    async def body():
        mid = await queries.create_message("app1", "+79990000001", "hi")
        await _age(mid, 120)
        rows = await queries.due_pending_messages(DEADLINE)
        return mid, [dict(r) for r in rows]

    mid, rows = _with_db(body)
    assert [r["id"] for r in rows] == [mid]
    assert rows[0]["phone"] == "+79990000001"
    assert rows[0]["text"] == "hi"
    assert rows[0]["app_id"] == "app1"


def test_a_message_older_than_the_deadline_is_never_resurrected():
    """A payment link sent out days late is worse than one never sent."""
    async def body():
        mid = await queries.create_message("app1", "+79990000001", "hi")
        await _age(mid, DEADLINE + 60)
        return await queries.due_pending_messages(DEADLINE)

    assert _with_db(body) == []


def test_one_tick_cannot_stuff_the_queue():
    async def body():
        for i in range(8):
            mid = await queries.create_message("app1", f"+7999000000{i}", "hi")
            await _age(mid, 120)
        return await queries.due_pending_messages(DEADLINE, limit=3)

    assert len(_with_db(body)) == 3


def test_a_finished_message_is_never_claimed():
    async def body():
        sent = await queries.create_message("app1", "+79990000001", "one")
        failed = await queries.create_message("app1", "+79990000002", "two")
        await _age(sent, 120)
        await _age(failed, 120)
        await queries.set_message_sent(sent, 10)
        await queries.set_message_failed(failed, "+CMS ERROR 1 (unassigned number)")
        return await queries.due_pending_messages(DEADLINE)

    assert _with_db(body) == []


def test_an_overlong_pending_message_is_swept_up():
    """Nothing else looks at `pending`, so without this a message whose attempt died
    mid-flight would sit there forever and its app would never see a terminal status."""
    async def body():
        fresh = await queries.create_message("app1", "+79990000001", "fresh")
        stuck = await queries.create_message("app1", "+79990000002", "stuck")
        await queries.begin_message_attempt(stuck)      # died mid-send: no schedule
        await _age(stuck, DEADLINE + 60)
        rows = await queries.stale_pending_messages(DEADLINE)
        return fresh, stuck, [dict(r) for r in rows]

    fresh, stuck, rows = _with_db(body)
    assert [r["id"] for r in rows] == [stuck]
    assert fresh not in [r["id"] for r in rows]
