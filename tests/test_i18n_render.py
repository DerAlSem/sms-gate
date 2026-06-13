# tests/test_i18n_render.py
from types import SimpleNamespace

from app.admin.i18n import render, _ENVS, SUPPORTED


def _req(cookie=None):
    return SimpleNamespace(cookies=({"lang": cookie} if cookie else {}), headers={})


def test_one_env_per_supported_locale():
    assert set(_ENVS.keys()) == set(SUPPORTED)


def test_render_returns_html_with_context():
    resp = render("base.html", _req())
    assert resp.status_code == 200
    assert resp.media_type == "text/html"
    assert b"SMS Gate" in resp.body


def test_render_uses_english_env_with_cookie():
    resp = render("base.html", _req("en"))
    assert resp.status_code == 200
    assert b"SMS Gate" in resp.body


def test_render_falls_back_to_default_on_invalid_cookie():
    resp = render("base.html", _req("de"))
    assert resp.status_code == 200
