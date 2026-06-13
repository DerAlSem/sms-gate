# tests/test_i18n_locale.py
from types import SimpleNamespace

from app.admin.i18n import resolve_locale, get_translations, SUPPORTED, DEFAULT


def _req(cookie=None):
    return SimpleNamespace(cookies=({"lang": cookie} if cookie else {}))


def test_resolve_defaults_to_ru():
    assert DEFAULT == "ru"
    assert resolve_locale(_req()) == "ru"


def test_resolve_honors_supported_cookie():
    assert resolve_locale(_req("en")) == "en"


def test_resolve_rejects_unknown_cookie():
    assert resolve_locale(_req("zz")) == "ru"


def test_get_translations_ru_returns_translations_object():
    # Full msgid round-trip assertion deferred to Task 5/6 when Russian strings are seeded.
    tr = get_translations("ru")
    assert hasattr(tr, "gettext")


def test_get_translations_unknown_locale_is_nulltranslations():
    tr = get_translations("zz")
    assert tr.gettext("Anything") == "Anything"
