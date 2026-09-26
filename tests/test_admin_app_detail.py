"""SG-33.4: the application detail page `/admin/apps/<id>`.

Storage is unchanged — the same three `settings` keys (`verification_templates`,
`delivery_dispatch`, `messenger_brands`) this page edits are the ones the settings
screen used to edit as raw JSON (doc-7). These tests are about the page: it edits
only the one entry that belongs to the application whose page it is, and leaves
every other application's entry exactly as stored.
"""
import asyncio
import base64
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.connection import init_db, close_db
from app.db.migrate import run_migrations
from app.db import queries
from app.settings_store import store
from app.admin.router import router

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


def _seed_apps(*ids):
    async def run():
        for app_id in ids:
            await queries.create_app(app_id, f"tok_{app_id}", "")
    asyncio.run(run())


# --------------------------------------------------------------------------- listing


def test_the_apps_list_links_to_the_application_page():
    _db()
    try:
        _seed_apps("sp_app")
        c = _client("en")
        page = c.get("/admin/apps", headers=_AUTH).text
        assert 'href="/admin/apps/sp_app"' in page
    finally:
        asyncio.run(close_db())


def test_the_apps_list_shows_no_template_in_red():
    _db()
    try:
        _seed_apps("sp_app")
        c = _client("en")
        page = c.get("/admin/apps", headers=_AUTH).text
        assert "no — no code will be sent by SMS" in page
    finally:
        asyncio.run(close_db())


def test_the_apps_list_does_not_alarm_about_internal_senders():
    """`admin` and `telegram` send free text (a resend, a reply), never a code — no
    template is their normal state, and a red row for them is noise that teaches the
    owner to skip the column."""
    _db()
    try:
        _seed_apps("sp_app")
        c = _client("en")
        page = c.get("/admin/apps", headers=_AUTH).text
        rows = {r.split("</code>")[0].rsplit(">", 1)[-1]: r
                for r in page.split("<tr>")[2:]}
        assert "not needed — internal sender" in rows["admin"]
        assert "not needed — internal sender" in rows["telegram"]
        assert "no — no code will be sent by SMS" in rows["sp_app"]
        assert "no — no code will be sent by SMS" not in rows["admin"]
    finally:
        asyncio.run(close_db())


def test_the_apps_list_shows_an_unreadable_template_store_without_crashing():
    _db()
    try:
        _seed_apps("sp_app")
        store._cache["verification_templates"] = "not json at all"
        c = _client("en")
        r = c.get("/admin/apps", headers=_AUTH)
        assert r.status_code == 200
        assert "unreadable" in r.text
    finally:
        asyncio.run(close_db())


def test_a_missing_application_404s_rather_than_500s():
    _db()
    try:
        c = _client()
        r = c.get("/admin/apps/does-not-exist", headers=_AUTH)
        assert r.status_code == 404
    finally:
        asyncio.run(close_db())


# --------------------------------------------------------------------------- template


def test_saving_a_template_stores_it_and_shows_on_the_page():
    _db()
    try:
        _seed_apps("sp_app")
        c = _client()
        r = c.post("/admin/apps/sp_app/save", headers=_AUTH, data={
            "_part": "template", "template": "SokolParking: {code}",
        }, follow_redirects=False)
        assert r.status_code == 303
        assert json.loads(store.verification_templates) == [
            {"app_id": "sp_app", "template": "SokolParking: {code}"}
        ]
        page = c.get("/admin/apps/sp_app", headers=_AUTH).text
        assert "SokolParking: {code}" in page

        # empty removes the entry rather than storing a blank template
        r = c.post("/admin/apps/sp_app/save", headers=_AUTH, data={
            "_part": "template", "template": "",
        }, follow_redirects=False)
        assert r.status_code == 303
        assert store.verification_templates == "[]"
    finally:
        asyncio.run(close_db())


