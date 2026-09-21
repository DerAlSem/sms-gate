"""An open verification ends by itself, and its end is announced.

An expiry computed only when somebody next asks never fires for the case that matters.
The person who never got the call has no reason to come back with a code, so nothing
triggers the lazy check and the application holds a session open for ever, waiting on an
answer that will not be computed.

The second half is harder than the sweep and is why the enumerating guard at the bottom of
this file exists: the sweep is not the only writer of a terminal state. A confirmation
arrives from a call, an exhausted attempt count fails a verification, a route dies under an
open one. Every one of them owes the application a word, and "every one" is a claim that
rots the moment somebody adds the next writer.
"""

import ast
import asyncio
import re
from pathlib import Path

import pytest

import app.verification.dispatch as dispatch_mod
from app.db import queries
from app.db.connection import close_db, get_db, init_db
from app.db.migrate import run_migrations
from app.settings_store import store
from app.verification.dispatch import announce_verification_outcomes
from app.verification.routes import CALL_IN, SMS_IN

PHONE = "+79261234888"


def _run(body):
    async def go():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("app1", "token-app1")
        await store.load()
        await store.set_many({
            "delivery_dispatch": '[{"app_id":"app1","webhook_url":"https://x/hook"}]',
            # Both rungs need a number for the subscriber to reach; without it neither is
            # offerable and every re-proof below would read as a route that had died.
            "gateway_msisdn": "+79990001122",
        })
        return await body()

    try:
        return asyncio.run(go())
    finally:
        asyncio.run(close_db())


@pytest.fixture
def pushed(monkeypatch):
    """Every payload the gateway tried to push, without a network."""
    sent = []

    async def fake_deliver(route, payload):
        sent.append(payload)
        return True, None

    monkeypatch.setattr(dispatch_mod, "deliver", fake_deliver)
    return sent


async def _open(route=CALL_IN, ttl=300, code="1234"):
    vid = await queries.create_verification("app1", PHONE, code=code, ttl_seconds=ttl)
    await queries.select_route(vid, "app1", route=route)
    return vid


# --- the sweep ---------------------------------------------------------------------------

def test_a_verification_nobody_came_back_for_is_expired_and_announced(pushed):
    async def body():
        vid = await _open(ttl=-1)
        await announce_verification_outcomes()
        return vid

    vid = _run(body)
    assert [(p["verification_id"], p["status"]) for p in pushed] == [(vid, "expired")]


def test_the_push_cannot_be_mistaken_for_a_message(pushed):
    """A receiver that cannot tell a verification id from a message id will eventually
    mark the wrong thing delivered."""
    async def body():
        await _open(ttl=-1)
        await announce_verification_outcomes()

    _run(body)
    assert pushed[0]["object"] == "verification"


def test_an_expiry_is_announced_once_and_not_again(pushed):
    async def body():
        await _open(ttl=-1)
        await announce_verification_outcomes()
        await announce_verification_outcomes()

    _run(body)
    assert len(pushed) == 1, pushed


def test_a_verification_still_open_is_not_announced(pushed):
    """The positive control for the sweep: a rule that announces everything has not
    distinguished the ended from the waiting."""
    async def body():
        await _open(ttl=300)
        await announce_verification_outcomes()

    _run(body)
    assert pushed == []


# --- what the announcement says -----------------------------------------------------------

def test_a_confirmation_names_the_method_that_proved_it(pushed):
    """7.5 — in the push as in the poll. The methods are not equally strong, and an
    application whose stakes do not tolerate the weakest must be able to see what it got
    rather than assume the strongest."""
    async def body():
        await _open()
        await queries.confirm_by_inbound_call(PHONE, method=CALL_IN)
        await announce_verification_outcomes()

    _run(body)
    assert pushed[0]["status"] == "confirmed"
    assert pushed[0]["method"] == CALL_IN


def test_no_announcement_ever_carries_the_code(pushed):
    async def body():
        await _open(route=SMS_IN)
        await queries.confirm_by_inbound_message(PHONE, code="1234", method=SMS_IN)
        await announce_verification_outcomes()

    _run(body)
    assert "code" not in pushed[0], pushed[0]
    assert "1234" not in str(pushed[0]), pushed[0]


