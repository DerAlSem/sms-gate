"""Task 3.2a — the contract handed to a consuming developer, held to the code.

`docs/verification-api.md` is the one artefact in this change with no compiler and no
caller: it is read by somebody outside this repository who cannot check it against
anything. So it rots in one direction only — silently, towards being confidently wrong —
and the reader finds out by shipping against it.

What is asserted here is every identifier and every number the document states as fact:
the doors, the vocabulary of routes, the words `check` can answer, the methods a
confirmation can name, the exact field names of the push, and the shipped defaults it
quotes. What is deliberately **not** asserted is the prose. A guard over wording fails on
every honest edit and gets proof-read away within a month.

The first guard is different in kind and is task 3.2: the document must print no telephone
number at all. A placeholder in a handed-over contract is not a typo — it is a number a
developer pastes into a release, and the person who owns it hears about it first.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from app.api import schemas
from app.api.router import router
from app.db import queries
from app.db.connection import close_db, init_db
from app.db.migrate import run_migrations
from app.settings_store import SPEC_BY_KEY, store
from app.verification.dispatch import push_verification
from app.verification.routes import ALL_ROUTES, CALL_IN, SMS_IN

DOC = Path(__file__).resolve().parents[1] / "docs" / "verification-api.md"

PHONE = "+79261234888"

# The doors the document documents, as it spells them, against the path the router
# actually registers. A door renamed under the document leaves a developer coding against
# a 404 with no way to tell that from their own mistake.
_DOORS = {
    ("POST", "/verifications"): "/verifications",
    ("POST", "/verifications/{id}/route"): "/verifications/{verification_id}/route",
    ("POST", "/verifications/{id}/check"): "/verifications/{verification_id}/check",
    ("GET", "/verifications/{id}"): "/verifications/{verification_id}",
}

# The numbers the document prints as fact, beside the setting that decides each. A default
# that moves under a quoted number is the quiet rot: the document goes on stating the old
# one, and there is nowhere else for the reader to read it from.
_QUOTED_DEFAULTS = {
    "verification_ttl_seconds": 300,
    "verification_max_attempts": 5,
    "inbound_dispatch_retries": 3,
    "inbound_dispatch_timeout": 10.0,
    "gateway_msisdn": "",
}


def _text() -> str:
    return DOC.read_text()


def _run(body):
    async def go():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("app1", "token-app1")
        await store.load()
        await store.set_many({
            "delivery_dispatch": '[{"app_id":"app1","webhook_url":"https://x/hook"}]',
            "gateway_msisdn": "+79990001122",
        })
        return await body()

    try:
        return asyncio.run(go())
    finally:
        asyncio.run(close_db())


def _backticked(section: str) -> set[str]:
    return set(re.findall(r"`([a-z_]+)`", section))


def _section(title: str, *, to_first_subsection: bool = False) -> str:
    text = _text()
    start = text.index(title)
    rest = text[start + len(title):]
    end = rest.find("\n### ") if to_first_subsection else rest.find("\n## ")
    return rest if end < 0 else rest[:end]


# --- task 3.2: no telephone number, anywhere ---------------------------------------------

def test_the_document_prints_no_telephone_number():
    """The whole of task 3.2, mechanically.

    The draft this replaces carried two placeholders — one in a JSON example and one in
    screen copy — and the fix was never "use the real one". For the paid call there is no
    gateway number at all, because the vendor dials from a number nobody knows in advance;
    for the two rungs the subscriber reaches, the gateway holds a number only when an
    operator has entered `gateway_msisdn`, and it ships blank.

    So the document quotes digits nowhere, and the rule is enforced on the shape of a
    number rather than on the two strings that happened to be in the draft: the next
    placeholder will be a different number, and a guard listing yesterday's is a guard
    that passes on tomorrow's.
    """
    runs = re.findall(r"\d{5,}", _text())
    assert runs == [], (
        f"docs/verification-api.md prints digit runs that read as a telephone number: "
        f"{runs}. A contract is handed to somebody who will paste what it prints"
    )


def test_the_document_says_why_it_prints_none():
    """The positive control the guard above is empty without.

    A document that had simply stopped discussing numbers would satisfy it perfectly, and
    the reader would be left assuming the gateway has a number it does not have.
    """
    text = _text()
    assert "`gateway_msisdn`" in text and "ships **blank**" in text, (
        "the document no longer explains that the gateway's own number is a setting that "
        "ships blank — without that sentence, printing no number reads as an omission"
    )


# --- the doors -----------------------------------------------------------------------

def test_every_door_the_document_documents_still_exists():
    registered = {(method, route.path)
                  for route in router.routes
                  for method in getattr(route, "methods", set())}
    missing = [spelled for spelled, path in _DOORS.items()
               if (spelled[0], path) not in registered]
    assert missing == [], (
        f"docs/verification-api.md documents doors the router no longer serves: {missing}"
    )


def test_the_document_actually_names_them():
    """The control: a document that had dropped a door would pass the guard above."""
    text = _text()
    unnamed = [f"{method} {path}" for method, path in _DOORS
               if f"{method} {path}" not in text]
    assert unnamed == [], (
        f"these are registered here as documented and are not in the document: {unnamed}"
    )


# --- the vocabulary of routes ---------------------------------------------------------

def _tabled_routes() -> set[str]:
    """Every name the contract's vocabulary table puts in its **route** column.

    Read from the column rather than from the section's backticks, and the difference is
    the whole guard: the section also names settings, and a predicate that picked route
    names out of the prose would have to recognise one by its spelling. Asked from the
    contrary instead — everything in that column is claimed to be a route, so everything
    in it has to be one.
    """
    section = _section("## What a deployment can carry today")
    names: set[str] = set()
    for line in section.splitlines():
        if not line.startswith("| "):
            continue
        first = line.split("|")[1]
        names |= set(re.findall(r"`([a-z_]+)`", first))
    return names


def test_the_route_vocabulary_is_the_gateway_s_own():
    """Flat, and one list. The owner settled the vocabulary on 18.09.2026 as a single flat
    field, and this guards it in both directions at once.

    A name the gateway knows and the contract does not is a route a consumer will be
    offered and will not recognise. A name the contract knows and the gateway does not is
    a route a consumer will ask for and be refused — and the second is the one a
    hand-written table produces, because a table is edited by somebody thinking about what
    ought to exist.
    """
    assert _tabled_routes() == set(ALL_ROUTES), (
        f"the contract's route table and the gateway's vocabulary have drifted apart: "
        f"only in the contract {sorted(_tabled_routes() - ALL_ROUTES)}, "
        f"only in the gateway {sorted(ALL_ROUTES - _tabled_routes())}"
    )


# --- what `check` can answer ----------------------------------------------------------

def test_every_outcome_the_check_door_answers_is_documented():
    """Driven, not read off a comment. Each of the five is provoked for real, because a
    documented vocabulary is exactly the thing that quietly grows a sixth member.
    """
    async def body():
        seen = set()

        vid = await queries.create_verification("app1", PHONE, code="1234",
                                                ttl_seconds=300)
        seen.add(await queries.check_verification(vid, "app1", code="9999",
                                                  max_attempts=5))
        seen.add(await queries.check_verification(vid, "app1", code="1234",
                                                  max_attempts=5))
        seen.add(await queries.check_verification(vid, "app1", code="1234",
                                                  max_attempts=5))

        spent = await queries.create_verification("app1", PHONE, code="2345",
                                                  ttl_seconds=300)
        # The attempt that reaches the ceiling still answers `wrong_code` — it is the
        # *next* offer, to a verification the ceiling has already ended, that answers
        # `no_attempts_left`. Two calls, because one of them does not reach the word.
        seen.add(await queries.check_verification(spent, "app1", code="9999",
                                                  max_attempts=1))
        seen.add(await queries.check_verification(spent, "app1", code="2345",
                                                  max_attempts=1))

        dead = await queries.create_verification("app1", PHONE, code="3456",
                                                 ttl_seconds=-1)
        seen.add(await queries.check_verification(dead, "app1", code="3456",
                                                  max_attempts=5))
        return seen

    outcomes = _run(body)
    assert outcomes == {"confirmed", "wrong_code", "already_confirmed",
                        "no_attempts_left", "expired"}, outcomes

    section = _section("## POST /verifications/{id}/check")
    undocumented = sorted(o for o in outcomes if f"`{o}`" not in section)
    assert undocumented == [], (
        f"the check door answers these and the contract does not document them: "
        f"{undocumented}"
    )


def test_the_check_section_documents_the_missing_verification_as_a_404():
    """`not_found` is the sixth word the query layer can answer and the one the door turns
    into a status code. A contract listing it beside the others would send a consumer
    looking for it in a `200` body."""
    section = _section("## POST /verifications/{id}/check")
    assert "`404`" in section
    assert "`not_found`" not in section, (
        "the contract lists `not_found` as an outcome; the door answers it as a 404 and "
        "it never appears in a body"
    )


# --- what a confirmation can name as its method ---------------------------------------

def test_every_method_a_confirmation_can_name_is_documented():
    """`method` is not `route`, and its vocabulary is its own: two of the three words
    coincide with a route name and the third, `check`, is a route name nowhere. A contract
    that documented the route vocabulary here would be telling a consumer to expect
    `tg_gateway` in a field that can never hold it."""
    async def body():
        seen = set()

        typed = await queries.create_verification("app1", PHONE, code="1234",
                                                  ttl_seconds=300)
        await queries.check_verification(typed, "app1", code="1234", max_attempts=5)
        seen.add((await queries.get_verification(typed, "app1"))["confirmed_by"])

        called = await queries.create_verification("app1", PHONE, code="2345",
                                                   ttl_seconds=300)
        await queries.select_route(called, "app1", route=CALL_IN)
        await queries.confirm_by_inbound_call(PHONE, method=CALL_IN)
        seen.add((await queries.get_verification(called, "app1"))["confirmed_by"])

        texted = await queries.create_verification("app1", PHONE, code="3456",
                                                   ttl_seconds=300)
        await queries.select_route(texted, "app1", route=SMS_IN)
        await queries.confirm_by_inbound_message(PHONE, code="3456", method=SMS_IN)
        seen.add((await queries.get_verification(texted, "app1"))["confirmed_by"])
        return seen

    methods = _run(body)
    assert methods == {"check", CALL_IN, SMS_IN}, methods

    section = _section("### `method` is not `route`")
    undocumented = sorted(m for m in methods if f"`{m}`" not in section)
    assert undocumented == [], (
        f"a confirmation can name these methods and the contract does not: {undocumented}"
    )


# --- the push -------------------------------------------------------------------------

def test_the_push_body_is_the_one_the_gateway_actually_sends(monkeypatch):
    """Captured off the real function rather than described. The field names are the whole
    of what a receiver keys on, and `verification_id` in particular is load-bearing: the
    message contract names its subject in `id`, both bodies arrive at the same URL, and
    both use the words `failed` and `expired`.
    """
    sent: list[dict] = []

    async def fake_deliver(route, payload):
        sent.append(payload)
        return True, None

    import app.verification.dispatch as dispatch_mod
    monkeypatch.setattr(dispatch_mod, "deliver", fake_deliver)

    async def body():
        await push_verification(9, "app1", "confirmed", method="call_in", reason=None)
        return sent

    payloads = _run(body)
    assert len(payloads) == 1, payloads
    payload = payloads[0]

    assert "id" not in payload, (
        "the verification push carries an `id` again; a receiver keyed on `id` and "
        "`status` will mark an unrelated message"
    )

    section = _section("## The push")
    undocumented = sorted(k for k in payload if f"`{k}`" not in section)
    assert undocumented == [], (
        f"the push carries fields the contract does not document: {undocumented}"
    )
    assert "| `id` |" not in section, (
        "the contract documents an `id` field on the push, which the gateway does not send"
    )


def test_the_contract_documents_no_push_field_that_is_not_sent(monkeypatch):
    """The other direction, and the one a reader pays for: a field promised and never sent
    is a receiver waiting on something that is never coming."""
    sent: list[dict] = []

    async def fake_deliver(route, payload):
        sent.append(payload)
        return True, None

    import app.verification.dispatch as dispatch_mod
    monkeypatch.setattr(dispatch_mod, "deliver", fake_deliver)

    async def body():
        await push_verification(9, "app1", "failed", method=None, reason="whatever")
        return sent

    payload = _run(body)[0]
    section = _section("## The push")
    promised = set(re.findall(r"^\| `([a-z_]+)` \|", section, re.MULTILINE))
    assert promised == set(payload), (
        f"the contract's push table and the body the gateway sends have drifted apart: "
        f"table {sorted(promised)}, body {sorted(payload)}"
    )


# --- the poll's own fields ------------------------------------------------------------

def test_the_poll_table_names_exactly_the_fields_the_answer_carries():
    """`GET /verifications/{id}` is the authoritative door, and its table is what a
    consumer builds its model from. `phone` and `id` are excluded from the comparison
    only because the table explains them in prose above it rather than as rows."""
    section = _section("## GET /verifications/{id}", to_first_subsection=True)
    tabled = set(re.findall(r"^\| `([a-z_]+)` \|", section, re.MULTILINE))
    carried = set(schemas.VerificationStatusResponse.model_fields)
    assert tabled <= carried, (
        f"the contract tables fields the poll does not carry: {sorted(tabled - carried)}"
    )
    assert carried - tabled <= {"id", "phone"}, (
        f"the poll carries fields the contract's table does not mention: "
        f"{sorted(carried - tabled - {'id', 'phone'})}"
    )


def test_the_statuses_the_contract_lists_are_the_ones_the_column_holds():
    """Four words, and the column's comment is not the guard — the doors are. `pending` is
    what creation answers, and the other three are the terminal ones the sweep announces.
    """
    section = _section("## GET /verifications/{id}")
    for status in ("pending", "confirmed", "failed", "expired"):
        assert f"`{status}`" in section, status
    assert schemas.VerificationCreateResponse.model_fields["status"] is not None


# --- the numbers ----------------------------------------------------------------------

def test_every_setting_the_document_names_still_exists():
    missing = [key for key in _QUOTED_DEFAULTS if key not in SPEC_BY_KEY]
    assert missing == [], (
        f"docs/verification-api.md names settings that no longer exist: {missing}"
    )


def test_every_default_the_document_quotes_is_the_shipped_one():
    wrong = {}
    for key, printed in _QUOTED_DEFAULTS.items():
        shipped = SPEC_BY_KEY[key].default
        if shipped != printed:
            wrong[key] = f"document says {printed!r}, ships {shipped!r}"
    assert wrong == {}, (
        f"docs/verification-api.md quotes defaults that have moved under it: {wrong}"
    )


def test_the_document_prints_those_numbers_where_a_reader_can_see_them():
    """The control: the guard above compares the document's claims against the code via a
    table in this file, and would pass just as well if the document had stopped making the
    claims at all."""
    text = _text()
    for printed in ("300 s", "**5**", "3 attempts", "10 s"):
        assert printed in text, (
            f"the contract no longer prints {printed!r}; the table in this file is then a "
            f"record of what it used to say"
        )
    assert "five minutes" in text


# --- the two things a reader must not have to discover by shipping ---------------------

def test_the_contract_says_the_push_is_a_minute_behind():
    """Measured off the loop rather than assumed: terminal states reach an application on
    a sixty-second sweep, so a confirmation that happened a second ago can be a minute from
    the webhook. A consumer that opens its barrier on the push and not on the poll makes a
    person stand there for it."""
    assert "one-minute tick" in _text(), (
        "the contract no longer warns that the push rides a one-minute sweep — the "
        "reader's own test will pass and their queue will be a minute late in production"
    )


def test_the_contract_says_the_telegram_rung_is_placed_and_says_it_because_it_is():
    """Inverted 21.09.2026, when the door that walks the ladder landed (4.56).

    This guard used to require the contract to **warn** that selecting the Telegram rung
    placed nothing. The warning was true and is now false, and a contract carrying it would
    understate what the gateway does — so the guard is turned round rather than deleted: what
    it has always been about is the document agreeing with the code, and it checks the same
    join from the other side.

    The join is read off the code, not off a list: the rung is placed exactly when something
    in `app/` outside the ladder itself calls `ladder.walk`. A door removed later would put
    the promise back into the document silently, and that is what this catches.
    """
    import ast
    from pathlib import Path

    walkers = []
    root = Path(__file__).resolve().parent.parent / "app"
    for path in root.rglob("*.py"):
        if path.name == "ladder.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "walk"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "ladder"):
                walkers.append(str(path.relative_to(root)))
    assert walkers, (
        "nothing in app/ walks the ladder any more — the Telegram rung can be selected and "
        "placed by nobody, and the contract below now promises otherwise"
    )

    text = _text()
    assert "places nothing" not in text.replace("used to be offered and then place nothing", ""), (
        "the contract still warns that the rung places nothing, and it does place it"
    )
    assert "names the rung that carried" in text or "names the rung that actually carried" \
        in text, "the contract does not say that the rung answered is the rung that carried"