def test_an_invalid_template_is_refused_at_the_field_and_shows_what_was_typed():
    _db()
    try:
        _seed_apps("sp_app")
        c = _client()
        r = c.post("/admin/apps/sp_app/save", headers=_AUTH, data={
            "_part": "template", "template": "{code} twice: {code}",
        })
        assert r.status_code == 200
        assert "{code} twice: {code}" in r.text
        assert "appears 2 times" in r.text
        assert store.verification_templates == ""
    finally:
        asyncio.run(close_db())


# --------------------------------------------------------------------------- webhook


def test_bearer_never_reaches_the_page_and_a_blank_resave_keeps_it():
    _db()
    try:
        _seed_apps("sp_app")
        c = _client()
        r = c.post("/admin/apps/sp_app/save", headers=_AUTH, data={
            "_part": "webhook", "webhook_url": "https://example.org/hook",
            "bearer": "top-secret",
        }, follow_redirects=False)
        assert r.status_code == 303

        page = c.get("/admin/apps/sp_app", headers=_AUTH).text
        assert "top-secret" not in page

        # a resave with no bearer typed must keep the stored one
        r = c.post("/admin/apps/sp_app/save", headers=_AUTH, data={
            "_part": "webhook", "webhook_url": "https://example.org/hook2",
        }, follow_redirects=False)
        assert r.status_code == 303
        stored = json.loads(store.delivery_dispatch)[0]
        assert stored["webhook_url"] == "https://example.org/hook2"
        assert stored["bearer"] == "top-secret"

        # the checkbox is an explicit erasure
        r = c.post("/admin/apps/sp_app/save", headers=_AUTH, data={
            "_part": "webhook", "webhook_url": "https://example.org/hook2",
            "clear_bearer": ["false", "true"],
        }, follow_redirects=False)
        assert r.status_code == 303
        stored = json.loads(store.delivery_dispatch)[0]
        assert "bearer" not in stored or not stored["bearer"]
    finally:
        asyncio.run(close_db())


def test_a_blank_webhook_url_removes_the_record():
    _db()
    try:
        _seed_apps("sp_app")
        c = _client()
        c.post("/admin/apps/sp_app/save", headers=_AUTH, data={
            "_part": "webhook", "webhook_url": "https://example.org/hook",
        })
        r = c.post("/admin/apps/sp_app/save", headers=_AUTH, data={
            "_part": "webhook", "webhook_url": "",
        }, follow_redirects=False)
        assert r.status_code == 303
        assert store.delivery_dispatch == "[]"
    finally:
        asyncio.run(close_db())


# --------------------------------------------------------------------------- brands


def _seed_brands_and_limits():
    brands = {
        "brands": {
            "sokol": {"tg_user": {
                "account": "@sokolbot", "number": "+79990000001",
                "intro": "Sokol code",
            }},
        },
    }
    limits = {"accounts": {"@sokolbot": {"per_hour": 5, "per_day": 20}},
              "recipient_window_seconds": 600}

    async def run():
        await store.set_many({
            "messenger_brands": json.dumps(brands, ensure_ascii=False),
            "messenger_limits": json.dumps(limits, ensure_ascii=False),
        })
    asyncio.run(run())


def test_a_brand_selection_and_default_are_saved_into_apps():
    _db()
    try:
        _seed_apps("sokol_app")
        _seed_brands_and_limits()
        c = _client()
        r = c.post("/admin/apps/sokol_app/save", headers=_AUTH, data={
            "_part": "brands", "brands": "sokol", "default": "sokol",
        }, follow_redirects=False)
        assert r.status_code == 303
        data = json.loads(store.messenger_brands)
        assert data["apps"]["sokol_app"] == {"brands": ["sokol"], "default": "sokol"}

        # nothing checked removes the app's key entirely
        r = c.post("/admin/apps/sokol_app/save", headers=_AUTH, data={
            "_part": "brands",
        }, follow_redirects=False)
        assert r.status_code == 303
        data = json.loads(store.messenger_brands)
        assert "sokol_app" not in data["apps"]
    finally:
        asyncio.run(close_db())