def test_a_verification_whose_route_died_ends_naming_that_rather_than_expiring(pushed):
    """7.2 — "expired" told to a person who did call, on time, from the right number is
    the gateway reporting the one thing that did not happen. A recovery of this modem is
    bounded at three hundred seconds of gate-closed time plus a settle, so it can consume
    a verification's whole window."""
    async def body():
        vid = await _open()
        moved = await queries.fail_verification(
            vid, reason="the modem was out of service")
        await announce_verification_outcomes()
        return vid, moved

    vid, moved = _run(body)
    assert moved is True
    assert pushed[0]["status"] == "failed"
    assert "out of service" in pushed[0]["reason"]


def test_a_route_that_died_is_announced_once_however_many_writers_notice(pushed):
    async def body():
        vid = await _open()
        first = await queries.fail_verification(vid, reason="the modem was out of service")
        second = await queries.fail_verification(vid, reason="noticed again")
        await announce_verification_outcomes()
        return first, second

    first, second = _run(body)
    assert (first, second) == (True, False), "only the writer that moved it may announce"
    assert len(pushed) == 1


# --- the enumerating guard ----------------------------------------------------------------
#
# Two halves, and the second is the one that rots. The rule — a writer may not mark its own
# row announced — is worth having only if the set of writers it is applied to is the real
# one. Both halves are therefore taken off the syntax tree rather than off the file's text:
#
#   * a text window around a match reaches into the next function, which produced a false
#     alarm when an unrelated writer was added 500 characters below a genuine one;
#   * a pattern keyed on `SET status = '<literal>'` does not recognise the same write with
#     its fields in another order, or with the status bound as a parameter. Measured: two
#     new terminal writers in those two shapes, each marking its own row announced, left
#     the whole suite green.
#
# The sweep itself is one of the writers that a text pattern misses for a third reason —
# its statement is an f-string, which is not a string constant at all.

_TERMINAL_STATUSES = {"confirmed", "failed", "expired"}

# Every queries.py function that moves a verification to a terminal state, and which
# states it writes. `?` means the status is bound at call time, so the function can write
# any of them. Adding a writer without adding it here fails the census below — which is
# the point: the failure forces a decision about who tells the application.
KNOWN_VERIFICATION_TERMINAL_WRITERS = {
    "fail_verification": {"failed"},
    "confirm_by_inbound_call": {"confirmed"},
    "confirm_by_inbound_message": {"confirmed"},
    "check_verification": {"confirmed", "failed"},
    "expire_due_verifications": {"expired"},
}

QUERIES_PY = Path(__file__).resolve().parents[1] / "app" / "db" / "queries.py"

_SET_STATUS = re.compile(r"\bSTATUS\s*=\s*(?:'([^']*)'|(\?))", re.IGNORECASE)
_SET_NOTIFIED = re.compile(r"\bNOTIFIED\s*=\s*1\b", re.IGNORECASE)
_SET_CODE_NULL = re.compile(r"\bCODE\s*=\s*NULL\b", re.IGNORECASE)


def _sql_strings(node):
    """Every SQL string in `node`, including f-strings.

    An f-string is a `JoinedStr` rather than a `Constant`, and the expiry sweep — the
    writer this file exists for — is written as one. A census that walked constants alone
    would enumerate every writer except the sweep, and report a full house.
    """
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            yield " ".join(sub.value.split())
        elif isinstance(sub, ast.JoinedStr):
            yield " ".join("".join(
                part.value for part in sub.values
                if isinstance(part, ast.Constant) and isinstance(part.value, str)
            ).split())


def _set_clause(sql: str) -> str | None:
    """The assignment half of an `UPDATE verifications`, or None if it is not one.

    Split from the `WHERE` half on purpose: `status` appears in both, and a condition on
    the status a row must already be in is the opposite of a write.
    """
    upper = sql.upper()
    start = upper.find("UPDATE VERIFICATIONS")
    if start < 0:
        return None
    set_at = upper.find(" SET ", start)
    if set_at < 0:
        return None
    where_at = upper.find(" WHERE ", set_at)
    return sql[set_at + 5:where_at if where_at > 0 else len(sql)]


