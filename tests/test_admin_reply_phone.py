import asyncio
import base64

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.connection import init_db, close_db
from app.db.migrate import run_migrations
from app.db import queries
from app.admin.router import router

_AUTH = {"Authorization": "Basic " + base64.b64encode(b"admin:change-me").decode()}


class _RecordingModem:
    def __init__(self):
        self.sent = []

    async def enqueue(self, message_id, phone, text, app_id):
        self.sent.append((phone, text, app_id))


def _client(modem=None):
    app = FastAPI()
    app.include_router(router)
    app.state.modem = modem or _RecordingModem()
    return TestClient(app)


def _db():
    async def run():
        await init_db(":memory:")
        await run_migrations()
    asyncio.run(run())


def test_reply_to_invalid_phone_returns_422():
    _db()
    try:
        r = _client().post("/admin/messages/reply",
                           data={"to": "not-a-phone", "text": "hello"}, headers=_AUTH,
                           follow_redirects=False)
        assert r.status_code == 422
    finally:
        asyncio.run(close_db())


def test_reply_accepts_national_format_and_normalizes():
    # lenient mode: a bare national RU number (rejected by the old +79… regex) is
    # accepted and normalized to E.164 before it reaches the modem.
    _db()
    try:
        modem = _RecordingModem()
        r = _client(modem).post("/admin/messages/reply",
                                data={"to": "89991234567", "text": "hi"}, headers=_AUTH,
                                follow_redirects=False)
        assert r.status_code == 303
        assert modem.sent == [("+79991234567", "hi", "admin")]
    finally:
        asyncio.run(close_db())


def test_reply_returns_to_the_view_it_was_sent_from():
    """The conversation the operator was reading stays open, on the same page of the
    same filtered, period-bounded table."""
    _db()
    try:
        r = _client().post(
            "/admin/messages/reply",
            data={"to": "+79991234567", "text": "hi", "period": "7d", "page": "2",
                  "phone": "+79991234567", "status": "", "direction": "",
                  "open": "in-5"},
            headers=_AUTH, follow_redirects=False,
        )
        assert r.status_code == 303
        location = r.headers["location"]
        assert location.startswith("/admin/messages?")
        assert "period=7d" in location
        assert "page=2" in location
        assert "open=in-5" in location
        # a `+` in a query string decodes to a space, so it has to arrive encoded
        assert "phone=%2B79991234567" in location
    finally:
        asyncio.run(close_db())


def test_reply_to_a_blacklisted_number_is_refused():
    _db()
    try:
        asyncio.run(queries.block_phone("+79991234567"))
        r = _client().post("/admin/messages/reply",
                           data={"to": "+79991234567", "text": "hi"}, headers=_AUTH,
                           follow_redirects=False)
        assert r.status_code == 422
    finally:
        asyncio.run(close_db())
