# tests/test_tg_user_outcomes.py
"""Task 3.3 — every Telegram failure this gateway claims to understand, and the evidence
for the claim.

`messenger-delivery` forbids the alternative in as many words: "A verdict recognised by a
string match invented by us SHALL NOT be written." The gateway has paid for that rule once
already, in the modem's `+CMS`/`+CME` table, where 96 was filed as permanent when it is
not — and the messenger routes carry the same risk in a worse place: a transient error
read as "the account is limited" disables a working route, and a limited account read as
an ordinary error leaves it enabled and reported to nobody.

So each row is keyed on the exception class's `ID` — the server's own string, carried as a
class attribute rather than parsed out of a formatted message — and each row names its
evidence. The evidence is checked here against the library that is actually installed: a
version that renames an error fails these tests instead of failing a send.
"""
from __future__ import annotations

import asyncio

import pytest
from pyrogram import errors

from app.routing import tg_errors, tg_user as tg
from app.routing.route import Outcome

from test_tg_user_wrapper import ACCOUNT, FakeClient, make_route, offer, the_account


# ---------------------------------------------------------------- the table binds to the vendor


def test_every_row_names_an_error_the_installed_library_still_has():
    """The row's key must be the class's own `ID`, not a string we remember.

    This is the whole of the rule the modem table broke. A renamed error, a changed code
    or a dropped class fails here — in a test that costs a second — rather than in a rung
    that silently reclassifies.
    """
    for error_id, row in tg_errors.TABLE.items():
        found = [c for c in _named_errors() if getattr(c, "ID", None) == error_id]
        assert found, f"{error_id} is not an error this build of kurigram knows"
        assert row.cites, f"{error_id} cites nothing"


def test_no_row_claims_a_send_was_accepted():
    """A failure is never an acceptance. The table may only narrow the three."""
    assert {row.outcome for row in tg_errors.TABLE.values()} <= {
        Outcome.MISS, Outcome.UNAVAILABLE, Outcome.INDETERMINATE}


def test_the_captured_rows_cite_the_capture_by_probe_name():
    """The two the live run produced say so; the rest name the vendor reference."""
    assert "resolve_phone.no_account" in tg_errors.TABLE["PHONE_NOT_OCCUPIED"].cites
    assert "resolve_phone.hidden" in tg_errors.TABLE["PHONE_NOT_OCCUPIED"].cites
    assert "flood_wait" in tg_errors.TABLE["FLOOD_WAIT_X"].cites


def _named_errors():
    seen = []
    for name in dir(errors):
        candidate = getattr(errors, name)
        if isinstance(candidate, type) and getattr(candidate, "ID", None):
            seen.append(candidate)
    return seen


# ------------------------------------------------------------------------- what each row says


def test_a_number_that_did_not_resolve_is_a_miss_and_claims_nothing_more():
    """`PHONE_NOT_OCCUPIED` arrived identically for a number with no account and for one
    hidden from lookup — every recorded field, the formatted message included. The route
    reports a miss and the ladder continues; which of the two it was, nobody can say."""
    attempt = tg_errors.outcome_for(errors.PhoneNotOccupied())
    assert attempt is not None
    assert attempt.outcome is Outcome.MISS
    lowered = attempt.reason.lower()
    assert "has no telegram" not in lowered
    assert "hidden" in lowered and "did not resolve" in lowered


def test_a_flood_wait_is_ours_and_says_how_long():
    attempt = tg_errors.outcome_for(errors.FloodWait(value=42))
    assert attempt.outcome is Outcome.UNAVAILABLE
    assert "42" in attempt.reason


def test_the_account_being_limited_is_recognised_and_recognisable():
    """`PEER_FLOOD` is Telegram's own words for it: "The current account is limited, you
    cannot execute this action, check @spambot for more info."

    Recognised as a distinct fact rather than as one more failure, because task 5.5 owes an
    alert naming the brand and the messenger — and because the aggregate alert exists
    precisely so that this recognition is not the only thing standing between a dead
    account and silence.
    """
    attempt = tg_errors.outcome_for(errors.PeerFlood())
    assert attempt.outcome is Outcome.UNAVAILABLE
    assert attempt.limits_account, (
        "carried on the attempt, because this is the only place the fact is knowable: "
        "downstream it could be recovered only by matching on the reason text"
    )
    assert "@spambot" in attempt.reason


