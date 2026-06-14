import asyncio

from app.db.connection import init_db, close_db
from app.db.migrate import run_migrations
from app.db import queries


async def _fresh_db():
    await init_db(":memory:")
    await run_migrations()
    await queries.create_app("app1", "tok1", "test")


def test_add_part_and_find_by_ref():
    async def run():
        await _fresh_db()
        try:
            mid = await queries.create_message("app1", "+7999", "hi")
            await queries.set_message_sent(mid, 100)
            await queries.add_message_part(mid, 100, 1, 2)
            row = await queries.find_message_by_part_ref(100)
            return (row["message_id"], row["phone"]) if row else None
        finally:
            await close_db()
    assert asyncio.run(run()) == (1, "+7999")


def test_all_delivered_only_when_every_part_delivered():
    async def run():
        await _fresh_db()
        try:
            mid = await queries.create_message("app1", "+7999", "hi")
            await queries.set_message_sent(mid, 100)
            await queries.add_message_part(mid, 100, 1, 2)
            await queries.add_message_part(mid, 101, 2, 2)
            await queries.set_part_delivered(100)
            before = await queries.message_parts_all_delivered(mid)
            await queries.set_part_delivered(101)
            after = await queries.message_parts_all_delivered(mid)
            return before, after
        finally:
            await close_db()
    assert asyncio.run(run()) == (False, True)


def test_find_by_part_ref_skips_finalized_message():
    async def run():
        await _fresh_db()
        try:
            mid = await queries.create_message("app1", "+7999", "hi")
            await queries.set_message_sent(mid, 100)
            await queries.add_message_part(mid, 100, 1, 1)
            await queries.set_message_delivered(mid)
            return await queries.find_message_by_part_ref(100)
        finally:
            await close_db()
    assert asyncio.run(run()) is None
