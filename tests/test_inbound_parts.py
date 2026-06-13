import asyncio

from app.db.connection import init_db, close_db
from app.db.migrate import run_migrations
from app.db import queries


async def _fresh_db():
    await init_db(":memory:")
    await run_migrations()


def test_save_and_get_parts_ordered_by_seq():
    async def run():
        await _fresh_db()
        try:
            await queries.save_inbound_part("+7999", 140, 2, 2, "world")
            await queries.save_inbound_part("+7999", 140, 2, 1, "hello ")
            rows = await queries.get_inbound_parts("+7999", 140, 2)
            return [(r["seq"], r["text"]) for r in rows]
        finally:
            await close_db()
    assert asyncio.run(run()) == [(1, "hello "), (2, "world")]


def test_duplicate_part_ignored():
    async def run():
        await _fresh_db()
        try:
            await queries.save_inbound_part("+7999", 140, 2, 1, "first")
            await queries.save_inbound_part("+7999", 140, 2, 1, "dup")
            rows = await queries.get_inbound_parts("+7999", 140, 2)
            return [(r["seq"], r["text"]) for r in rows]
        finally:
            await close_db()
    assert asyncio.run(run()) == [(1, "first")]


def test_delete_parts():
    async def run():
        await _fresh_db()
        try:
            await queries.save_inbound_part("+7999", 140, 2, 1, "a")
            await queries.save_inbound_part("+7888", 140, 2, 1, "other")
            first_delete = await queries.delete_inbound_parts("+7999", 140, 2)
            second_delete = await queries.delete_inbound_parts("+7999", 140, 2)
            kept = await queries.get_inbound_parts("+7888", 140, 2)
            gone = await queries.get_inbound_parts("+7999", 140, 2)
            return first_delete, second_delete, len(kept), len(gone)
        finally:
            await close_db()
    assert asyncio.run(run()) == (1, 0, 1, 0)


def test_stale_part_groups():
    async def run():
        await _fresh_db()
        try:
            await queries.save_inbound_part("+7999", 140, 2, 1, "old")
            await queries.save_inbound_part("+7888", 7, 3, 1, "fresh")
            db = await queries.get_db()
            await db.execute(
                "UPDATE inbound_parts SET received_at = datetime('now', '-600 seconds') "
                "WHERE phone = '+7999'"
            )
            await db.commit()
            rows = await queries.stale_part_groups(300)
            return [(r["phone"], r["ref"], r["total"]) for r in rows]
        finally:
            await close_db()
    assert asyncio.run(run()) == [("+7999", 140, 2)]


def test_group_with_recent_part_is_not_stale():
    async def run():
        await _fresh_db()
        try:
            await queries.save_inbound_part("+7999", 9, 2, 1, "old part")
            db = await queries.get_db()
            await db.execute(
                "UPDATE inbound_parts SET received_at = datetime('now', '-600 seconds')"
            )
            await db.commit()
            await queries.save_inbound_part("+7999", 9, 2, 2, "fresh part")
            rows = await queries.stale_part_groups(300)
            return len(rows)
        finally:
            await close_db()
    assert asyncio.run(run()) == 0
