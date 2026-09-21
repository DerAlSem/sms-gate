"""Task 4.19 — the operator's document about the two paid rungs, held to the code.

A document is the one artefact here with no compiler and no caller, so it rots in exactly
one direction: silently, and towards being confidently wrong. The two ways it rots are a
setting renamed under it and a default changed under it, and both are mechanical to ask
about — so they are asked here rather than trusted to whoever next edits `settings_store`.

What is deliberately *not* asserted is the prose. A guard over wording would fail on every
honest edit and be proof-read away within a month, which is the fate of a guard that cries
wolf. What is asserted is every identifier and every number the document states as fact.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.settings_store import SPEC_BY_KEY
from app.verification import rule

DOC = Path(__file__).resolve().parents[1] / "docs" / "verification-rungs.md"

# The settings the document names, and the defaults it prints beside them. A key here with
# no default is one the document names without quoting its shipped value.
_NAMED_SETTINGS: dict[str, object] = {
    "operator_routes": None,                    # its default is asserted separately, below
    "verification_route_order": "call_in,sms_out,flash_call,tg_gateway,sms_in",
    "verification_paid_per_hour": 100,
    "verification_paid_per_day": 300,
    "tg_gateway_balance_floor": 10.0,
    "flash_call_balance_floor": 0.0,
    "verification_retention_days": 30,
    "operator_route_review_days": 30,
    "tg_gateway_token": None,
    # Both ship blank, and the document says so in prose. Registered with their
    # shipped value rather than with None so that giving either a non-blank default
    # fails here — a default the operator is told does not exist.
    "tg_gateway_callback_base": "",
    "tg_gateway_sender_username": "",
}


def _text() -> str:
    return DOC.read_text()


def test_every_setting_the_document_names_still_exists():
    """A renamed setting leaves the document telling an operator to open a page and change
    a field that is not there — and leaves them to conclude the document is wrong about
    everything else too."""
    missing = [key for key in _NAMED_SETTINGS if key not in SPEC_BY_KEY]
    assert missing == [], (
        f"docs/verification-rungs.md names settings that no longer exist: {missing}"
    )


def test_the_document_actually_names_them():
    """The control the guard above is empty without: a document that had stopped naming
    these keys would satisfy it perfectly, and the list here would be a record of what the
    document used to say."""
    text = _text()
    unnamed = [key for key in _NAMED_SETTINGS if f"`{key}`" not in text]
    assert unnamed == [], (
        f"these are registered here as named by the document and are not in it: {unnamed}. "
        f"Either the document dropped them — and this list is now a fiction — or they were "
        f"renamed in the prose without being renamed here"
    )


def test_every_default_the_document_prints_is_the_shipped_one():
    """The quieter rot: the setting survives, its default moves, and the document goes on
    stating the old number. An operator sizing a spend ceiling or a retention window reads
    it as fact, because there is nowhere else to read it from."""
    wrong = {}
    for key, printed in _NAMED_SETTINGS.items():
        if printed is None:
            continue
        shipped = SPEC_BY_KEY[key].default
        if shipped != printed:
            wrong[key] = f"document says {printed!r}, ships {shipped!r}"
    assert wrong == {}, (
        f"docs/verification-rungs.md prints defaults that have moved under it: {wrong}"
    )


def test_the_shipped_rule_in_the_document_is_the_shipped_rule():
    """The document quotes the rule verbatim, because "which operator goes where" is the
    one question an operator opens it for. Quoted text is the form that rots hardest: it
    looks authoritative precisely when it is stale.

    Compared as parsed data rather than as characters, so that reformatting the JSON in
    the document is not a failure while changing what it says is.
    """
    import json

    text = _text()
    block = re.search(r"```json\n(.*?)\n```", text, re.DOTALL)
    assert block, "the document no longer quotes the rule as a json block"
    assert json.loads(block.group(1)) == json.loads(rule.SHIPPED), (
        "the rule quoted in docs/verification-rungs.md is not the rule that ships"
    )


def test_the_document_names_the_wildcards_as_the_rule_spells_them():
    """`*` and `?` are the two entries an operator is most likely to get wrong, and `?`
    changed meaning on 20.09.2026 — it is "the lookup did not answer", not "a number we
    have not seen". A document still explaining the old meaning would be worse than none.
    """
    text = _text()
    assert f'**`"{rule.DEFAULT}"`**' in text and f'**`"{rule.UNKNOWN}"`**' in text
    assert "не удалось разрешить" in text, (
        "the document no longer says that `?` means the lookup failed to answer — the "
        "reading it replaced, 'a number nobody has written to yet', sends an operator to "
        "the wrong conclusion about every unrouted message"
    )
    assert f'`"{rule.REFUSE}"`' in text


def test_the_document_does_not_promise_a_free_second_send():
    """Measured 20.09.2026 and recorded in `captures/README.md`: the send answered the
    *same* `request_cost` as the ability check, an echo of the request's price, and whether
    a second charge was taken is not visible in the samples. The vendor's reference promises
    the second call is free; this gateway has not measured it.

    Guarded because the first draft of this document stated the promise as fact, and a
    budget built on it would be built on a vendor's word.
    """
    text = _text()
    assert "обещание вендора, а не наш замер" in text, (
        "the document no longer marks the free-second-send promise as unmeasured"
    )
