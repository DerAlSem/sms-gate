# tests/test_stats_day.py
import asyncio

from app.db.connection import init_db, close_db
from app.db.migrate import run_migrations
from app.db import queries


def test_daily_counts_buckets_by_msk_day():
    async def run():
        await init_db(":memory:")
        await run_migrations()
        db = await queries.get_db()
        await db.execute("INSERT OR IGNORE INTO apps (id, token) VALUES ('admin', 'tok')")
        # 23:30 UTC on Jun 2 is 02:30 MSK on Jun 3 -> must bucket into Jun 3
        await db.execute(
            "INSERT INTO messages (app_id, phone, text, status, created_at) "
            "VALUES ('admin', '+79995550011', 'x', 'delivered', '2026-06-02 23:30:00')"
        )
        await db.commit()
        try:
            rows = await queries.daily_counts(days=3650)
            return [(r["day"], r["status"], r["n"]) for r in rows]
        finally:
            await close_db()
    assert asyncio.run(run()) == [("2026-06-03", "delivered", 1)]
