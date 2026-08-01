"""Statistics count the selected period, key off creation time, and bucket to fit."""
import asyncio

from app.db.connection import init_db, close_db
from app.db.migrate import run_migrations
from app.db import queries


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


async def _out(status: str, created_at: str, delivered_at: str | None = None) -> None:
    db = await queries.get_db()
    await db.execute(
        "INSERT INTO messages (app_id, phone, text, status, created_at, delivered_at) "
        "VALUES ('gm', '+79995550011', 'x', ?, ?, ?)",
        (status, created_at, delivered_at),
    )
    await db.commit()


async def _in(received_at: str) -> None:
    db = await queries.get_db()
    await db.execute(
        "INSERT INTO inbound_messages (phone, text, received_at) VALUES ('+79995550011', 'x', ?)",
        (received_at,),
    )
    await db.commit()


def test_counts_are_bounded_by_the_period():
    async def run():
        await _out("delivered", "2020-01-01 10:00:00")
        await _out("delivered", "2099-01-01 10:00:00")
        await _out("failed", "2099-01-01 10:00:00")
        return (
            await queries.status_counts("7d"),
            await queries.status_counts("all"),
        )

    week, everything = _run(run)
    assert week == {"delivered": 1, "failed": 1}
    assert everything == {"delivered": 2, "failed": 1}


def test_membership_is_by_creation_not_by_delivery():
    """Status is a present-tense fact; a message enters a window by when it was
    created, so the cards and the table agree on which messages exist."""

    async def run():
        await _out("delivered", "2020-01-01 10:00:00", delivered_at="2099-01-01 10:00:00")
        return await queries.status_counts("7d")

    assert _run(run) == {}


def test_inbound_is_counted_for_the_period():
    """With the Inbound tab gone, nothing else reports how much arrived."""

    async def run():
        await _in("2020-01-01 10:00:00")
        await _in("2099-01-01 10:00:00")
        await _in("2099-01-02 10:00:00")
        return await queries.inbound_count("7d"), await queries.inbound_count("all")

    assert _run(run) == (2, 3)


def test_buckets_are_sized_to_the_period():
    async def run():
        for day in ("2099-01-01", "2099-01-02", "2099-02-01"):
            await _out("delivered", f"{day} 10:00:00")
        yearly = await queries.period_buckets("1y")
        daily = await queries.period_buckets("30d")
        return (
            sorted({r["bucket"] for r in yearly}),
            sorted({r["bucket"] for r in daily}),
        )

    yearly, daily = _run(run)
    assert yearly == ["2099-01", "2099-02"], "one row per month over a year"
    assert daily == ["2099-01-01", "2099-01-02", "2099-02-01"], "one row per day over a month"


def test_hourly_buckets_over_a_day():
    async def run():
        await _out("delivered", "2099-01-01 10:15:00")
        await _out("delivered", "2099-01-01 10:45:00")
        await _out("failed", "2099-01-01 11:05:00")
        rows = await queries.period_buckets("24h")
        return sorted((r["bucket"], r["status"], r["n"]) for r in rows)

    assert _run(run) == [
        ("2099-01-01 13:00", "delivered", 2),   # 10:xx UTC is 13:xx MSK
        ("2099-01-01 14:00", "failed", 1),
    ]


def test_buckets_fall_on_msk_days_not_utc_days():
    """23:30 UTC on Jan 1 is 02:30 MSK on Jan 2 — it belongs to the MSK day."""

    async def run():
        await _out("delivered", "2099-01-01 23:30:00")
        rows = await queries.period_buckets("30d")
        return [(r["bucket"], r["n"]) for r in rows]

    assert _run(run) == [("2099-01-02", 1)]