@pytest.mark.parametrize("name", [
    "AuthKeyUnregistered", "SessionRevoked", "SessionExpired",
    "UserDeactivated", "UserDeactivatedBan",
])
def test_a_dead_session_is_unavailable_and_is_known_to_be_about_us(name):
    """Logged out, revoked or banned — none of it is the recipient's doing, and the ladder
    must reach the modem rather than stop."""
    failure = getattr(errors, name)()
    attempt = tg_errors.outcome_for(failure)
    assert attempt.outcome is Outcome.UNAVAILABLE
    assert attempt.limits_account


@pytest.mark.parametrize("name", [
    "UserPrivacyRestricted", "UserIsBlocked", "InputUserDeactivated", "PhoneNumberInvalid",
])
def test_a_recipient_we_cannot_reach_is_a_miss(name):
    failure = getattr(errors, name)()
    attempt = tg_errors.outcome_for(failure)
    assert attempt.outcome is Outcome.MISS
    assert not attempt.limits_account, (
        "the recipient's own settings say nothing about our account"
    )


def test_an_error_the_library_cannot_name_is_left_to_the_floor():
    """`UnknownError` is the library's fallback for an id its tables lack, and an error we
    cannot name is exactly what `indeterminate` is for. The table says nothing about it on
    purpose: a catch-all row here would be the invented verdict the delta forbids, and the
    caller's floor already answers it."""
    from pyrogram.errors.rpc_error import UnknownError

    assert tg_errors.outcome_for(UnknownError()) is None
    assert tg_errors.outcome_for(TimeoutError("Failed to invoke after 10 retries")) is None
    assert tg_errors.outcome_for(ValueError("something of ours")) is None


# ------------------------------------------------------------ the table wins over the step


def _route_raising(tmp_path, where: str, failure: BaseException):
    route, made = make_route(tmp_path)

    def factory(**kwargs):
        client = FakeClient(**kwargs)
        client.me = the_account()
        client.raises[where] = failure
        made.append(client)
        return client

    route._factory = factory
    return route, made


def test_a_no_account_answer_reaches_the_ladder_as_a_miss(tmp_path):
    """Through the wrapper, not only through the table.

    Without the table this is `unavailable` — the step-based floor — which is safe but
    wrong: the record an operator reads would say "this route could not be used" about a
    number that simply has no account.
    """
    route, _ = _route_raising(tmp_path, "ResolvePhone", errors.PhoneNotOccupied())
    attempt = asyncio.run(offer(route))
    assert attempt.outcome is Outcome.MISS


def test_a_flood_wait_during_the_send_does_not_stop_the_ladder(tmp_path):
    """The expensive assertion in the other direction.

    A failure during the send is `indeterminate` by default — the frame may have left. A
    flood-wait is the exception the delta anticipates: the server *refused*, which is a
    positive statement that nothing was sent, so the ladder continues and the person gets
    the code by SMS instead of not at all.
    """
    route, _ = _route_raising(tmp_path, "SendMessage", errors.FloodWait(value=17))
    attempt = asyncio.run(offer(route))
    assert attempt.outcome is Outcome.UNAVAILABLE
    assert "17" in attempt.reason


def test_an_unnamed_failure_during_the_send_still_stops_the_ladder(tmp_path):
    """The floor is not weakened by the table existing."""
    from pyrogram.errors.rpc_error import UnknownError

    route, _ = _route_raising(tmp_path, "SendMessage", UnknownError())
    attempt = asyncio.run(offer(route))
    assert attempt.outcome is Outcome.INDETERMINATE


def test_the_wrapper_asks_the_table_first(tmp_path):
    """Named errors are answered by name wherever they happen — the step is the fallback,
    not the first word."""
    route, _ = _route_raising(tmp_path, "ResolvePhone", errors.PeerFlood())
    attempt = asyncio.run(offer(route))
    assert attempt.outcome is Outcome.UNAVAILABLE
    assert "@spambot" in attempt.reason
    assert ACCOUNT in attempt.reason
