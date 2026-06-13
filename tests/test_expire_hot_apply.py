# tests/test_expire_hot_apply.py
import asyncio

from app.db.connection import init_db, close_db
from app.db.migrate import run_migrations
from app.db import queries
from app.settings_store import store


def test_expire_uses_current_store_value():
    async def run():
        await init_db(":memory:")
        await run_migrations()
        await store.load()
        db = await queries.get_db()
        await db.execute("INSERT OR IGNORE INTO apps (id, token) VALUES ('admin','t')")
        mid = await queries.create_message("admin", "+79995550011", "x")
        await db.execute(
            "UPDATE messages SET status='sent', sent_at=datetime('now','-100 seconds') WHERE id=?",
            (mid,),
        )
        await db.commit()

        await store.set_many({"delivery_timeout_seconds": "300"})
        await queries.expire_stale_messages(store.delivery_timeout_seconds)
        row = await queries.get_message(mid, "admin")
        assert row["status"] == "sent"

        await store.set_many({"delivery_timeout_seconds": "60"})
        await queries.expire_stale_messages(store.delivery_timeout_seconds)
        row = await queries.get_message(mid, "admin")
        assert row["status"] == "expired"

    try:
        asyncio.run(run())
    finally:
        asyncio.run(close_db())
