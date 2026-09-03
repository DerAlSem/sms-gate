# tests/test_admin_settings.py
import asyncio
import base64

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.connection import init_db, close_db
from app.db.migrate import run_migrations
from app.settings_store import store
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
        await store.load()
    asyncio.run(run())


def test_get_settings_page_renders_without_leaking_secret():
    _db()
    try:
        async def seed():
            await store.set_many({"alert_bot_token": "SECRET-TOKEN-123"})
        asyncio.run(seed())
        r = _client().get("/admin/settings", headers=_AUTH)
        assert r.status_code == 200
        assert "voxlink_url" in r.text
        assert "alert_bot_token" in r.text         # the field/key is shown
        assert "SECRET-TOKEN-123" not in r.text     # but never the secret value
    finally:
        asyncio.run(close_db())


def test_post_valid_settings_persists_and_applies():
    _db()
    try:
        c = _client()
        r = c.post("/admin/settings", headers=_AUTH, follow_redirects=False, data={
            "voxlink_timeout": "12.5",
            "blacklist_threshold": "9",
        })
        assert r.status_code in (302, 303)
        assert store.voxlink_timeout == 12.5
        assert store.blacklist_threshold == 9
    finally:
        asyncio.run(close_db())


def test_post_invalid_value_persists_nothing():
    _db()
    try:
        async def baseline():
            await store.set_many({"voxlink_timeout": "7.0"})
        asyncio.run(baseline())
        c = _client()
        r = c.post("/admin/settings", headers=_AUTH, follow_redirects=False, data={
            "voxlink_timeout": "3.0",
            "blacklist_threshold": "abc",   # invalid int
        })
        assert r.status_code == 200            # re-rendered, not redirect
        assert store.voxlink_timeout == 7.0    # nothing persisted (atomic)
    finally:
        asyncio.run(close_db())


def test_phone_region_renders_as_country_select():
    _db()
    try:
        c = _client()
        ru = c.get("/admin/settings", headers=_AUTH)              # default RU locale
        assert "<select name=\"phone_region\"" in ru.text
        assert "Эстония (EE)" in ru.text
        assert 'value="RU" selected' in ru.text
        en = c.get("/admin/settings", headers={**_AUTH, "Cookie": "lang=en"})
        assert "Estonia (EE)" in en.text
    finally:
        asyncio.run(close_db())


def test_the_new_delivery_report_settings_render():
    """The three settings this change adds are reachable in the console.

    `posint` is a type the settings template has no branch for, so it falls through to a
    plain text input. That is the intended outcome and not an accident — but a template
    that raised on an unknown type would take the whole page down, and no unit test of
    the settings store can see that.
    """
    _db()
    try:
        r = _client().get("/admin/settings", headers=_AUTH)
        assert r.status_code == 200
        for key in ("delivery_report_max_age_hours",
                    "delivery_report_strict_attribution",
                    "notify_unplaced_reports"):
            assert f'id="set-{key}"' in r.text, f"{key} has no input on the page"
        assert 'name="delivery_report_max_age_hours" id="set-delivery_report_max_age_hours" type="text"' in r.text
        assert 'name="delivery_report_strict_attribution"' in r.text
        assert "168" in r.text and "true" in r.text
    finally:
        asyncio.run(close_db())


def test_the_window_refuses_zero_through_the_form():
    """The refusal an operator actually meets. A window of zero discards every report
    the gateway receives and would announce itself only as every message expiring."""
    _db()
    try:
        c = _client()
        assert c.post("/admin/settings",
                      data={"delivery_report_max_age_hours": "24"},
                      headers=_AUTH).status_code in (200, 303)
        r = c.post("/admin/settings",
                   data={"delivery_report_max_age_hours": "0"}, headers=_AUTH)
        assert r.status_code == 200, "a refused save re-renders the form"
        assert store.delivery_report_max_age_hours == 24, "the previous value stands"
    finally:
        asyncio.run(close_db())
