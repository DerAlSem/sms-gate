import asyncio

from app.db.connection import init_db, close_db
from app.db.migrate import run_migrations
from app.db import queries


async def _fresh_db():
    await init_db(":memory:")
    await run_migrations()


def test_add_and_find_notify_ref():
    async def run():
        await _fresh_db()
        try:
            await queries.add_notify_ref(500, "+79991234567")
            return await queries.find_notify_ref(500)
        finally:
            await close_db()
    assert asyncio.run(run()) == "+79991234567"


def test_find_notify_ref_unknown_is_none():
    async def run():
        await _fresh_db()
        try:
            return await queries.find_notify_ref(404)
        finally:
            await close_db()
    assert asyncio.run(run()) is None


def test_telegram_app_seeded():
    async def run():
        await _fresh_db()
        try:
            return await queries.create_message("telegram", "+79991234567", "hi")
        finally:
            await close_db()
    assert asyncio.run(run()) >= 1
