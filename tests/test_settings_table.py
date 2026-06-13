# tests/test_settings_table.py
import asyncio

from app.db.connection import init_db, close_db
from app.db.migrate import run_migrations
from app.db import queries


def test_settings_table_exists_and_is_writable():
    async def run():
        await init_db(":memory:")
        await run_migrations()
        db = await queries.get_db()
        await db.execute(
            "INSERT INTO settings (key, value) VALUES ('k', 'v')"
        )
        await db.commit()
        async with db.execute("SELECT value FROM settings WHERE key='k'") as cur:
            row = await cur.fetchone()
        assert row["value"] == "v"

    try:
        asyncio.run(run())
    finally:
        asyncio.run(close_db())
