"""The merged two-direction listing behind the SMS view."""
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


async def _out(phone: str, text: str, created_at: str, status: str = "delivered") -> int:
    db = await queries.get_db()
    cursor = await db.execute(
        "INSERT INTO messages (app_id, phone, text, status, created_at) "
        "VALUES ('gm', ?, ?, ?, ?)",
        (phone, text, status, created_at),
    )
    await db.commit()
    return cursor.lastrowid


async def _in(phone: str, text: str, received_at: str) -> int:
    db = await queries.get_db()
    cursor = await db.execute(
        "INSERT INTO inbound_messages (phone, text, received_at) VALUES (?, ?, ?)",
        (phone, text, received_at),
    )
    await db.commit()
    return cursor.lastrowid


def test_both_directions_land_in_one_stream_ordered_by_time():
    """An inbound row with a lower id still sorts above an older outbound row —
    the stream is ordered by when the message happened, not by an id sequence."""

    async def run():
        await _out("+79995550011", "sent first", "2026-07-01 10:00:00")
        await _out("+79995550011", "sent second", "2026-07-01 11:00:00")
        await _in("+79995550011", "replied last", "2026-07-01 12:00:00")
        rows = await queries.list_thread_page("all", None, None, None, 50, 0)
        return [(r["direction"], r["text"]) for r in rows]

    assert _run(run) == [
        ("in", "replied last"),
        ("out", "sent second"),
        ("out", "sent first"),
    ]


def test_equal_timestamps_page_deterministically():
    """CURRENT_TIMESTAMP has one-second resolution, so ties are ordinary. Without a
    tie-break a row can appear on two pages or on neither."""

    async def run():
        for i in range(6):
            await _out("+79995550011", f"m{i}", "2026-07-01 10:00:00")
        for i in range(6):
            await _in("+79995550011", f"i{i}", "2026-07-01 10:00:00")
        first = await queries.list_thread_page("all", None, None, None, 5, 0)
        second = await queries.list_thread_page("all", None, None, None, 5, 5)
        third = await queries.list_thread_page("all", None, None, None, 5, 10)
        return [
            [(r["direction"], r["text"]) for r in page]
            for page in (first, second, third)
        ]

    pages = _run(run)
    seen = [row for page in pages for row in page]
    assert len(seen) == 12, "every row appears"
    assert len(set(seen)) == 12, "and none of them twice"


def test_period_bounds_both_directions():
    async def run():
        await _out("+79995550011", "old out", "2020-01-01 10:00:00")
        await _in("+79995550011", "old in", "2020-01-01 10:00:00")
        await _out("+79995550011", "fresh out", "2099-01-01 10:00:00")
        await _in("+79995550011", "fresh in", "2099-01-01 10:00:00")
        week = await queries.list_thread_page("7d", None, None, None, 50, 0)
        everything = await queries.list_thread_page("all", None, None, None, 50, 0)
        return (
            sorted(r["text"] for r in week),
            sorted(r["text"] for r in everything),
        )

    week, everything = _run(run)
    assert week == ["fresh in", "fresh out"]
    assert everything == ["fresh in", "fresh out", "old in", "old out"]


def test_count_reflects_the_filtered_set_not_the_table():
    async def run():
        await _out("+79995550011", "a", "2099-01-01 10:00:00")
        await _out("+79995550022", "b", "2099-01-01 10:00:00")
        await _in("+79995550011", "c", "2099-01-01 10:00:00")
        return (
            await queries.count_thread_page("all", None, None, None),
            await queries.count_thread_page("all", "550011", None, None),
        )

    total, filtered = _run(run)
    assert total == 3
    assert filtered == 2


def test_direction_filter_narrows_to_one_direction():
    async def run():
        await _out("+79995550011", "out", "2099-01-01 10:00:00")
        await _in("+79995550011", "in", "2099-01-01 10:00:00")
        inbound = await queries.list_thread_page("all", None, None, "in", 50, 0)
        outbound = await queries.list_thread_page("all", None, None, "out", 50, 0)
        return (
            [r["text"] for r in inbound],
            [r["text"] for r in outbound],
        )

    inbound, outbound = _run(run)
    assert inbound == ["in"]
    assert outbound == ["out"]


def test_a_status_filter_forces_the_outbound_direction():
    """"delivered inbound" has no meaning; the status decides, and inbound drops out."""

    async def run():
        await _out("+79995550011", "delivered one", "2099-01-01 10:00:00", "delivered")
        await _out("+79995550011", "failed one", "2099-01-01 10:00:00", "failed")
        await _in("+79995550011", "arrived", "2099-01-01 10:00:00")
        rows = await queries.list_thread_page("all", None, "delivered", "in", 50, 0)
        return [r["text"] for r in rows]

    assert _run(run) == ["delivered one"]


def test_normalize_filters_is_one_directional():
    assert queries.normalize_filters("delivered", "in") == ("delivered", "out")
    assert queries.normalize_filters("", "in") == ("", "in")
    assert queries.normalize_filters(None, None) == ("", "")
    assert queries.normalize_filters("", "nonsense") == ("", "")


def test_get_thread_row_resolves_the_counterparty_per_direction():
    """Ids collide across the two tables, so the key carries the direction."""

    async def run():
        out_id = await _out("+79995550011", "out", "2099-01-01 10:00:00")
        in_id = await _in("+79995550022", "in", "2099-01-01 10:00:00")
        return (
            out_id,
            in_id,
            (await queries.get_thread_row("out", out_id))["phone"],
            (await queries.get_thread_row("in", in_id))["phone"],
            await queries.get_thread_row("out", 9999),
        )

    out_id, in_id, out_phone, in_phone, missing = _run(run)
    assert out_id == in_id == 1, "both sequences start at 1 — the collision is real"
    assert out_phone == "+79995550011"
    assert in_phone == "+79995550022"
    assert missing is None


def test_dialog_is_capped_and_reads_oldest_first():
    async def run():
        for i in range(120):
            await _out("+79995550011", f"m{i:03d}", f"2026-07-01 10:{i // 60:02d}:{i % 60:02d}")
        rows = await queries.dialog_for("+79995550011", limit=100)
        return (
            [r["text"] for r in rows],
            await queries.dialog_total("+79995550011"),
        )

    texts, total = _run(run)
    assert total == 120
    assert len(texts) == 100
    assert texts[0] == "m020", "the newest 100 are kept"
    assert texts[-1] == "m119"
    assert texts == sorted(texts), "and are shown oldest first"