def test_no_brands_configured_shows_a_pointer_to_settings_instead_of_a_form():
    _db()
    try:
        _seed_apps("lonely_app")
        c = _client("en")
        page = c.get("/admin/apps/lonely_app", headers=_AUTH).text
        assert "No brands are set up" in page
        assert '/admin/settings#vendors' in page
        assert '"_part" value="brands"' not in page
    finally:
        asyncio.run(close_db())


def test_a_brand_with_no_rate_bound_is_refused_not_a_server_error():
    _db()
    try:
        _seed_apps("sokol_app")
        brands = {
            "brands": {
                "sokol": {"tg_user": {
                    "account": "@nolimit", "number": "+79990000002",
                    "intro": "Sokol code",
                }},
            },
        }
        # Seeded directly into the cache: `store.set_many` itself refuses a brand with
        # no limit, so this reproduces "the brand already existed unbounded" without
        # going through the door this test is about.
        store._cache["messenger_brands"] = json.dumps(brands, ensure_ascii=False)
        c = _client()
        r = c.post("/admin/apps/sokol_app/save", headers=_AUTH, data={
            "_part": "brands", "brands": "sokol", "default": "sokol",
        })
        assert r.status_code == 200
        assert "rate bound" in r.text
        data = json.loads(store.messenger_brands)
        assert "apps" not in data or "sokol_app" not in data.get("apps", {})
    finally:
        asyncio.run(close_db())


# ------------------------------------------------------------- one app leaves others alone


def test_saving_one_apps_template_does_not_touch_anothers():
    _db()
    try:
        _seed_apps("app_a", "app_b")
        c = _client()
        c.post("/admin/apps/app_a/save", headers=_AUTH, data={
            "_part": "template", "template": "A: {code}"})
        c.post("/admin/apps/app_b/save", headers=_AUTH, data={
            "_part": "template", "template": "B: {code}"})
        before = json.loads(store.verification_templates)
        c.post("/admin/apps/app_a/save", headers=_AUTH, data={
            "_part": "template", "template": "A changed: {code}"})
        after = json.loads(store.verification_templates)
        b_before = next(x for x in before if x["app_id"] == "app_b")
        b_after = next(x for x in after if x["app_id"] == "app_b")
        assert b_before == b_after
    finally:
        asyncio.run(close_db())


def test_saving_one_apps_webhook_does_not_touch_anothers():
    _db()
    try:
        _seed_apps("app_a", "app_b")
        c = _client()
        c.post("/admin/apps/app_a/save", headers=_AUTH, data={
            "_part": "webhook", "webhook_url": "https://a.example/hook",
            "bearer": "bearer-a"})
        c.post("/admin/apps/app_b/save", headers=_AUTH, data={
            "_part": "webhook", "webhook_url": "https://b.example/hook",
            "bearer": "bearer-b"})
        before = json.loads(store.delivery_dispatch)
        c.post("/admin/apps/app_a/save", headers=_AUTH, data={
            "_part": "webhook", "webhook_url": "https://a.example/hook2"})
        after = json.loads(store.delivery_dispatch)
        b_before = next(x for x in before if x["app_id"] == "app_b")
        b_after = next(x for x in after if x["app_id"] == "app_b")
        assert b_before == b_after
    finally:
        asyncio.run(close_db())


def test_saving_one_apps_brands_does_not_touch_anothers():
    _db()
    try:
        _seed_apps("app_a", "app_b")
        brands = {
            "brands": {
                "sokol": {"tg_user": {
                    "account": "@sokolbot", "number": "+79990000001",
                    "intro": "Sokol code"}},
                "gm": {"tg_user": {
                    "account": "@gmbot", "number": "+79990000002",
                    "intro": "GM code"}},
            },
        }
        limits = {"accounts": {
            "@sokolbot": {"per_hour": 5, "per_day": 20},
            "@gmbot": {"per_hour": 5, "per_day": 20},
        }, "recipient_window_seconds": 600}

        async def seed():
            await store.set_many({
                "messenger_brands": json.dumps(brands, ensure_ascii=False),
                "messenger_limits": json.dumps(limits, ensure_ascii=False),
            })
        asyncio.run(seed())
        c = _client()
        c.post("/admin/apps/app_a/save", headers=_AUTH, data={
            "_part": "brands", "brands": "sokol", "default": "sokol"})
        c.post("/admin/apps/app_b/save", headers=_AUTH, data={
            "_part": "brands", "brands": "gm", "default": "gm"})
        before = json.loads(store.messenger_brands)["apps"]["app_b"]
        c.post("/admin/apps/app_a/save", headers=_AUTH, data={
            "_part": "brands"})
        after = json.loads(store.messenger_brands)["apps"]["app_b"]
        assert before == after
    finally:
        asyncio.run(close_db())


