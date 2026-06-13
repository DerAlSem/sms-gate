import asyncio
import base64

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.connection import init_db, close_db
from app.db.migrate import run_migrations
from app.admin.router import router

_AUTH = {"Authorization": "Basic " + base64.b64encode(b"admin:change-me").decode()}


class _DummyModem:
    async def enqueue(self, *a, **k):
        pass


def _client():
    app = FastAPI()
    app.include_router(router)
    app.state.modem = _DummyModem()
    return TestClient(app)


def _db():
    async def run():
        await init_db(":memory:")
        await run_migrations()
    asyncio.run(run())


def test_reply_to_invalid_phone_returns_422():
    _db()
    try:
        r = _client().post("/admin/dialogs/not-a-phone/reply",
                           data={"text": "hello"}, headers=_AUTH,
                           follow_redirects=False)
        assert r.status_code == 422
    finally:
        asyncio.run(close_db())


def test_reply_accepts_national_format_and_normalizes():
    # lenient mode: a bare national RU number (rejected by the old +79… regex) is
    # accepted, normalized to E.164, and the reply redirects to the normalized dialog.
    _db()
    try:
        r = _client().post("/admin/dialogs/89991234567/reply",
                           data={"text": "hi"}, headers=_AUTH,
                           follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/admin/dialogs/+79991234567"
    finally:
        asyncio.run(close_db())
