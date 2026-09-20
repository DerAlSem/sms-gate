"""A refusal stops looking like a fault — on the page, where a person reads it.

Three of the fourteen rows are permanently unsuccessful on a perfectly healthy modem.
A page that is partly red whenever it is opened teaches its reader that red means
nothing there, and the next red row — the one that is a fault — is read the same way.
"""

import base64
import re
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.admin.router import router
from app.modem.parser import VALUE, REFUSAL, SILENCE, FAILURE

_AUTH = {"Authorization": "Basic " + base64.b64encode(b"admin:change-me").decode()}

_ROWS = [
    {"key": "gateway", "cmd": "—", "parsed": {"voice_route": "available"}},
    {"key": "sim", "cmd": "AT+CPIN?", "raw": "+CME ERROR: 13",
     "error": "AT+CPIN?: +CME ERROR 13 (SIM failure)", "outcome": FAILURE},
    {"key": "ims_reg", "cmd": "AT+CIREG?", "raw": "ERROR",
     "error": "AT+CIREG?: modem returned ERROR", "outcome": REFUSAL},
    {"key": "clip", "cmd": "AT+CLIP?",
     "error": "no response from modem (timeout)", "outcome": SILENCE},
    {"key": "ims", "cmd": 'AT+QCFG="ims"', "raw": '+QCFG: "ims",1,1', "outcome": VALUE,
     "parsed": {"ims_conf": 1, "config": "enabled compulsorily",
                "volte_cap": 1, "volte": "VoLTE enabled"}},
]


class FakeModem:
    async def collect_diagnostics(self):
        return _ROWS


def _page(locale=None):
    app = FastAPI()
    app.include_router(router)
    app.state.modem = FakeModem()
    c = TestClient(app)
    headers = dict(_AUTH)
    if locale:
        headers["Cookie"] = f"lang={locale}"
    return c.get("/admin/modem", headers=headers).text


def _row(html: str, key: str) -> str:
    """The one table row whose first cell names `key`."""
    rows = re.findall(r"<tr>(.*?)</tr>", html, re.S)
    match = [r for r in rows if re.search(rf"<td>\s*{re.escape(key)}\s", r)]
    assert len(match) == 1, f"{key}: {len(match)} rows"
    return match[0]


def test_the_fault_style_exists_at_all():
    """Without it, "not in the fault style" is satisfied by a page that styles nothing —
    and a fault and a refusal go on looking identical."""
    css = Path("app/admin/templates/base.html").read_text(encoding="utf-8")
    assert re.search(r"\.err\s*\{", css), "the page has no style for a fault"


def test_a_failed_sim_is_still_a_fault():
    """The positive control. Without it, an implementation that renders everything as
    "not measured" passes — and this is the reading that named the 2026-09-06 outage."""
    assert 'class="err"' in _row(_page(), "sim")


def test_a_refusal_is_not_in_the_fault_style():
    row = _row(_page(), "ims_reg")
    assert 'class="err"' not in row
    assert 'class="soft"' in row
    assert "refused" in _row(_page("en"), "ims_reg").lower()


def test_a_refusal_shows_what_the_modem_answered():
    """So a reader can tell a firmware without the command from a gateway that has
    stopped asking properly."""
    assert "ERROR" in _row(_page(), "ims_reg")


def test_a_refusal_does_not_claim_the_firmware_lacks_the_command():
    """The page says what happened, not why. That inference is wrong for any command the
    modem refuses for a reason of its own — and it must be absent in both languages,
    since a claim only one reader sees is still a claim."""
    for locale, guesses in (
        ("en", ("not supported", "unsupported", "firmware", "unknown command")),
        ("ru", ("не поддерж", "не уме", "прошивк", "нет такой команды")),
    ):
        row = _row(_page(locale), "ims_reg").lower()
        for guess in guesses:
            assert guess not in row, (locale, guess)


def test_a_silence_is_distinct_from_a_refusal_and_from_a_fault():
    row = _row(_page(), "clip")
    assert 'class="err"' not in row
    assert row != _row(_page(), "ims_reg").replace("ims_reg", "clip")
    english = _row(_page("en"), "clip").lower()
    assert "refused" not in english
    assert "measur" in english


def test_a_value_still_renders_its_reading():
    row = _row(_page(), "ims")
    assert "enabled compulsorily" in row
    assert "VoLTE enabled" in row


def test_the_page_carries_the_voice_route_from_the_gateway_row():
    assert "voice_route" in _page()


def test_the_new_strings_are_translated():
    ru = _page(locale="ru")
    assert re.search(r"[А-Яа-яЁё]", _row(ru, "ims_reg")), "refusal is untranslated"
    assert re.search(r"[А-Яа-яЁё]", _row(ru, "clip")), "silence is untranslated"
