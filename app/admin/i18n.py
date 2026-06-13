from __future__ import annotations

import gettext
import io
from pathlib import Path
from typing import Any

import jinja2
from babel.messages.mofile import write_mo
from babel.messages.pofile import read_po
from starlette.responses import HTMLResponse

from app.admin.timefmt import to_msk

SUPPORTED: tuple[str, ...] = ("ru", "en")
DEFAULT: str = "ru"

_TRANSLATIONS_DIR = Path(__file__).parent / "translations"


def get_translations(locale: str) -> gettext.NullTranslations:
    """Load a locale's gettext catalog. Compiles the .po to a .mo in memory
    (Jinja's install_gettext_translations needs a GNUTranslations, which reads a
    binary .mo stream). Missing catalog -> NullTranslations (msgids pass through)."""
    po_path = _TRANSLATIONS_DIR / locale / "LC_MESSAGES" / "messages.po"
    if not po_path.exists():
        return gettext.NullTranslations()
    with po_path.open("rb") as fp:
        catalog = read_po(fp)
    buf = io.BytesIO()
    write_mo(buf, catalog)
    buf.seek(0)
    return gettext.GNUTranslations(buf)


def resolve_locale(request: Any) -> str:
    """Pick the locale from the `lang` cookie, falling back to DEFAULT."""
    lang = request.cookies.get("lang")
    return lang if lang in SUPPORTED else DEFAULT


_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _build_env(locale: str) -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(_TEMPLATES_DIR),
        extensions=["jinja2.ext.i18n"],
        autoescape=True,
    )
    env.install_gettext_translations(get_translations(locale), newstyle=True)
    env.filters["msk"] = to_msk
    return env


# Built at import time so render tests work without running lifespan.
_ENVS: dict[str, jinja2.Environment] = {loc: _build_env(loc) for loc in SUPPORTED}


def render(template_name: str, request: Any, ctx: dict | None = None) -> HTMLResponse:
    """Render a template in the request's locale. The only admin render path."""
    locale = resolve_locale(request)
    context = dict(ctx or {})
    context["request"] = request
    context["current_locale"] = locale
    html = _ENVS[locale].get_template(template_name).render(context)
    return HTMLResponse(html)
