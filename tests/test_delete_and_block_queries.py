"""Deletion refuses while anything still depends on the message; blocking keeps the
failure history."""
import asyncio

from app.db.connection import init_db, close_db
from app.db.migrate import run_migrations
from app.db import queries

OLD = "2020-01-01 10:00:00"        # comfortably past DELETE_MIN_AGE
FRESH = "2099-01-01 10:00:00"      # comfortably inside it


def _run(coro_fn):
    async def wrapper():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("gm", "tok-gm")
        try:
            return await coro_fn()
        finally:
            await close_db()

    return asyncio.run(wrapper())


async def _msg(status: str, created_at: str = OLD, resent_from: int | None = None) -> int:
    db = await queries.get_db()
    cursor = await db.execute(
        "INSERT INTO messages (app_id, phone, text, status, created_at, resent_from) "
        "VALUES ('gm', '+79995550011', 'x', ?, ?, ?)",
        (status, created_at, resent_from),
    )
    await db.commit()
    return cursor.lastrowid


async def _exists(message_id: int) -> bool:
    db = await queries.get_db()
    async with db.execute("SELECT 1 FROM messages WHERE id = ?", (message_id,)) as c:
        return await c.fetchone() is not None


async def _part_count(message_id: int) -> int:
    db = await queries.get_db()
    async with db.execute(
        "SELECT COUNT(*) FROM message_parts WHERE message_id = ?", (message_id,)
    ) as c:
        return int((await c.fetchone())[0])


def test_in_flight_and_expired_messages_are_not_deletable():
    """`expired` is not terminal: a late report can still correct it to delivered."""

    async def run():
        results = {}
        for status in ("pending", "sent", "expired"):
            mid = await _msg(status)
            results[status] = (await queries.delete_outbound(mid), await _exists(mid))
        return results

    results = _run(run)
    assert results["pending"] == ("not_terminal", True)
    assert results["sent"] == ("not_terminal", True)
    assert results["expired"] == ("not_terminal", True)


def test_a_fresh_message_is_not_deletable():
    """`GET /sms/{id}` is how an app recovers a dropped webhook; a 404 too soon
    destroys that answer."""

    async def run():
        mid = await _msg("delivered", created_at=FRESH)
        return await queries.delete_outbound(mid), await _exists(mid)

    assert _run(run) == ("too_young", True)


def test_an_eligible_message_is_deleted_with_its_parts():
    async def run():
        mid = await _msg("failed")
        db = await queries.get_db()
        await queries.add_message_part(mid, 101, 1, 2)
        await queries.add_message_part(mid, 102, 2, 2)
        await db.commit()
        before = await _part_count(mid)
        reason = await queries.delete_outbound(mid)
        async with db.execute("SELECT COUNT(*) FROM message_parts") as c:
            orphans = int((await c.fetchone())[0])
        return before, reason, await _exists(mid), orphans

    before, reason, exists, orphans = _run(run)
    assert before == 2
    assert reason is None
    assert exists is False
    assert orphans == 0, "no part record outlives its message"


def test_a_resend_still_in_flight_blocks_the_deletion():
    """delivery-dispatch requires resent_from in *every* notification for the copy,
    and that column is read at notification time."""

    async def run():
        source = await _msg("failed")
        copy = await _msg("sent", resent_from=source)
        reason = await queries.delete_outbound(source)
        db = await queries.get_db()
        async with db.execute(
            "SELECT resent_from FROM messages WHERE id = ?", (copy,)
        ) as c:
            still_linked = (await c.fetchone())["resent_from"]
        return reason, await _exists(source), still_linked

    reason, exists, still_linked = _run(run)
    assert reason == "resend_in_flight"
    assert exists is True
    assert still_linked is not None, "the copy keeps its attribution"


def test_deletion_is_allowed_once_the_resend_is_finished():
    async def run():
        source = await _msg("failed")
        copy = await _msg("delivered", resent_from=source)
        reason = await queries.delete_outbound(source)
        db = await queries.get_db()
        async with db.execute(
            "SELECT resent_from FROM messages WHERE id = ?", (copy,)
        ) as c:
            link = (await c.fetchone())["resent_from"]
        return reason, await _exists(source), await _exists(copy), link

    reason, source_gone, copy_alive, link = _run(run)
    assert reason is None
    assert source_gone is False
    assert copy_alive is True, "the copy survives its source"
    assert link is None


def test_a_refused_deletion_changes_nothing():
    """The gate lives inside the DELETE, so a refusal must not have eaten the parts
    on the way there."""

    async def run():
        mid = await _msg("sent")
        await queries.add_message_part(mid, 201, 1, 1)
        reason = await queries.delete_outbound(mid)
        return reason, await _exists(mid), await _part_count(mid)

    reason, exists, parts = _run(run)
    assert reason == "not_terminal"
    assert exists is True
    assert parts == 1, "the part record survives the refusal"


def test_telegram_notification_refs_are_untouched():
    """notify_refs.message_id is a Telegram message id, not one of ours — deleting by
    our id there would remove an unrelated record."""

    async def run():
        mid = await _msg("delivered")
        await queries.add_notify_ref(mid, "+79995550099")   # same integer, other namespace
        await queries.delete_outbound(mid)
        return await queries.find_notify_ref(mid)

    assert _run(run) == "+79995550099"


def test_missing_message_reports_not_found():
    async def run():
        return await queries.delete_outbound(4242)

    assert _run(run) == "not_found"


def test_blocking_leaves_the_failure_counter_alone():
    async def run():
        await queries.record_permanent_fail("+79995550011", "boom", threshold=99)
        await queries.record_permanent_fail("+79995550011", "boom again", threshold=99)
        await queries.block_phone("+79995550011")
        db = await queries.get_db()
        async with db.execute(
            "SELECT fail_count, last_error FROM bad_numbers WHERE phone = ?",
            ("+79995550011",),
        ) as c:
            row = await c.fetchone()
        return (
            await queries.is_phone_blocked("+79995550011"),
            row["fail_count"],
            row["last_error"],
        )

    blocked, fail_count, last_error = _run(run)
    assert blocked is True
    assert fail_count == 2, "a manual block is not a failure"
    assert last_error == "boom again"


def test_unblocking_preserves_the_history_it_used_to_delete():
    """Unblocking is now one click inside any conversation. Deleting the row would
    hand a number that earned its threshold a fresh budget of failures."""

    async def run():
        await queries.record_permanent_fail("+79995550011", "boom", threshold=99)
        await queries.block_phone("+79995550011")
        await queries.unblock_phone("+79995550011")
        db = await queries.get_db()
        async with db.execute(
            "SELECT fail_count, last_error, blocked_at FROM bad_numbers WHERE phone = ?",
            ("+79995550011",),
        ) as c:
            row = await c.fetchone()
        return (
            await queries.is_phone_blocked("+79995550011"),
            row["fail_count"],
            row["last_error"],
            row["blocked_at"],
        )

    blocked, fail_count, last_error, blocked_at = _run(run)
    assert blocked is False
    assert blocked_at is None
    assert fail_count == 1, "the counter survives the unblock"
    assert last_error == "boom"


def test_blocking_an_unknown_number_creates_the_row():
    async def run():
        await queries.block_phone("+79995550077")
        return await queries.is_phone_blocked("+79995550077")

    assert _run(run) is True
