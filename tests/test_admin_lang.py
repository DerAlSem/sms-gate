# tests/test_admin_lang.py
import asyncio
import base64

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.connection import init_db, close_db
from app.db.migrate import run_migrations
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


def test_messages_page_renders_via_render_helper():
    _db()
    try:
        r = _client().get("/admin/messages", headers=_AUTH)
        assert r.status_code == 200
        assert "SMS Gate" in r.text
    finally:
        asyncio.run(close_db())


def test_lang_switch_sets_cookie_and_redirects():
    _db()
    try:
        r = _client().get("/admin/lang/en", headers=_AUTH, follow_redirects=False)
        assert r.status_code == 303
        assert "lang=en" in r.headers.get("set-cookie", "")
    finally:
        asyncio.run(close_db())


def test_lang_switch_rejects_unknown_code():
    _db()
    try:
        r = _client().get("/admin/lang/zz", headers=_AUTH, follow_redirects=False)
        assert "lang=zz" not in r.headers.get("set-cookie", "")
    finally:
        asyncio.run(close_db())


def test_nav_is_russian_by_default_and_english_with_cookie():
    _db()
    try:
        c = _client()
        ru = c.get("/admin/messages", headers=_AUTH)
        assert "Статистика" in ru.text          # ru is default
        en = c.get("/admin/messages", headers={**_AUTH, "Cookie": "lang=en"})
        assert "Statistics" in en.text
        assert "Статистика" not in en.text
    finally:
        asyncio.run(close_db())


def test_messages_table_headers_translate():
    _db()
    try:
        c = _client()
        ru = c.get("/admin/messages", headers=_AUTH)
        assert "Фильтр" in ru.text
        en = c.get("/admin/messages", headers={**_AUTH, "Cookie": "lang=en"})
        assert "Filter" in en.text
        assert "Фильтр" not in en.text
    finally:
        asyncio.run(close_db())


def test_lang_switch_preserves_query_string():
    _db()
    try:
        r = _client().get("/admin/lang/en",
                          headers={**_AUTH, "Referer": "/admin/messages?page=3&status=sent"},
                          follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/admin/messages?page=3&status=sent"
    finally:
        asyncio.run(close_db())


def test_lang_switch_ignores_external_referer():
    _db()
    try:
        r = _client().get("/admin/lang/en",
                          headers={**_AUTH, "Referer": "https://evil.com/phish"},
                          follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/admin/messages"   # external host dropped
    finally:
        asyncio.run(close_db())


def test_header_is_sticky_and_nav_scrolls_on_mobile():
    _db()
    try:
        html = _client().get("/admin/messages", headers=_AUTH).text
        assert "position: sticky" in html
        assert "overflow-x: auto" in html
    finally:
        asyncio.run(close_db())
