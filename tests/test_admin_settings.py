# tests/test_admin_settings.py
import asyncio
import html
import base64
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.connection import init_db, close_db
from app.db.migrate import run_migrations
from app.settings_store import store
from app.admin.router import router, BEARER_SENTINEL

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


def test_a_refused_save_keeps_the_valid_field_as_submitted():
    """SG-33.1 #2: a refusal on one field must not discard an edit on another. The
    re-rendered page shows what was just typed, not what is still stored."""
    _db()
    try:
        async def baseline():
            await store.set_many({"voxlink_timeout": "7.0"})
        asyncio.run(baseline())
        c = _client()
        r = c.post("/admin/settings", headers=_AUTH, data={
            "voxlink_timeout": "3.0",       # valid, and different from what is stored
            "blacklist_threshold": "abc",   # invalid int, refuses the whole submission
        })
        assert r.status_code == 200
        assert 'value="3.0"' in r.text, "the just-typed value must survive the refusal"
        assert store.voxlink_timeout == 7.0, "nothing was actually persisted"
    finally:
        asyncio.run(close_db())


def _brands_json(account: str, number: str) -> str:
    return json.dumps({
        "brands": {"sokol": {"tg_user": {
            "account": account, "number": number,
            "intro": "Это наш сервисный аккаунт, вы запросили код.",
        }}},
        "apps": {"sokol_app": {"brands": ["sokol"], "default": "sokol"}},
    })


def test_brand_without_a_rate_bound_errors_both_fields_and_saves_nothing():
    """SG-33.1 #3: `check_every_account_is_rate_bound` raises ValueError from inside
    `store.set_many` — the router must catch it rather than let it become a 500, and the
    message belongs to both settings that together decide the bound."""
    _db()
    try:
        c = _client()
        brands = _brands_json("sokol_tg", "+79851600019")
        limits = json.dumps({"accounts": {}, "recipient_window_seconds": 600})
        r = c.post("/admin/settings", headers=_AUTH, data={
            "messenger_brands": brands,
            "messenger_limits": limits,
        })
        assert r.status_code == 200, "the cross-setting refusal must not be a 500"
        assert r.text.count("no rate bound") == 2, "the error is shown under both fields"
        assert store.messenger_brands == "", "nothing was persisted"
        assert store.messenger_limits == ""
    finally:
        asyncio.run(close_db())


def test_saving_one_section_does_not_touch_another_and_redirects_with_saved():
    """SG-33.1 #4/#5: each section is its own form and its own save; a successful save
    redirects back to that section with `?saved=<section>`, and only that section's
    settings changed.

    SG-33.2: sections are now `settings_layout`'s display groups (`voxlink_timeout`
    lives under `advanced`), not `Spec.section` — the id used here is the layout's."""
    _db()
    try:
        async def baseline():
            await store.set_many({"blacklist_threshold": "5"})
        asyncio.run(baseline())
        c = _client()
        r = c.post("/admin/settings", headers=_AUTH, follow_redirects=False, data={
            "_section": "advanced",
            "voxlink_timeout": "9.5",
        })
        assert r.status_code == 303
        assert r.headers["location"] == "/admin/settings?saved=advanced#advanced"
        assert store.voxlink_timeout == 9.5
        assert store.blacklist_threshold == 5, "a different section must stand untouched"

        page = c.get("/admin/settings?saved=advanced", headers=_AUTH)
        assert page.status_code == 200
        assert "Сохранено" in page.text
    finally:
        asyncio.run(close_db())


def test_checkbox_unchecked_saves_false_checked_saves_true():
    """SG-33.1 #6: the hidden-then-checkbox pair. Starlette's form keeps the last value
    for a repeated key, so an unticked box (only the hidden field arrives) must save
    false, and a ticked one (hidden, then the checkbox) must save true."""
    _db()
    try:
        c = _client()
        r = c.post("/admin/settings", headers=_AUTH, data={
            "delivery_report_strict_attribution": "false",   # box left unticked
        })
        assert r.status_code in (200, 303)
        assert store.delivery_report_strict_attribution is False

        r = c.post("/admin/settings", headers=_AUTH, data={
            # order matters: the hidden field is rendered before the checkbox
            "delivery_report_strict_attribution": ["false", "true"],
        })
        assert r.status_code in (200, 303)
        assert store.delivery_report_strict_attribution is True
    finally:
        asyncio.run(close_db())


def _routes_json(*, prefix: str, url: str, bearer: str = "") -> str:
    item = {"prefix": prefix, "webhook_url": url}
    if bearer:
        item["bearer"] = bearer
    return json.dumps([item])


