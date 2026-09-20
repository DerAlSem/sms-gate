# tests/test_vendor_credentials.py
"""What the console may say about a vendor credential, and what it may never render.

The settings page is the only place a credential is entered, and it is therefore the
only place one can leak. The guard is written over the *set* of credentials rather than
over `tg_gateway_token` by name: the second vendor's key does not exist yet (task 1.1),
and a guard naming one key would pass on the day the other arrives unprotected.
"""

import asyncio
import base64
import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.admin.router import router
from app.db.connection import init_db, close_db
from app.db.migrate import run_migrations
from app.settings_store import SETTINGS_SPEC, store

_AUTH = {"Authorization": "Basic " + base64.b64encode(b"admin:change-me").decode()}

# What a key is called when it holds a credential. Checked rather than assumed, because
# the leak this guards against arrives as a *new* setting declared without `is_secret`,
# and a guard that enumerates today's keys is silent on exactly that day.
_CREDENTIAL_SUFFIXES = ("_token", "_key", "_secret", "_password")

# The console is bilingual and its default locale is Russian, so a guard written against
# the English wording alone would pass while the Russian page said nothing. Both spellings
# of each verdict, and the page is read in both languages.
_SAYS_CONFIGURED = {"ru": "задано", "en": "configured"}
_SAYS_NOT_SET = {"ru": "не задано", "en": "not set"}


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


def _credential_keys() -> list[str]:
    return [s.key for s in SETTINGS_SPEC if s.key.endswith(_CREDENTIAL_SUFFIXES)]


def _field(html: str, key: str) -> str:
    """The one input tag that carries this setting, or an assertion naming what is wrong."""
    found = re.findall(rf'<(?:input|textarea)\s+name="{re.escape(key)}"[^>]*>', html)
    assert len(found) == 1, f"{key}: expected one field on the page, found {len(found)}"
    return found[0]


def test_a_setting_named_like_a_credential_is_declared_secret():
    """`is_secret` is what keeps a value off the page; a credential without it is rendered."""
    keys = _credential_keys()
    assert keys, "no credential settings found — the naming convention this guard reads has moved"
    by_key = {s.key: s for s in SETTINGS_SPEC}
    not_secret = [k for k in keys if not by_key[k].is_secret]
    assert not not_secret, f"credential settings declared without is_secret: {not_secret}"


def test_the_settings_page_says_configured_and_renders_no_value():
    _db()
    try:
        keys = _credential_keys()
        secret = {key: f"SECRET-VALUE-{i}" for i, key in enumerate(keys)}

        async def seed():
            await store.set_many(secret)
        asyncio.run(seed())

        for locale, says in _SAYS_CONFIGURED.items():
            r = _client(locale).get("/admin/settings", headers=_AUTH)
            assert r.status_code == 200
            for key in keys:
                assert key in r.text, f"{key}: the console does not report this credential at all"
                assert secret[key] not in r.text, f"{key} [{locale}]: its value reached the page"
                tag = _field(r.text, key)
                assert "value=" not in tag, f"{key} [{locale}]: rendered with a value attribute — {tag}"
                assert says in tag, f"{key} [{locale}]: set, but the page does not say so — {tag}"
    finally:
        asyncio.run(close_db())


def test_an_unset_credential_is_reported_as_not_set():
    _db()
    try:
        for locale, says in _SAYS_NOT_SET.items():
            r = _client(locale).get("/admin/settings", headers=_AUTH)
            assert r.status_code == 200
            for key in _credential_keys():
                tag = _field(r.text, key)
                assert says in tag, f"{key} [{locale}]: unset, but the page does not say so — {tag}"
    finally:
        asyncio.run(close_db())


def test_the_value_never_reaches_the_template_at_all():
    """Not the page but the row handed to it.

    The page is safe today because the template ignores `value` for a secret field, so a
    view that passed the credential on would still render nothing. That makes the whole
    guarantee rest on one line of markup: the next person to add a field type there
    inherits a variable holding a live token. The row is what the view produces directly,
    so it is what this asserts.
    """
    _db()
    try:
        from app.admin.router import _settings_view_rows

        keys = _credential_keys()
        secret = {key: f"SECRET-VALUE-{i}" for i, key in enumerate(keys)}
        asyncio.run(store.set_many(secret))

        rows = {row["key"]: row for fields in _settings_view_rows().values() for row in fields}
        for key in keys:
            row = rows[key]
            assert row["value"] != secret[key], f"{key}: the view hands its value to the page"
            assert not row["value"], f"{key}: the view hands something derived from it — {row['value']!r}"
            assert row["configured"] is True, f"{key}: set, but the view does not say so"
    finally:
        asyncio.run(close_db())
