"""Delete, block and the origin guard, as reached from the conversation panel."""
import asyncio
import base64

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.connection import init_db, close_db
from app.db.migrate import run_migrations
from app.db import queries
from app.admin.router import router

_AUTH = {"Authorization": "Basic " + base64.b64encode(b"admin:change-me").decode()}
OLD = "2020-01-01 10:00:00"


class _RecordingModem:
    def __init__(self):
        self.sent = []

    async def enqueue(self, message_id, phone, text, app_id):
        self.sent.append((phone, text, app_id))


def _client():
    app = FastAPI()
    app.include_router(router)
    app.state.modem = _RecordingModem()
    return TestClient(app)


def _run(coro_fn):
    return asyncio.run(coro_fn())


def _seed():
    async def setup():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("gm", "tok-gm")
        db = await queries.get_db()
        cursor = await db.execute(
            "INSERT INTO messages (app_id, phone, text, status, created_at) "
            "VALUES ('gm', '+79995550011', 'old delivered', 'delivered', ?)",
            (OLD,),
        )
        deletable = cursor.lastrowid
        cursor = await db.execute(
            "INSERT INTO messages (app_id, phone, text, status, created_at) "
            "VALUES ('gm', '+79995550011', 'still going', 'sent', ?)",
            (OLD,),
        )
        in_flight = cursor.lastrowid
        cursor = await db.execute(
            "INSERT INTO inbound_messages (phone, text) VALUES ('+79995550011', 'hi there')"
        )
        await db.commit()
        return deletable, in_flight, cursor.lastrowid
    return _run(setup)


def _exists(table: str, row_id: int) -> bool:
    async def run():
        db = await queries.get_db()
        async with db.execute(f"SELECT 1 FROM {table} WHERE id = ?", (row_id,)) as c:
            return await c.fetchone() is not None
    return _run(run)


def test_deleting_an_eligible_message_returns_to_the_same_view():
    deletable, _, _ = _seed()
    try:
        r = _client().post(
            "/admin/messages/delete",
            data={"id": deletable, "row_direction": "out", "period": "7d",
                  "page": "2", "phone": "+79995550011", "status": "", "direction": "",
                  "open": "in-1"},
            headers=_AUTH, follow_redirects=False,
        )
        assert r.status_code == 303
        location = r.headers["location"]
        assert "period=7d" in location and "page=2" in location and "open=in-1" in location
        assert "phone=%2B79995550011" in location
        assert "error=" not in location
        assert _exists("messages", deletable) is False
    finally:
        _run(close_db)


def test_a_refused_deletion_says_why():
    _, in_flight, _ = _seed()
    try:
        r = _client().post(
            "/admin/messages/delete",
            data={"id": in_flight, "row_direction": "out"},
            headers=_AUTH, follow_redirects=False,
        )
        assert "error=not_terminal" in r.headers["location"]
        assert _exists("messages", in_flight) is True

        # and the reason reaches the operator as words, not as a code
        html = _client().get("/admin/messages?error=not_terminal", headers=_AUTH).text
        assert "delivery report" in html or "отчёт о доставке" in html
    finally:
        _run(close_db)


def test_deleting_an_inbound_message():
    _, _, inbound = _seed()
    try:
        r = _client().post(
            "/admin/messages/delete",
            data={"id": inbound, "row_direction": "in"},
            headers=_AUTH, follow_redirects=False,
        )
        assert "error=" not in r.headers["location"]
        assert _exists("inbound_messages", inbound) is False
    finally:
        _run(close_db)


def test_block_then_unblock_from_the_conversation():
    _seed()
    try:
        c = _client()
        c.post("/admin/messages/block",
               data={"to": "+79995550011", "action": "block"},
               headers=_AUTH, follow_redirects=False)
        assert _run(lambda: queries.is_phone_blocked("+79995550011")) is True

        c.post("/admin/messages/block",
               data={"to": "+79995550011", "action": "unblock"},
               headers=_AUTH, follow_redirects=False)
        assert _run(lambda: queries.is_phone_blocked("+79995550011")) is False
    finally:
        _run(close_db)


def test_blocking_a_non_number_is_refused():
    _seed()
    try:
        r = _client().post("/admin/messages/block",
                           data={"to": "Tinkoff", "action": "block"},
                           headers=_AUTH, follow_redirects=False)
        assert "error=not_dialable" in r.headers["location"]
    finally:
        _run(close_db)


def test_the_conversation_offers_unblocking_once_blocked():
    _, _, inbound = _seed()
    try:
        _run(lambda: queries.block_phone("+79995550011"))
        html = _client().get(f"/admin/messages?open=in-{inbound}", headers=_AUTH).text
        assert 'value="unblock"' in html
        assert 'value="block"' not in html
    finally:
        _run(close_db)


def test_a_cross_site_destructive_post_is_refused():
    """Basic auth carries no per-request token, so a browser attaches cached
    credentials to a cross-site form post."""
    deletable, _, _ = _seed()
    try:
        r = _client().post(
            "/admin/messages/delete",
            data={"id": deletable, "row_direction": "out"},
            headers={**_AUTH, "Origin": "https://evil.example", "Host": "gate.local"},
            follow_redirects=False,
        )
        assert r.status_code == 403
        assert _exists("messages", deletable) is True
    finally:
        _run(close_db)


def test_a_same_origin_destructive_post_goes_through():
    deletable, _, _ = _seed()
    try:
        r = _client().post(
            "/admin/messages/delete",
            data={"id": deletable, "row_direction": "out"},
            headers={**_AUTH, "Origin": "https://gate.local", "Host": "gate.local"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert _exists("messages", deletable) is False
    finally:
        _run(close_db)


def test_a_headerless_post_is_allowed():
    """curl and the tests carry neither header; the guard is against browsers."""
    deletable, _, _ = _seed()
    try:
        r = _client().post(
            "/admin/messages/delete",
            data={"id": deletable, "row_direction": "out"},
            headers=_AUTH, follow_redirects=False,
        )
        assert r.status_code == 303
    finally:
        _run(close_db)