def _verification_terminal_writers() -> dict[str, set[str]]:
    tree = ast.parse(QUERIES_PY.read_text())
    writers: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for sql in _sql_strings(node):
            clause = _set_clause(sql)
            if clause is None:
                continue
            for literal, bound in _SET_STATUS.findall(clause):
                written = "?" if bound else literal.lower()
                if written == "?" or written in _TERMINAL_STATUSES:
                    writers.setdefault(node.name, set()).add(written)
    return writers


def test_the_census_of_verification_terminal_writers():
    """A new writer of a terminal verification state must be registered here.

    "Every ending reaches the application" is the claim, and it rots the moment somebody
    adds the next writer. Unlike the message side, no call site has to remember to
    notify — one announcer sweeps up every row left with `notified` at 0 — so what this
    census buys is the decision itself: whoever adds a writer is made to look at it and
    confirm the announcer can still see what it wrote.
    """
    assert _verification_terminal_writers() == KNOWN_VERIFICATION_TERMINAL_WRITERS, (
        "queries.py gained or lost a writer of a terminal verification status. Add it to "
        "KNOWN_VERIFICATION_TERMINAL_WRITERS and leave its row's `notified` at 0, or the "
        "one announcer will never tell the application how that verification ended."
    )


def test_no_writer_of_a_terminal_state_marks_it_announced():
    """The rule, now applied to the enumerated writers rather than to a text window.

    A writer that marked its own row announced would be silently unannounced — precisely
    the edit nobody would notice, because nothing else in the system would change.
    Leaving `notified` at 0 hands the row to the one announcer, which claims it with a
    conditional update and therefore tells the application exactly once.
    """
    tree = ast.parse(QUERIES_PY.read_text())
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name not in _verification_terminal_writers():
            continue
        for sql in _sql_strings(node):
            clause = _set_clause(sql)
            if clause and _SET_STATUS.search(clause) and _SET_NOTIFIED.search(clause):
                offenders.append(node.name)
    assert offenders == [], (
        f"these end a verification and mark it announced in the same breath, so the one "
        f"announcer will never see them: {sorted(set(offenders))}"
    )


def test_every_enumerated_terminal_writer_takes_the_code_with_it():
    """Task 4.30, asked of the census rather than of the file.

    That the three endings alive today null the code is guarded behaviourally, over a
    path where the code genuinely travelled to the vendor — and that guard says nothing
    about the *fourth* ending, which is the one that will be written by somebody who is
    thinking about the vendor rather than about the secret. Destruction stands on every
    terminal writer, a census of writers read by eye is never complete, and this census
    already exists and is already taken off the syntax tree.

    The rule is per statement rather than per function on purpose: `check_verification`
    ends a verification two ways, in two updates, and a function-level answer would let
    the second inherit the first's `code = NULL`.

    A writer that binds its status at call time is held to the same rule: it *can* write a
    terminal state, and the whole point of the census is that what it can do is what
    counts.
    """
    tree = ast.parse(QUERIES_PY.read_text())
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name not in KNOWN_VERIFICATION_TERMINAL_WRITERS:
            continue
        for sql in _sql_strings(node):
            clause = _set_clause(sql)
            if clause is None or not _SET_STATUS.search(clause):
                continue
            if not _SET_CODE_NULL.search(clause):
                offenders.append(f"{node.name}: {' '.join(clause.split())[:90]}")
    assert offenders == [], (
        "these end a verification and leave its code readable — the row goes on holding a "
        "live secret beside a subscriber's number after the window in which that secret "
        f"means anything has closed: {sorted(offenders)}"
    )


