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
        self.sent.append((message_id, phone, text, app_id))


def _client(modem=None):
    app = FastAPI()
    app.include_router(router)
    app.state.modem = modem or _RecordingModem()
    return TestClient(app)


def _run(coro_fn):
    return asyncio.run(coro_fn())


def _seed_failed(status="failed", text="hi"):
    async def run():
        await init_db(":memory:")
        await run_migrations()
        # a real application (not the seeded 'admin') — resend must keep the origin app_id
        await queries.create_app("gm", "tok-gm")
        mid = await queries.create_message("gm", "+79995550011", text)
        if status == "failed":
            await queries.set_message_failed(mid, "no response from modem (timeout)")
        return mid
    return _run(run)


def test_resend_failed_creates_new_pending_and_enqueues():
    mid = _seed_failed()
    try:
        modem = _RecordingModem()
        r = _client(modem).post(f"/admin/messages/{mid}/resend",
                                data={"page": "1", "status": "", "phone": ""},
                                headers=_AUTH, follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/admin/messages"

        # a NEW row is queued; the failed original keeps its error as history
        assert len(modem.sent) == 1
        new_id, phone, text, app_id = modem.sent[0]
        assert new_id != mid
        assert (phone, text, app_id) == ("+79995550011", "hi", "gm")

        async def check():
            new_row = await queries.get_message_any(new_id)
            old_row = await queries.get_message_any(mid)
            return new_row["status"], old_row["status"]
        assert _run(check) == ("pending", "failed")
    finally:
        _run(close_db)


def test_resend_preserves_list_filters_in_redirect():
    mid = _seed_failed()
    try:
        r = _client().post(f"/admin/messages/{mid}/resend",
                           data={"page": "3", "status": "failed", "phone": "+7999"},
                           headers=_AUTH, follow_redirects=False)
        assert r.status_code == 303
        loc = r.headers["location"]
        assert loc.startswith("/admin/messages?")
        assert "status=failed" in loc and "page=3" in loc
    finally:
        _run(close_db)


def test_resend_rejects_non_failed_message():
    mid = _seed_failed(status="pending")
    try:
        modem = _RecordingModem()
        r = _client(modem).post(f"/admin/messages/{mid}/resend",
                                data={}, headers=_AUTH, follow_redirects=False)
        assert r.status_code == 422
        assert modem.sent == []
    finally:
        _run(close_db)


def test_resend_unknown_id_returns_404():
    _seed_failed()
    try:
        r = _client().post("/admin/messages/999999/resend",
                           data={}, headers=_AUTH, follow_redirects=False)
        assert r.status_code == 404
    finally:
        _run(close_db)


def test_resend_button_shown_only_for_failed_rows():
    mid = _seed_failed()
    try:
        async def add_delivered():
            ok = await queries.create_message("gm", "+79995550022", "ok")
            await queries.set_message_delivered(ok)
        _run(add_delivered)

        html = _client().get("/admin/messages", headers=_AUTH).text
        assert f"/admin/messages/{mid}/resend" in html
        assert "+79995550022" in html            # the delivered row IS rendered…
        assert html.count("/resend") == 1        # …but carries no resend form
    finally:
        _run(close_db)
