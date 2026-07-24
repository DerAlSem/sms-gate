"""The resent_from migration: idempotent, and the column actually carries the link."""
import asyncio

from app.db import queries
from app.db.connection import close_db, get_db, init_db
from app.db.migrate import run_migrations


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


def test_migration_is_idempotent():
    """run_migrations runs on every start, and SQLite has no ADD COLUMN IF NOT EXISTS —
    a second run must not raise 'duplicate column'."""
    async def body():
        await run_migrations()          # second pass over the same DB
        await run_migrations()          # third, for good measure
        db = await get_db()
        async with db.execute("PRAGMA table_info(messages)") as cur:
            cols = {row[1] async for row in cur}
        return cols

    cols = _with_db(body)
    assert "resent_from" in cols


def test_api_message_has_null_resent_from():
    async def body():
        mid = await queries.create_message("app1", "+7985", "hi")
        ctx = await queries.get_message_delivery_context(mid)
        return ctx["resent_from"]

    assert _with_db(body) is None


def test_resent_message_persists_the_source_id():
    async def body():
        original = await queries.create_message("app1", "+7985", "hi")
        copy = await queries.create_message("app1", "+7985", "hi", resent_from=original)
        ctx = await queries.get_message_delivery_context(copy)
        return original, ctx["resent_from"]

    original, link = _with_db(body)
    assert link == original