# --------------------------------------------------------------------------- settings


def test_settings_page_has_no_input_for_the_two_app_owned_keys():
    _db()
    try:
        c = _client()
        page = c.get("/admin/settings", headers=_AUTH).text
        assert 'name="verification_templates"' not in page
        assert 'name="delivery_dispatch"' not in page
        assert "/admin/apps" in page
    finally:
        asyncio.run(close_db())


def test_settings_page_never_shows_apps_inside_messenger_brands():
    _db()
    try:
        brands = {
            "brands": {"sokol": {"tg_user": {
                "account": "@sokolbot", "number": "+79990000001",
                "intro": "Sokol code"}}},
            "apps": {"sokol_app": {"brands": ["sokol"], "default": "sokol"}},
        }
        limits = {"accounts": {"@sokolbot": {"per_hour": 5, "per_day": 20}},
                  "recipient_window_seconds": 600}

        async def seed():
            await store.set_many({
                "messenger_brands": json.dumps(brands, ensure_ascii=False),
                "messenger_limits": json.dumps(limits, ensure_ascii=False),
            })
        asyncio.run(seed())
        c = _client()
        page = c.get("/admin/settings", headers=_AUTH).text
        # Scoped to the textarea itself: the Telegram account card in the same
        # section names `sokol_app` on purpose (it is a diagnostic, not the field
        # this change touches), so asserting over the whole section would pass with
        # the field itself unchanged.
        textarea = page.split('id="set-messenger_brands"', 1)[1].split("</textarea>", 1)[0]
        assert '"apps"' not in textarea
        assert "sokol_app" not in textarea
        assert "@sokolbot" in textarea
    finally:
        asyncio.run(close_db())


def test_saving_vendors_section_keeps_stored_apps_binding():
    _db()
    try:
        brands = {
            "brands": {"sokol": {"tg_user": {
                "account": "@sokolbot", "number": "+79990000001",
                "intro": "Sokol code"}}},
            "apps": {"sokol_app": {"brands": ["sokol"], "default": "sokol"}},
        }
        limits = {"accounts": {"@sokolbot": {"per_hour": 5, "per_day": 20}},
                  "recipient_window_seconds": 600}

        async def seed():
            await store.set_many({
                "messenger_brands": json.dumps(brands, ensure_ascii=False),
                "messenger_limits": json.dumps(limits, ensure_ascii=False),
            })
        asyncio.run(seed())
        c = _client()
        # Re-save exactly the brands-only text the page would show (no "apps").
        resend = json.dumps({"brands": brands["brands"]}, ensure_ascii=False)
        r = c.post("/admin/settings", headers=_AUTH, data={
            "_section": "vendors", "messenger_brands": resend,
            "messenger_limits": json.dumps(limits, ensure_ascii=False),
        }, follow_redirects=False)
        assert r.status_code == 303
        data = json.loads(store.messenger_brands)
        assert data["apps"] == {"sokol_app": {"brands": ["sokol"], "default": "sokol"}}
    finally:
        asyncio.run(close_db())


def test_a_submitted_apps_key_is_refused_on_the_settings_page():
    _db()
    try:
        c = _client()
        r = c.post("/admin/settings", headers=_AUTH, data={
            "_section": "vendors",
            "messenger_brands": json.dumps({"brands": {}, "apps": {"x": {}}}),
        })
        assert r.status_code == 200
        assert "not edited here" in r.text
        assert store.messenger_brands == ""
    finally:
        asyncio.run(close_db())


# ------------------------------------------------------------- review: orphaned records