def test_bearer_is_never_shown_and_resaving_unchanged_text_keeps_it():
    """SG-33.1 #7: a bearer is masked on the page, and saving the masked textarea back
    unchanged must not stomp the real bearer with the sentinel."""
    _db()
    try:
        async def seed():
            await store.set_many({
                "inbound_dispatch": _routes_json(
                    prefix="X", url="https://example.org/hook", bearer="real-secret-1",
                ),
            })
        asyncio.run(seed())

        c = _client()
        page = c.get("/admin/settings", headers=_AUTH)
        assert "real-secret-1" not in page.text
        assert BEARER_SENTINEL in page.text

        # Re-save the section with the bearer left exactly as shown (masked).
        r = c.post("/admin/settings", headers=_AUTH, data={
            "inbound_dispatch": _routes_json(
                prefix="X", url="https://example.org/hook", bearer=BEARER_SENTINEL,
            ),
        })
        assert r.status_code in (200, 303)
        assert json.loads(store.inbound_dispatch)[0]["bearer"] == "real-secret-1"
    finally:
        asyncio.run(close_db())


def test_bearer_sentinel_on_a_new_route_is_refused():
    """SG-33.1 #7: the sentinel names a route the store does not have — saving it as a
    literal bearer would silently ship a route that fails at the vendor on its first
    call, so this must be a field error instead."""
    _db()
    try:
        c = _client()
        r = c.post("/admin/settings", headers=_AUTH, data={
            "inbound_dispatch": _routes_json(
                prefix="new-route", url="https://example.org/hook", bearer=BEARER_SENTINEL,
            ),
        })
        assert r.status_code == 200
        assert "bearer" in r.text
        assert store.inbound_dispatch == "", "nothing was persisted"
    finally:
        asyncio.run(close_db())


def test_a_refused_section_is_marked_unsaved():
    """The values a refused save shows back are not stored: the section says so.

    SG-33.2: `blacklist_threshold` (valid) now lives under `sending`, and
    `delivery_report_max_age_hours` (refused) under `advanced` — two different
    display sections. Only the one holding the refused field is marked unsaved, and
    it — being `advanced` — opens its `<details>`."""
    _db()
    try:
        r = _client().post("/admin/settings", headers=_AUTH, data={
            "_section": "sending", "blacklist_threshold": "9",
            "delivery_report_max_age_hours": "0"})
        assert r.status_code == 200
        advanced = r.text.split('id="advanced"', 1)[1].split('class="card"', 1)[0]
        assert "<details open" in advanced
        assert 'class="dirty-mark muted" style="font-size:11px;font-weight:600;" >' in advanced
        sending = r.text.split('id="sending"', 1)[1].split('class="card"', 1)[0]
        assert "hidden>" in sending.split("dirty-mark", 1)[1][:80]
    finally:
        asyncio.run(close_db())


def test_a_bearer_typed_into_a_refused_save_is_not_reverted_by_the_next():
    """Review of SG-33.1: a refused save showed a just-typed bearer as the sentinel, and
    the next save resolved that sentinel to the OLD bearer — the edit lost behind green."""
    _db()
    try:
        async def seed():
            await store.set_many({"inbound_dispatch": _routes_json(
                prefix="X", url="https://example.org/hook", bearer="old-secret")})
        asyncio.run(seed())
        c = _client()
        broken = json.dumps([
            {"prefix": "X", "webhook_url": "https://example.org/hook", "bearer": "new-secret"},
            {"prefix": "Y", "webhook_url": ""},
        ])
        r = c.post("/admin/settings", headers=_AUTH, data={"inbound_dispatch": broken})
        assert r.status_code == 200
        assert "new-secret" in r.text, "the typed bearer comes back as typed"
        textarea = r.text.split('id="set-inbound_dispatch"', 1)[1].split("</textarea>", 1)[0]
        resubmit = html.unescape(textarea.split(">", 1)[1])
        fixed = json.loads(resubmit)[:1]
        c.post("/admin/settings", headers=_AUTH, data={"inbound_dispatch": json.dumps(fixed)})
        assert json.loads(store.inbound_dispatch)[0]["bearer"] == "new-secret"
    finally:
        asyncio.run(close_db())


def test_routes_sharing_a_key_keep_their_own_bearers():
    """Review of SG-33.1: nothing refuses two routes with one key, and resolving the
    sentinel by key alone gave both the bearer of the last."""
    _db()
    try:
        routes = [
            {"prefix": "X", "webhook_url": "https://a.example/hook", "bearer": "first"},
            {"prefix": "X", "webhook_url": "https://b.example/hook", "bearer": "second"},
        ]
        async def seed():
            await store.set_many({"inbound_dispatch": json.dumps(routes)})
        asyncio.run(seed())
        masked = [dict(r, bearer=BEARER_SENTINEL) for r in routes]
        r = _client().post("/admin/settings", headers=_AUTH,
                           data={"inbound_dispatch": json.dumps(masked)})
        assert r.status_code in (200, 303)
        assert [x["bearer"] for x in json.loads(store.inbound_dispatch)] == ["first", "second"]
    finally:
        asyncio.run(close_db())
