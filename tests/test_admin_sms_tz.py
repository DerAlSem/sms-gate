import asyncio
import base64

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.connection import init_db, close_db
from app.db.migrate import run_migrations
from app.db import queries
from app.admin.router import router

_AUTH = {"Authorization": "Basic " + base64.b64encode(b"admin:change-me").decode()}


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _seed():
    """One outbound and one inbound message, both stamped in UTC."""
    async def setup():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("gm", "tok-gm")
        mid = await queries.create_message("gm", "+79995550011", "hi")
        db = await queries.get_db()
        await db.execute(
            "UPDATE messages SET created_at = '2026-07-20 14:21:17' WHERE id = ?",
            (mid,),
        )
        await db.execute(
            "INSERT INTO inbound_messages (phone, text, received_at) "
            "VALUES ('+79995550011', 'reply', '2026-07-20 15:30:00')"
        )
        await db.commit()
        return mid
    return asyncio.run(setup())


def test_sms_table_shows_moscow_time_not_utc():
    _seed()
    try:
        html = _client().get("/admin/messages?period=all", headers=_AUTH).text
        assert "2026-07-20 17:21:17" in html      # UTC+3
        assert "2026-07-20 18:30:00" in html      # the inbound row too
        assert "2026-07-20 14:21:17" not in html
    finally:
        asyncio.run(close_db())


def test_expanded_conversation_shows_moscow_time_not_utc():
    mid = _seed()
    try:
        html = _client().get(
            f"/admin/messages?period=all&open=out-{mid}", headers=_AUTH
        ).text
        assert "2026-07-20 17:21:17" in html
        assert "2026-07-20 18:30:00" in html
        assert "2026-07-20 15:30:00" not in html
    finally:
        asyncio.run(close_db())