def test_a_leftover_template_gets_a_page_instead_of_a_404():
    """review #1: a deleted application's id has no row in `apps`, but a leftover
    template still blocks a save of the whole list (it is validated as one) — the
    page has to exist so the record can be fixed or cleared."""
    _db()
    try:
        async def seed():
            await store.set_many({"verification_templates": json.dumps(
                [{"app_id": "ghost", "template": "Ghost: {code}"}]
            )})
        asyncio.run(seed())
        c = _client("en")
        r = c.get("/admin/apps/ghost", headers=_AUTH)
        assert r.status_code == 200
        assert "no application with this id" in r.text
    finally:
        asyncio.run(close_db())


def test_an_id_with_no_row_and_no_leftover_record_still_404s():
    _db()
    try:
        c = _client()
        r = c.get("/admin/apps/does-not-exist", headers=_AUTH)
        assert r.status_code == 404
    finally:
        asyncio.run(close_db())


def test_the_orphan_page_can_clear_its_own_leftover_record():
    _db()
    try:
        async def seed():
            await store.set_many({"verification_templates": json.dumps(
                [{"app_id": "ghost", "template": "Ghost: {code}"}]
            )})
        asyncio.run(seed())
        c = _client()
        r = c.post("/admin/apps/ghost/save", headers=_AUTH, data={
            "_part": "template", "template": "",
        }, follow_redirects=False)
        assert r.status_code == 303
        assert store.verification_templates == "[]"
        # nothing names it any more: the page is gone too
        assert c.get("/admin/apps/ghost", headers=_AUTH).status_code == 404
    finally:
        asyncio.run(close_db())


def test_the_apps_list_names_leftover_records_of_deleted_applications():
    _db()
    try:
        async def seed():
            await store.set_many({"delivery_dispatch": json.dumps(
                [{"app_id": "ghost", "webhook_url": "https://example.org/hook"}]
            )})
        asyncio.run(seed())
        c = _client("en")
        page = c.get("/admin/apps", headers=_AUTH).text
        assert "Records of deleted applications remain" in page
        assert 'href="/admin/apps/ghost"' in page
    finally:
        asyncio.run(close_db())


def test_a_live_application_is_not_listed_as_leftover():
    _db()
    try:
        _seed_apps("sp_app")
        c = _client("en")
        page = c.get("/admin/apps", headers=_AUTH).text
        assert "Records of deleted applications remain" not in page
    finally:
        asyncio.run(close_db())


# ------------------------------------------------------------- review: unreadable stored


def test_an_unreadable_templates_store_refuses_the_save_rather_than_erasing_it():
    """review #2: `_replace_app_entry` must not rebuild the list from `[]` when the
    stored value cannot be read — that would silently drop every other application's
    template the moment this one is saved."""
    _db()
    try:
        _seed_apps("sp_app")
        store._cache["verification_templates"] = "{not json"
        c = _client()
        r = c.post("/admin/apps/sp_app/save", headers=_AUTH, data={
            "_part": "template", "template": "New: {code}",
        })
        assert r.status_code == 200
        assert "cannot be read" in r.text
        assert store.get("verification_templates") == "{not json"
    finally:
        asyncio.run(close_db())


def test_an_unreadable_delivery_dispatch_refuses_the_save():
    _db()
    try:
        _seed_apps("sp_app")
        store._cache["delivery_dispatch"] = '[{"app_id": "x"'  # truncated, unparsable
        c = _client()
        r = c.post("/admin/apps/sp_app/save", headers=_AUTH, data={
            "_part": "webhook", "webhook_url": "https://example.org/hook",
        })
        assert r.status_code == 200
        assert "cannot be read" in r.text
        assert store.get("delivery_dispatch") == '[{"app_id": "x"'
    finally:
        asyncio.run(close_db())


def test_a_non_object_messenger_brands_refuses_the_brands_save():
    _db()
    try:
        _seed_apps("sp_app")
        store._cache["messenger_brands"] = "[]"  # a list, not an object
        c = _client()
        r = c.post("/admin/apps/sp_app/save", headers=_AUTH, data={
            "_part": "brands",
        })
        assert r.status_code == 200
        assert "not a JSON object" in r.text
        assert store.get("messenger_brands") == "[]"
    finally:
        asyncio.run(close_db())


