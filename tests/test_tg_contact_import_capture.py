"""SG-36 — why `tg_user` does not import a contact after an empty `ResolvePhone`.

The fixture `tests/fixtures/tg_contact_import.json` is what Telegram answered
`@gmplus_support` for an open number, a number with no account and two numbers hidden from
lookup by phone, one of them the person behind the live `gmp_app` miss of 26.09. The step
"ImportContacts → send → DeleteContacts" would be worth building only if import ever found
someone resolve did not; this pins that it never did, so that a new capture which says
otherwise fails here instead of going unnoticed.
"""
import json
from pathlib import Path

CAPTURE = Path(__file__).parent / "fixtures" / "tg_contact_import.json"


def _cases():
    return json.loads(CAPTURE.read_text(encoding="utf-8"))["cases"]


def test_the_capture_covers_open_absent_and_hidden():
    assert {c["case"] for c in _cases()} == {"open", "no_account", "hidden"}


def test_import_never_finds_whom_resolve_missed():
    for case in _cases():
        resolved = bool(case["resolve_phone"].get("users"))
        imported = case["import_contacts"]["users"] > 0
        assert imported == resolved, case["case"]


def test_numbers_in_the_capture_are_redacted():
    for case in _cases():
        assert "…" in case["phone"] and len(case["phone"]) <= 8