def test_the_three_guards_above_can_actually_fail():
    """Their own bite, inline, because a guard over source structure is exactly the kind
    that passes against a file it is no longer reading correctly.

    Both shapes that slipped past the text pattern are exercised here: the fields in
    another order, and the status bound at call time.
    """
    reordered = ("UPDATE verifications SET reason = ?, status = 'failed', notified = 1 "
                 " WHERE id = ? AND status = 'pending'")
    bound = "UPDATE verifications SET status = ?, notified = 1 WHERE id = ?"
    for sql in (reordered, bound):
        clause = _set_clause(sql)
        assert clause is not None, f"no longer recognised as a verification write: {sql}"
        assert _SET_STATUS.search(clause), f"the status write is no longer seen in: {sql}"
        assert _SET_NOTIFIED.search(clause), f"the announcement mark is no longer seen: {sql}"

    # And the WHERE half must not be read as a write: `select_route` only requires the
    # row to be pending, and counting it as a writer would pad the census with a
    # function that ends nothing.
    condition_only = ("UPDATE verifications SET route = ? "
                      " WHERE id = ? AND app_id = ? AND status = 'pending'")
    assert not _SET_STATUS.search(_set_clause(condition_only))

    # The code-destruction rule, put the same way round: the shape it must call an
    # offender, and the shape it must not. A `code = ?` in the WHERE half is a condition
    # on the secret rather than its destruction, and reading it as the latter would let
    # the confirming update pass while leaving the code in place.
    leaves_the_code = "UPDATE verifications SET status = 'failed', reason = ? WHERE id = ?"
    assert not _SET_CODE_NULL.search(_set_clause(leaves_the_code)), (
        "the code-destruction rule no longer sees a terminal write that leaves the code")
    destroys_it = ("UPDATE verifications SET reason = ?, code = NULL, status = 'failed' "
                   " WHERE id = ? AND code = ?")
    assert _SET_CODE_NULL.search(_set_clause(destroys_it))
    assert not _SET_CODE_NULL.search(
        _set_clause("UPDATE verifications SET status = 'confirmed' "
                    " WHERE id = ? AND code = NULL")), (
        "a `code = NULL` in the WHERE half is being read as destruction")


# --- 7.2 — the detector, not just the writer ---------------------------------------------

def test_an_open_verification_whose_route_died_is_ended_by_the_sweep(pushed, monkeypatch):
    """The half that is easy to leave unbuilt: `fail_verification` exists, and nothing
    calls it. Then a route dies under an open verification, nothing notices, and the
    person is told "expired" — the one thing that did not happen."""
    import app.modem.manager as manager_mod

    class DeadRoute:
        # Stands in for the serial link, which is what the manager's own
        # `caller_id_held` reads — replacing the manager's property instead would test
        # the fake rather than the chain.
        caller_id_subscribed = False    # the subscription is gone
        in_service = True

    async def body():
        m = manager_mod.ModemManager("/dev/null", "/dev/null")
        m._sender = DeadRoute()
        m._reader_link = DeadRoute()
        vid = await _open(CALL_IN)
        await m.verification_step()
        row = await queries.get_verification(vid, "app1")
        return vid, row["status"], row["reason"]

    vid, status, reason = _run(body)
    assert status == "failed", "the sweep let a dead route run to its deadline"
    assert reason and "precondition" in reason, reason
    assert [(p["verification_id"], p["status"]) for p in pushed] == [(vid, "failed")]


def test_a_verification_whose_route_still_holds_is_left_alone(pushed, monkeypatch):
    """The positive control. A sweep that ends everything has not detected anything."""
    import app.modem.manager as manager_mod

    class LiveRoute:
        caller_id_subscribed = True
        in_service = True

    async def body():
        m = manager_mod.ModemManager("/dev/null", "/dev/null")
        m._sender = LiveRoute()
        m._reader_link = LiveRoute()
        m.ims_proof = _ims_holds()
        vid = await _open(CALL_IN)
        await m.verification_step()
        return (await queries.get_verification(vid, "app1"))["status"]

    assert _run(body) == "pending"
    assert pushed == []


def _ims_holds():
    from app.verification.routes import Proof

    async def proof():
        return Proof(holds=True)
    return proof


# --- 4.15 — the two pushes travel the same route and must not be read as each other ------

