# tests/test_i18n_completeness.py
import re
import asyncio
import base64
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.connection import init_db, close_db
from app.db.migrate import run_migrations
from app.db import queries
from app.admin.router import router

_CYRILLIC = re.compile(r"[А-Яа-яЁё]")
_TPL_DIR = Path("app/admin/templates")
_AUTH = {"Authorization": "Basic " + base64.b64encode(b"admin:change-me").decode()}


def _app():
    app = FastAPI()
    app.include_router(router)
    return app


def test_no_cyrillic_literals_left_in_templates():
    offenders = [f.name for f in _TPL_DIR.glob("*.html")
                 if _CYRILLIC.search(f.read_text(encoding="utf-8"))]
    assert offenders == [], f"Cyrillic literals remain in: {offenders}"


def test_english_render_has_no_cyrillic_on_each_page():
    async def setup():
        await init_db(":memory:")
        await run_migrations()
        # seed one row per area so list/detail pages render with data
        await queries.create_message("admin", "+79995550011", "hi")
    asyncio.run(setup())
    try:
        c = TestClient(_app())
        paths = ("/admin/messages", "/admin/inbound", "/admin/dialogs",
                 "/admin/blacklist", "/admin/ranges", "/admin/stats",
                 "/admin/dialogs/+79995550011")
        for path in paths:
            r = c.get(path, headers={**_AUTH, "Cookie": "lang=en"})
            assert r.status_code == 200, f"{path} -> {r.status_code}"
            assert not _CYRILLIC.search(r.text), f"Cyrillic in EN render of {path}"
    finally:
        asyncio.run(close_db())


def test_russian_render_shows_translations():
    async def setup():
        await init_db(":memory:")
        await run_migrations()
    asyncio.run(setup())
    try:
        c = TestClient(_app())
        r = c.get("/admin/stats", headers=_AUTH)   # default ru
        assert r.status_code == 200
        assert "Статистика" in r.text              # nav translated
        assert "За 14 дней" in r.text              # stats.html string translated under ru
    finally:
        asyncio.run(close_db())
