# tests/test_admin_settings_layout.py
"""SG-33.2: the settings screen grouped by the owner's own tasks, in Russian.

`Spec.section` (settings_store.py) is left alone by this change — these tests are
about `app.admin.settings_layout`, the display grouping on top of it, and about what
the rendered page says.
"""
import asyncio
import base64

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.admin import settings_layout
from app.admin.router import router
from app.config import settings
from app.db.connection import init_db, close_db
from app.db.migrate import run_migrations
from app.settings_store import SETTINGS_SPEC, store

_AUTH = {"Authorization": "Basic " + base64.b64encode(b"admin:change-me").decode()}


def _client(locale: str = "ru"):
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, cookies={"lang": locale})


def _db():
    async def run():
        await init_db(":memory:")
        await run_migrations()
        await store.load()
    asyncio.run(run())


def test_every_spec_key_is_in_exactly_one_layout_section():
    spec_keys = {s.key for s in SETTINGS_SPEC}
    layout_keys = [f.key for section in settings_layout.SECTIONS for f in section.fields]
    assert len(layout_keys) == len(set(layout_keys)), "a key is placed in two sections"
    assert set(layout_keys) == spec_keys, (
        f"missing from the layout: {spec_keys - set(layout_keys)}; "
        f"in the layout but not in SETTINGS_SPEC: {set(layout_keys) - spec_keys}"
    )


def test_ru_page_shows_the_owners_own_wording():
    _db()
    try:
        r = _client("ru").get("/admin/settings", headers=_AUTH)
        assert r.status_code == 200
        assert "Куда приходят алерты" in r.text
        assert "Лимит платных проверок в час" in r.text
        assert "Лимит платных проверок в сутки" in r.text
    finally:
        asyncio.run(close_db())


def test_en_page_shows_english_labels():
    _db()
    try:
        r = _client("en").get("/admin/settings", headers=_AUTH)
        assert r.status_code == 200
        assert "Where alerts go" in r.text
        assert "Paid verifications allowed per hour" in r.text
        assert "Paid verifications allowed per day" in r.text
    finally:
        asyncio.run(close_db())


def test_advanced_shows_a_changed_count_only_when_something_differs_from_default():
    _db()
    try:
        c = _client("ru")
        r = c.get("/admin/settings", headers=_AUTH)
        assert "changed:" not in r.text and "изменено" not in r.text

        async def change():
            await store.set_many({"voxlink_timeout": "42.0"})   # advanced, non-default
        asyncio.run(change())

        r = c.get("/admin/settings", headers=_AUTH)
        assert "изменено: 1" in r.text
    finally:
        asyncio.run(close_db())


def test_tg_account_card_never_leaks_the_hash_when_configured(monkeypatch):
    _db()
    try:
        monkeypatch.setattr(settings, "tg_api_id", 12345)
        monkeypatch.setattr(settings, "tg_api_hash", "SUPER-SECRET-HASH")
        monkeypatch.setattr(settings, "tg_session_dir", "/opt/sms-gate/tg-sessions")
        r = _client("ru").get("/admin/settings", headers=_AUTH)
        assert r.status_code == 200
        assert "SUPER-SECRET-HASH" not in r.text
    finally:
        asyncio.run(close_db())


def test_error_in_advanced_opens_its_details():
    _db()
    try:
        r = _client("ru").post("/admin/settings", headers=_AUTH, data={
            "_section": "advanced", "delivery_report_max_age_hours": "0",
        })
        assert r.status_code == 200
        assert "<details open" in r.text
    finally:
        asyncio.run(close_db())


def test_saving_a_section_redirects_to_its_own_anchor():
    _db()
    try:
        r = _client("ru").post("/admin/settings", headers=_AUTH, follow_redirects=False, data={
            "_section": "sending", "blacklist_threshold": "9",
        })
        assert r.status_code == 303
        assert r.headers["location"] == "/admin/settings?saved=sending#sending"
    finally:
        asyncio.run(close_db())


def test_tg_account_card_rows_say_not_set_rather_than_failing():
    # Scoped to the card's own rows: the page's empty password fields say "не задано" too,
    # so counting the phrase over the page would pass with the card failed.
    _db()
    try:
        r = _client("ru").get("/admin/settings", headers=_AUTH)
        assert "не удалось прочитать" not in r.text.lower()
        for var in ("TG_API_ID", "TG_API_HASH", "TG_SESSION_DIR"):
            row = r.text.split(f">{var}</code>", 1)[1].split("</tr>", 1)[0]
            assert "не задано" in row, var
    finally:
        asyncio.run(close_db())


def _overview_with(monkeypatch, reasons: dict):
    from app.verification import tg_user_carrier
    monkeypatch.setattr(type(store), "messenger_brands_parsed",
                        property(lambda self: {"apps": {a: {} for a in reasons}}))
    monkeypatch.setattr(tg_user_carrier, "unwired_reason", lambda app_id: reasons[app_id])
    asyncio.run(store.set_many({"verification_route_order": "tg_user,sms_out"}))
    return settings_layout.tg_account_overview()


def test_one_wired_application_is_enough_for_the_rung_to_be_on(monkeypatch):
    _db()
    try:
        o = _overview_with(monkeypatch, {"a": None, "b": "b writes as @x, and no session"})
        assert o["error"] is None
        assert o["ok"] and o["wired_count"] == 1
        r = _client("en").get("/admin/settings", headers=_AUTH)
        assert "Stage tg_user is enabled for 1 of 2 applications" in r.text
        assert "is not enabled" not in r.text
    finally:
        asyncio.run(close_db())


def test_no_wired_application_names_the_first_reason(monkeypatch):
    _db()
    try:
        o = _overview_with(monkeypatch, {"b": "b writes as @x, and no session"})
        assert not o["ok"]
        r = _client("en").get("/admin/settings", headers=_AUTH)
        assert "Stage tg_user is not enabled: b writes as @x, and no session" in r.text
    finally:
        asyncio.run(close_db())