# ------------------------------------------------------------------- review: route split


def test_an_application_literally_named_delete_can_still_save_its_template():
    """review #3: the page's own save used to be `POST /admin/apps/{app_id}`, which an
    application named `delete` collided with — `/admin/apps/delete` is also the path
    the applications-list delete action posts to."""
    _db()
    try:
        _seed_apps("delete")
        c = _client()
        r = c.post("/admin/apps/delete/save", headers=_AUTH, data={
            "_part": "template", "template": "D: {code}",
        }, follow_redirects=False)
        assert r.status_code == 303
        assert json.loads(store.verification_templates) == [
            {"app_id": "delete", "template": "D: {code}"}
        ]
    finally:
        asyncio.run(close_db())


def test_the_delete_action_route_is_unaffected_by_the_new_save_route():
    _db()
    try:
        _seed_apps("throwaway")
        c = _client()
        r = c.post("/admin/apps/delete", headers=_AUTH, data={"id": "throwaway"},
                   follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/admin/apps"
        ids = [a["id"] for a in asyncio.run(queries.list_apps())]
        assert "throwaway" not in ids
    finally:
        asyncio.run(close_db())


# --------------------------------------------------------------------- review: id encoding


def test_an_id_containing_a_slash_opens_and_saves():
    from urllib.parse import quote
    _db()
    try:
        _seed_apps("shop/eu")
        c = _client()
        path = quote("shop/eu", safe="/")
        r = c.get(f"/admin/apps/{path}", headers=_AUTH)
        assert r.status_code == 200
        r2 = c.post(f"/admin/apps/{path}/save", headers=_AUTH, data={
            "_part": "template", "template": "Shop EU: {code}",
        }, follow_redirects=False)
        assert r2.status_code == 303
        assert json.loads(store.verification_templates) == [
            {"app_id": "shop/eu", "template": "Shop EU: {code}"}
        ]
    finally:
        asyncio.run(close_db())


def test_an_id_containing_a_hash_opens_and_saves():
    from urllib.parse import quote
    _db()
    try:
        _seed_apps("a#b")
        c = _client()
        path = quote("a#b", safe="/")
        r = c.get(f"/admin/apps/{path}", headers=_AUTH)
        assert r.status_code == 200
        r2 = c.post(f"/admin/apps/{path}/save", headers=_AUTH, data={
            "_part": "template", "template": "AB: {code}",
        }, follow_redirects=False)
        assert r2.status_code == 303
        assert "a%23b" in r2.headers["location"]
        assert json.loads(store.verification_templates) == [
            {"app_id": "a#b", "template": "AB: {code}"}
        ]
    finally:
        asyncio.run(close_db())


def test_the_apps_list_encodes_ids_with_special_characters_in_their_links():
    from urllib.parse import quote
    _db()
    try:
        _seed_apps("a#b")
        c = _client("en")
        page = c.get("/admin/apps", headers=_AUTH).text
        assert f'href="/admin/apps/{quote("a#b", safe="/")}"' in page
    finally:
        asyncio.run(close_db())


# ------------------------------------------------------- SG-33.5: a template per rung
#
# SG-34 keyed a template on (app_id, route): `sms_out`, `tg_user`, or none — the entry
# that stands in for every worded rung. The page edits all three slots.


def _set_templates(entries):
    asyncio.run(store.set_many({"verification_templates": json.dumps(entries)}))


def test_the_page_edits_each_rung_slot_on_its_own_pair():
    _db()
    try:
        _seed_apps("gmp_app", "other")
        _set_templates([
            {"app_id": "other", "template": "O: {code}"},
            {"app_id": "gmp_app", "route": "tg_user", "template": "TG: {code}"},
            {"app_id": "gmp_app", "template": "Common: {code}"},
        ])
        c = _client()
        r = c.post("/admin/apps/gmp_app/save", headers=_AUTH, data={
            "_part": "template", "template": "Common: {code}",
            "template_sms_out": "GM+: {code_words}", "template_tg_user": "TG2: {code}"},
            follow_redirects=False)
        assert r.status_code == 303
        assert json.loads(store.verification_templates) == [
            {"app_id": "other", "template": "O: {code}"},
            {"app_id": "gmp_app", "route": "tg_user", "template": "TG2: {code}"},
            {"app_id": "gmp_app", "template": "Common: {code}"},
            {"app_id": "gmp_app", "route": "sms_out", "template": "GM+: {code_words}"},
        ]
        # a blank slot removes only its own entry
        c.post("/admin/apps/gmp_app/save", headers=_AUTH, data={
            "_part": "template", "template": "Common: {code}",
            "template_sms_out": "GM+: {code_words}", "template_tg_user": ""})
        assert [(x["app_id"], x.get("route")) for x in json.loads(store.verification_templates)] == [
            ("other", None), ("gmp_app", None), ("gmp_app", "sms_out")]
    finally:
        asyncio.run(close_db())


def test_saving_the_common_text_keeps_a_rung_entry_that_came_first():
    """The SG-33.4 page rewrote the *first* entry with this app_id — a rung entry first
    in the list turned into the common one, and the rung lost its own text."""
    _db()
    try:
        _seed_apps("gmp_app")
        _set_templates([
            {"app_id": "gmp_app", "route": "sms_out", "template": "SMS: {code_words}"},
        ])
        c = _client()
        c.post("/admin/apps/gmp_app/save", headers=_AUTH, data={
            "_part": "template", "template": "Common: {code}"})
        assert json.loads(store.verification_templates) == [
            {"app_id": "gmp_app", "route": "sms_out", "template": "SMS: {code_words}"},
            {"app_id": "gmp_app", "template": "Common: {code}"},
        ]
    finally:
        asyncio.run(close_db())


def test_the_page_says_which_text_each_rung_goes_with():
    _db()
    try:
        _seed_apps("gmp_app")
        _set_templates([
            {"app_id": "gmp_app", "route": "sms_out", "template": "SMS: {code_words}"},
        ])
        page = _client("en").get("/admin/apps/gmp_app", headers=_AUTH).text
        assert "SMS: {code_words}" in page
        assert "SMS goes with its own text" in page
        assert "no text — the Telegram account rung is not used" in page

        _set_templates([{"app_id": "gmp_app", "template": "Common: {code}"}])
        page = _client("en").get("/admin/apps/gmp_app", headers=_AUTH).text
        assert "SMS goes with the common text" in page
        assert "Telegram goes with the common text" in page
    finally:
        asyncio.run(close_db())


def test_a_refused_rung_template_keeps_every_typed_field():
    _db()
    try:
        _seed_apps("gmp_app")
        c = _client()
        r = c.post("/admin/apps/gmp_app/save", headers=_AUTH, data={
            "_part": "template", "template": "Common: {code}",
            "template_sms_out": "SMS: {kod}", "template_tg_user": "TG: {code}"})
        assert r.status_code == 200
        assert "field-error" in r.text
        for typed in ("Common: {code}", "SMS: {kod}", "TG: {code}"):
            assert typed in r.text
        assert store.verification_templates == ""
    finally:
        asyncio.run(close_db())


def test_the_apps_list_counts_a_rung_or_common_entry_as_an_sms_text():
    _db()
    try:
        _seed_apps("with_sms", "with_common", "tg_only")
        _set_templates([
            {"app_id": "with_sms", "route": "sms_out", "template": "S: {code_words}"},
            {"app_id": "with_common", "template": "C: {code}"},
            {"app_id": "tg_only", "route": "tg_user", "template": "T: {code}"},
        ])
        page = _client("en").get("/admin/apps", headers=_AUTH).text
        assert page.count("no — no code will be sent by SMS") == 1
        row = page[page.index('href="/admin/apps/tg_only"'):]
        assert row.index("no — no code will be sent by SMS") < row.index("</tr>")
    finally:
        asyncio.run(close_db())