def test_a_verification_push_carries_nothing_a_message_receiver_reads_as_a_message_id(
        pushed, monkeypatch):
    """4.15 — both bodies arrive at the same URL, and `id` is how the older one names
    the thing it is about.

    The message contract is `{"id": <message id>, "status": ..., ...}`, and `failed` and
    `expired` are words both bodies use. A receiver keyed on `id` and `status` — which is
    the whole of the older contract — therefore acts on a verification push and marks the
    wrong message. `object` does not save it: a receiver that never looked for `object`
    is exactly the receiver that predates verifications.

    So the two shapes are compared against each other rather than against a remembered
    description of the message body, because the remembered description is what rots.
    """
    from app.modem import delivery_dispatch as message_dispatch

    message_pushes = []

    async def fake_message_deliver(route, payload):
        message_pushes.append(payload)
        return True, None

    monkeypatch.setattr(message_dispatch, "deliver", fake_message_deliver)

    async def body():
        message_id = await queries.create_message("app1", PHONE, "hi")
        await message_dispatch.dispatch_delivery(message_id, "delivered")
        verification_id = await _open(ttl=-1)
        await announce_verification_outcomes()
        return message_id, verification_id

    message_id, verification_id = _run(body)

    message, verification = message_pushes[0], pushed[0]
    assert message["id"] == message_id, "the message contract moved; re-read this test"

    for field, value in message.items():
        if value != message_id:
            continue
        assert field not in verification, (
            f"the message body names its subject in {field!r}, and the verification body "
            f"carries {verification.get(field)!r} there — a receiver reading {field!r} "
            f"acts on a message it was never told about"
        )

    # And the number appears in exactly one place, under a name that says what it is.
    # Comparing the two bodies alone cannot catch a field the message body has never
    # had — `message_id`, say — and a field named that way is precisely one a receiver
    # reads as a message identifier.
    carrying = sorted(k for k, v in verification.items() if v == verification_id)
    assert carrying == ["verification_id"], (
        f"the verification's number travels in {carrying} — it may travel in "
        f"'verification_id' and nowhere else"
    )


# --- 4.30 — the retention runs while the gateway is simply running ----------------------

def test_the_recurring_sweep_prunes_finished_verifications(pushed, monkeypatch):
    """🔴 Measured on 21.09.2026: `prune_verifications` could be deleted from
    `announce_verification_outcomes` outright and the whole suite stayed green.

    The query was guarded and its placement was not, which is the shape that makes a
    retention rule a comment: the rows a person would have to run the deletion by hand to
    remove look exactly like rows a rule removes. The ledger's retention is pinned the
    same way and for the same reason — a correct-looking placement that never fires on a
    gateway that stays up is the failure this asserts against.

    Driven through `ModemManager.verification_step`, which is exactly what the sixty-second
    verification loop calls, rather than through the announcer the loop happens to reach:
    what is claimed here is that a gateway nobody touches forgets these rows.
    """
    import app.modem.manager as manager_mod
    from app.modem.manager import ModemManager

    monkeypatch.setattr(manager_mod, "spawn_delivery_dispatch", lambda *a, **kw: None)

    async def body():
        aged = await _open(ttl=300, code="1234")
        await queries.fail_verification(aged, reason="no_route")
        live = await _open(ttl=300, code="5678")
        db = await get_db()
        await db.execute(
            "UPDATE verifications SET created_at = datetime('now', '-40 days')"
            " WHERE id = ?", (aged,))
        await db.commit()

        await ModemManager("/dev/null", "/dev/null").verification_step()

        async with db.execute("SELECT id FROM verifications ORDER BY id") as cur:
            return live, [row[0] for row in await cur.fetchall()]

    live, remaining = _run(body)
    assert remaining == [live], (
        "the sixty-second verification loop does not prune: a finished verification past "
        "the configured retention outlived a pass of the tick that is supposed to remove it"
    )


def test_the_recurring_sweep_keeps_what_is_inside_the_retention(pushed, monkeypatch):
    """The control the guard above is empty without — a tick that deleted every finished
    verification would satisfy it, and would take a login that ended a minute ago.

    The kept row is finished rather than open on purpose: "still pending" is already
    guarded at the query, and a tick that pruned by age alone would pass that guard while
    failing this one.
    """
    import app.modem.manager as manager_mod
    from app.modem.manager import ModemManager

    monkeypatch.setattr(manager_mod, "spawn_delivery_dispatch", lambda *a, **kw: None)

    async def body():
        recent = await _open(ttl=300, code="1234")
        await queries.fail_verification(recent, reason="no_route")

        await ModemManager("/dev/null", "/dev/null").verification_step()

        db = await get_db()
        async with db.execute("SELECT id FROM verifications") as cur:
            return recent, [row[0] for row in await cur.fetchall()]

    recent, remaining = _run(body)
    assert remaining == [recent]
