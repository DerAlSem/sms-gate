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


def test_a_created_app_is_shown_as_not_allowed_to_spend():
    """The entitlement is off for a token created a moment ago, and the page says so.

    Asserted on the rendered page rather than only on the column, because the switch
    exists to be operated: an entitlement nobody can see is one nobody reviews.
    """
    _db()
    try:
        c = _client()
        c.post("/admin/apps/create", data={"id": "fresh", "description": ""},
               headers=_AUTH, follow_redirects=False)
        assert asyncio.run(queries.app_may_spend("fresh")) is False
        page = c.get("/admin/apps", headers={**_AUTH, "Cookie": "lang=en"}).text
        assert "May spend" in page
        assert "Allow spending" in page, \
            "an application that cannot spend must offer the grant, not the revocation"
    finally:
        asyncio.run(close_db())


def test_the_entitlement_can_be_granted_and_revoked_from_the_page():
    async def setup():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("payer", "tok-payer", "")
    asyncio.run(setup())
    try:
        c = _client()
        c.post("/admin/apps/entitlement", data={"id": "payer", "may_spend": "1"},
               headers=_AUTH, follow_redirects=False)
        assert asyncio.run(queries.app_may_spend("payer")) is True

        page = c.get("/admin/apps", headers={**_AUTH, "Cookie": "lang=en"}).text
        assert "Revoke spending" in page

        c.post("/admin/apps/entitlement", data={"id": "payer", "may_spend": "0"},
               headers=_AUTH, follow_redirects=False)
        assert asyncio.run(queries.app_may_spend("payer")) is False
    finally:
        asyncio.run(close_db())


def test_granting_the_entitlement_needs_no_restart_to_take_effect():
    """The gate reads the row per call, so the page and the ladder cannot disagree."""
    from app.verification import gates

    async def setup():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("payer", "tok-payer", "")
    asyncio.run(setup())
    try:
        c = _client()
        assert asyncio.run(gates.entitlement_gate("payer")())
        c.post("/admin/apps/entitlement", data={"id": "payer", "may_spend": "1"},
               headers=_AUTH, follow_redirects=False)
        assert asyncio.run(gates.entitlement_gate("payer")()) == ""
    finally:
        asyncio.run(close_db())
