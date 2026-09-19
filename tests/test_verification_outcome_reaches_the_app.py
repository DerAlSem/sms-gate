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

import asyncio
import re
from pathlib import Path

import pytest

import app.verification.dispatch as dispatch_mod
from app.db import queries
from app.db.connection import close_db, init_db
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
        await store.set_many({"delivery_dispatch": '[{"app_id":"app1",'
                                                   '"webhook_url":"https://x/hook"}]'})
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
    assert [(p["id"], p["status"]) for p in pushed] == [(vid, "expired")]


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

_TERMINAL_WRITE = re.compile(
    r"UPDATE verifications SET status = '(confirmed|failed|expired)'")

def test_no_writer_of_a_terminal_state_marks_it_announced():
    """The claim "every ending reaches the application" rots the moment somebody adds the
    next writer, so it is checked mechanically rather than believed.

    The rule it enforces is one line long: a statement that moves a verification to a
    terminal state may not also mark it announced. Leaving `notified` at 0 hands the row
    to the one announcer, which claims it with a conditional update and therefore tells
    the application exactly once. A writer that marked its own row announced would be
    silently unannounced — and that is precisely the edit nobody would notice, because
    nothing else in the system would change.
    """
    source = Path("app/db/queries.py").read_text()
    offenders = []
    for match in _TERMINAL_WRITE.finditer(source):
        # One statement, not one function: the window is generous enough for the longest
        # of them and stops well before the next.
        statement = source[match.start():match.start() + 500]
        if "notified = 1" in statement:
            offenders.append(statement.splitlines()[0])
    assert offenders == [], (
        f"these statements end a verification and mark it announced in the same breath, "
        f"so the one announcer will never see it: {offenders}"
    )


def test_the_guard_above_can_actually_fail():
    """Its own bite, inline, because a guard over source text is exactly the kind that
    passes against a file it is no longer reading correctly."""
    offending = ("UPDATE verifications SET status = 'failed', reason = ?, "
                 "notified = 1 WHERE id = ?")
    match = _TERMINAL_WRITE.search(offending)
    assert match is not None, "the pattern no longer recognises a terminal write at all"
    assert "notified = 1" in offending[match.start():match.start() + 500]
