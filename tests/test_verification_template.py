# tests/test_verification_template.py
"""The per-application text of an SMS-carried code, and what the save refuses.

Every refusal here happens at save time. The alternative is discovering at compose time
that a template drops the code, and by compose time a person is at a barrier — on a
ladder, after money has been spent.
"""

import asyncio
import base64

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.admin.router import router
from app.db.connection import init_db, close_db
from app.db.migrate import run_migrations
from app.settings_store import store
from app.verification import template

_AUTH = {"Authorization": "Basic " + base64.b64encode(b"admin:change-me").decode()}


def _db():
    async def run():
        await init_db(":memory:")
        await run_migrations()
        await store.load()
    asyncio.run(run())


def _entry(text: str, app_id: str = "sp_app") -> str:
    import json
    return json.dumps([{"app_id": app_id, "template": text}], ensure_ascii=False)


# ---- what a template must carry -------------------------------------------------

def test_a_template_with_no_placeholder_is_refused():
    with pytest.raises(ValueError) as e:
        template.validate(_entry("SokolParking: your code"))
    assert "code" in str(e.value)


def test_a_template_carrying_the_code_twice_is_refused():
    """Twice is not a harmless duplicate: the person is shown two numbers to type."""
    with pytest.raises(ValueError) as e:
        template.validate(_entry("SokolParking: {code} ({code})"))
    assert "once" in str(e.value) or "twice" in str(e.value)


def test_an_unknown_placeholder_is_refused_and_named():
    with pytest.raises(ValueError) as e:
        template.validate(_entry("SokolParking: {code} for {name}"))
    assert "name" in str(e.value)


def test_a_template_with_exactly_one_code_is_accepted():
    template.validate(_entry("SokolParking: {code}"))
    template.validate(_entry("Ваш код: {code}"))


def test_an_empty_template_is_refused_as_empty_rather_than_as_placeholderless():
    """Blank is not "no template" — no template is the absence of an entry.

    The reason is what this asserts, not the refusal: a blank template is refused by the
    placeholder count too, so a test asserting only `ValueError` would pass with the
    blank case unhandled and tell an operator their text is missing a `{code}` when what
    it is missing is text.
    """
    for blank in ("", "   "):
        with pytest.raises(ValueError) as e:
            template.validate(_entry(blank))
        assert "template is required" in str(e.value), str(e.value)


def test_an_entry_with_no_app_id_is_refused():
    with pytest.raises(ValueError) as e:
        template.validate('[{"template": "code {code}"}]')
    assert "app_id" in str(e.value)


def test_one_application_named_twice_is_refused():
    """Which of the two wins would be decided by the order of the list, invisibly."""
    with pytest.raises(ValueError) as e:
        template.validate(
            '[{"app_id": "sp_app", "template": "a {code}"},'
            ' {"app_id": "sp_app", "template": "b {code}"}]')
    assert "sp_app" in str(e.value)


def test_a_stored_value_that_is_not_a_list_is_refused():
    with pytest.raises(ValueError):
        template.validate('{"app_id": "sp_app", "template": "{code}"}')
    with pytest.raises(ValueError):
        template.validate("not json at all")


def test_the_empty_setting_is_the_absence_of_every_template():
    template.validate("")
    assert template.parse("") == {}


# ---- what it composes ------------------------------------------------------------

def test_the_text_is_the_application_s_own_and_there_is_no_default():
    _db()
    try:
        asyncio.run(store.set_many({template.KEY: _entry("SokolParking: {code}")}))
        assert template.for_app("sp_app") == "SokolParking: {code}"
        assert template.for_app("gmp_app") is None
        assert template.compose("SokolParking: {code}", "1234") == "SokolParking: 1234"
    finally:
        asyncio.run(close_db())


def test_an_unreadable_setting_is_never_read_as_an_absent_template():
    """A template read as absent refuses the application; read as empty it sends a person
    a message with nothing in it to type. Neither is a reading, so it raises."""
    with pytest.raises(template.UnreadableTemplates):
        template.parse("{not json")


def test_a_pasted_value_is_stored_as_it_will_be_read():
    assert '"app_id": "sp_app"' in template.normalize(
        '[{"app_id": "  sp_app  ", "template": "x {code}"}]')


def test_composing_never_interprets_the_rest_of_the_template():
    """A template is operator-supplied text. `str.format` would read every brace in it as
    a field — `{0}` reaches into the arguments and `{a.b}` into attributes — and would
    raise on the ones it cannot resolve, turning a wording typo into a failed send."""
    assert template.compose("a {0} and {code}", "77") == "a {0} and 77"
    assert template.compose("{x.y} {code}", "77") == "{x.y} 77"


# ---- the save itself -------------------------------------------------------------

def test_the_console_refuses_the_save_and_changes_nothing():
    _db()
    try:
        app = FastAPI()
        app.include_router(router)
        c = TestClient(app)
        good = _entry("SokolParking: {code}")
        r = c.post("/admin/settings", headers=_AUTH, follow_redirects=False,
                   data={template.KEY: good})
        assert r.status_code in (302, 303)
        assert template.for_app("sp_app") == "SokolParking: {code}"

        r = c.post("/admin/settings", headers=_AUTH, follow_redirects=False,
                   data={template.KEY: _entry("SokolParking: no code here")})
        assert r.status_code == 200                    # re-rendered with the reason
        assert template.KEY in r.text
        # and the template in force is untouched
        assert template.for_app("sp_app") == "SokolParking: {code}"

        # a pasted app_id is stored as it will be read, and the body exactly as written
        r = c.post("/admin/settings", headers=_AUTH, follow_redirects=False,
                   data={template.KEY: _entry(" Код: {code} ", app_id="  sp_app  ")})
        assert r.status_code in (302, 303)
        assert template.for_app("sp_app") == " Код: {code} "
        # the stored form, not the lookup: `parse` strips `app_id` on read as well, so a
        # lookup succeeds whether or not the save normalised anything. What the save
        # decides is the text an operator re-reads on the page.
        stored = store.get(template.KEY)
        assert '"app_id": "sp_app"' in stored, stored
        assert '" Код: {code} "' in stored, stored
    finally:
        asyncio.run(close_db())
