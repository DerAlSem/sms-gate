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


def _db():
    async def run():
        await init_db(":memory:")
        await run_migrations()
    asyncio.run(run())


def test_create_and_list_app():
    _db()
    try:
        c = _client()
        r = c.post("/admin/apps/create", data={"id": "newbot", "description": "x"},
                   headers=_AUTH, follow_redirects=False)
        assert r.status_code == 200
        assert "tok_" in r.text                 # token shown once in body, not a URL
        ids = [a["id"] for a in asyncio.run(queries.list_apps())]
        assert "newbot" in ids
    finally:
        asyncio.run(close_db())


def test_create_does_not_put_token_in_a_redirect():
    _db()
    try:
        c = _client()
        r = c.post("/admin/apps/create", data={"id": "b2", "description": ""},
                   headers=_AUTH, follow_redirects=False)
        assert "token=" not in r.headers.get("location", "")   # no token in any redirect URL
    finally:
        asyncio.run(close_db())


def test_delete_blocked_when_app_has_messages():
    async def setup():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("busybot", "tok", "")
        await queries.create_message("busybot", "+79995550011", "x")
    asyncio.run(setup())
    try:
        c = _client()
        c.post("/admin/apps/delete", data={"id": "busybot"}, headers=_AUTH, follow_redirects=False)
        ids = [a["id"] for a in asyncio.run(queries.list_apps())]
        assert "busybot" in ids   # guard: not deleted
    finally:
        asyncio.run(close_db())


def test_create_duplicate_id_does_not_500():
    async def setup():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("dup", "tok-dup", "")
    asyncio.run(setup())
    try:
        c = _client()
        r = c.post("/admin/apps/create", data={"id": "dup", "description": ""},
                   headers=_AUTH, follow_redirects=False)
        assert r.status_code == 303
        assert "error=exists" in r.headers.get("location", "")
    finally:
        asyncio.run(close_db())


def test_apps_page_translates():
    _db()
    try:
        c = _client()
        ru = c.get("/admin/apps", headers=_AUTH)
        assert "Приложения-клиенты" in ru.text
        en = c.get("/admin/apps", headers={**_AUTH, "Cookie": "lang=en"})
        assert "Client apps" in en.text
        assert "Приложения-клиенты" not in en.text
    finally:
        asyncio.run(close_db())
