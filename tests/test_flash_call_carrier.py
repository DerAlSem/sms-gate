# tests/test_flash_call_carrier.py
"""The uCaller rung as the ladder sees it: what it buys, when it stops waiting, and what
it refuses to call a result.

The wire is covered by `tests/test_ucaller_adapter.py` against the samples captured live
on 22.09.2026. This file is about the orderings, and three of them are the whole of it:

**An answer carrying a `ucaller_id` is an authorisation, whatever `status` said.** The id
is recorded before anything else happens, because on a real number it is money — and
because it is the only way to ask afterwards what became of the call.

**A placed call is not a delivered code.** `call_status: 1` is the analogue of an SMS
having been sent; the verification is confirmed only by a correct code at `/check`.

**The vendor is allowed not to know yet, and so is the gateway.** `call_status: -1` means
"информация проверяется (от 1 сек до 1 минуты)" — longer than the ladder's whole patience,
and the person is standing in front of a synchronous HTTP request while it runs. So the
wait is bounded by the ladder's own bound, an unresolved outcome is recorded as **unknown**
rather than as either success or failure, and the ladder stops there rather than advancing:
the call was placed, and advancing would buy the same code at the other vendor.
"""

from __future__ import annotations

import asyncio

import pytest

from app.db import queries
from app.db.connection import close_db, init_db
from app.db.migrate import run_migrations
from app.settings_store import store
from app.verification import flash_carrier, ladder, ucaller
from app.verification.routes import FLASH_CALL, SMS_OUT

PHONE = "+79851600019"
BEARER = "SECRET.1692"


def _run(body):
    async def go():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("app1", "token-app1")
        await store.load()
        return await body()

    try:
        return asyncio.run(go())
    finally:
        asyncio.run(close_db())


async def _open(ttl=300, code="1234"):
    return await queries.create_verification("app1", PHONE, code=code, ttl_seconds=ttl)


def _accepted(uid=57251313, code="1234", status=True):
    return ucaller.Call(kind=ucaller.ACCEPTED, placed=ucaller.Placed(
        ucaller_id=uid, code=code, phone="7900***0019", status=status))


def _info(call_status=ucaller.PLACED, code="1234", cost=0.8, balance=100.8):
    return ucaller.Fetched(kind=ucaller.ACCEPTED, info=ucaller.Info(
        ucaller_id=57251313, call_status=call_status, code=code, cost=cost,
        balance_before=balance))


def _patch(monkeypatch, *, call, infos=(), calls=None, asked=None):
    """Drive the adapter from a script. `infos` is consumed one `getInfo` at a time and
    its last entry repeats, which is what a poll actually meets."""
    script = list(infos)

    async def init_call(phone, *, code, unique, bearer, timeout=10.0, client=None,
                        client_label=""):
        if calls is not None:
            calls.append({"phone": phone, "code": code, "unique": unique,
                          "bearer": bearer, "timeout": timeout})
        if isinstance(call, Exception):
            raise call
        return call

    async def get_info(uid, *, bearer, timeout=10.0, client=None):
        if asked is not None:
            asked.append(uid)
        return script.pop(0) if len(script) > 1 else (
            script[0] if script else ucaller.Fetched(kind=ucaller.UNANSWERED))

    monkeypatch.setattr(ucaller, "init_call", init_call)
    monkeypatch.setattr(ucaller, "get_info", get_info)


def _carry(verification_id, *, seconds_left=10.0, rung_id=None, poll_interval=0.0):
    async def go():
        rid = rung_id
        if rid is None:
            rid = await queries.record_verification_rung(
                verification_id, route=FLASH_CALL, outcome=ladder.ATTEMPTING)
        carry = flash_carrier.carrier(verification_id, app_id="app1", bearer=BEARER,
                                      poll_interval=poll_interval)
        attempt = await carry(PHONE, seconds_left=seconds_left, rung_id=rid)
        return attempt, rid
    return go


# --- the placed call --------------------------------------------------------------------

def test_a_connected_call_carries_the_verification_and_records_what_it_cost(monkeypatch):
    def body():
        async def run():
            vid = await _open()
            _patch(monkeypatch, call=_accepted(), infos=[_info()])
            attempt, rung_id = await _carry(vid)()
            assert attempt.outcome == ladder.CARRIED
            assert attempt.vendor_ref == "57251313"
            assert attempt.cost == 0.8
            rows = await queries.verification_rungs(vid)
            assert rows[0]["vendor_ref"] == "57251313"
            return True
        return run()
    assert _run(body)


def test_a_placed_call_does_not_confirm_the_verification(monkeypatch):
    """`call_status: 1` is the analogue of a message having been sent. The code is
    confirmed at `/check` and nowhere else — the vendor never learns whether the person
    read the digits off their screen."""
    def body():
        async def run():
            vid = await _open()
            _patch(monkeypatch, call=_accepted(), infos=[_info()])
            await _carry(vid)()
            row = await queries.get_verification(vid, "app1")
            assert row["status"] == "pending"
            assert row["confirmed_by"] is None
            return True
        return run()
    assert _run(body)


def test_the_idempotency_key_is_the_rungs_own(monkeypatch):
    """A retry of our own HTTP request must not place and pay for a second call, while a
    legitimate repeat — a second rung row — remains possible."""
    def body():
        async def run():
            vid = await _open()
            calls: list = []
            _patch(monkeypatch, call=_accepted(), infos=[_info()], calls=calls)
            _, rung_id = await _carry(vid)()
            assert calls[0]["unique"] == ucaller.idempotency_key(rung_id)
            assert calls[0]["bearer"] == BEARER
            assert calls[0]["code"] == "1234"
            return True
        return run()
    assert _run(body)


# --- `status: false` is not a refusal ---------------------------------------------------

def test_an_authorisation_that_says_status_false_is_still_followed_up(monkeypatch):
    """🔴 The finding the samples bought. The vendor allocates the id and answers
    `status: false`; discarding it loses an authorisation that exists, is queryable and
    costs money on a real number."""
    def body():
        async def run():
            vid = await _open()
            asked: list = []
            _patch(monkeypatch, call=_accepted(uid=57251317, status=False),
                   infos=[_info(call_status=ucaller.NOT_CONNECTED)], asked=asked)
            attempt, _ = await _carry(vid)()
            assert asked == [57251317], "the authorisation was thrown away unqueried"
            assert attempt.vendor_ref == "57251317"
            assert attempt.outcome == ladder.FAILED
            return True
        return run()
    assert _run(body)


def test_a_call_that_could_not_be_connected_fails_the_verification_with_that_reason(
        monkeypatch):
    def body():
        async def run():
            vid = await _open()
            _patch(monkeypatch, call=_accepted(),
                   infos=[_info(call_status=ucaller.NOT_CONNECTED)])
            attempt, _ = await _carry(vid)()
            assert attempt.outcome == ladder.FAILED
            assert "connect" in attempt.reason
            assert attempt.cost == 0.8, "a call that did not connect was still paid for"
            return True
        return run()
    assert _run(body)


# --- the outcome that has not resolved --------------------------------------------------

def test_an_unresolved_outcome_is_recorded_as_unknown(monkeypatch):
    """Neither a placed call nor a failure. The vendor takes up to a minute to decide and
    the ladder's whole patience is ten seconds, so this is the ordinary case rather than
    the exotic one."""
    def body():
        async def run():
            vid = await _open()
            _patch(monkeypatch, call=_accepted(),
                   infos=[_info(call_status=ucaller.PENDING)])
            attempt, _ = await _carry(vid, seconds_left=0.05)()
            assert attempt.outcome == ladder.UNRESOLVED
            assert attempt.vendor_ref == "57251313", (
                "an unresolved call still has an id, and it is the only way to ask later")
            row = await queries.get_verification(vid, "app1")
            assert row["status"] == "pending", "unknown was reported as an ending"
            return True
        return run()
    assert _run(body)


def test_the_ladder_does_not_advance_past_a_call_that_was_placed():
    """The expensive mistake this rung can make: the call is placed and paid for, the
    outcome has not arrived, and the ladder buys the same code at the other vendor.

    Driven through `walk` rather than asserted against the constant. A membership test
    reads as a guard and is one only of the table; what has to hold is what the driver
    does with it, and the two are three branches apart.
    """
    def body():
        async def run():
            vid = await _open()
            walked: list = []

            async def unresolved(phone, *, seconds_left, rung_id):
                walked.append(FLASH_CALL)
                return ladder.Attempt(outcome=ladder.UNRESOLVED, vendor_ref="57251313")

            async def behind(phone, *, seconds_left, rung_id):
                walked.append(SMS_OUT)
                return ladder.Attempt(outcome=ladder.CARRIED)

            walk = await ladder.walk(
                vid, app_id="app1", operator="МегаФон", phone=PHONE,
                rungs=[FLASH_CALL, SMS_OUT], gates=[],
                carriers={FLASH_CALL: unresolved, SMS_OUT: behind}, bound=5.0)

            assert walked == [FLASH_CALL], (
                "the ladder bought the same code at the rung behind a call already placed")
            assert walk.carried_by is None, "an unknown outcome was reported as carried"
            row = await queries.get_verification(vid, "app1")
            assert row["status"] == "pending", (
                "the application was told the code is not coming while a phone may ring")
            assert (await queries.verification_rungs(vid))[0]["outcome"] == \
                ladder.UNRESOLVED
            return True
        return run()
    assert _run(body)


def test_the_wait_stops_at_the_ladders_bound_rather_than_the_vendors(monkeypatch):
    """The person is standing in front of a synchronous request while this runs."""
    def body():
        async def run():
            vid = await _open()
            asked: list = []
            _patch(monkeypatch, call=_accepted(),
                   infos=[_info(call_status=ucaller.PENDING)], asked=asked)
            attempt, _ = await _carry(vid, seconds_left=0.05, poll_interval=0.02)()
            assert attempt.outcome == ladder.UNRESOLVED
            assert 1 <= len(asked) <= 4, (
                f"the poll ran {len(asked)} times inside a 0.05s bound")
            return True
        return run()
    assert _run(body)


def test_a_pending_outcome_that_resolves_inside_the_bound_is_the_resolved_one(monkeypatch):
    def body():
        async def run():
            vid = await _open()
            _patch(monkeypatch, call=_accepted(),
                   infos=[_info(call_status=ucaller.PENDING), _info()])
            attempt, _ = await _carry(vid, seconds_left=5.0, poll_interval=0.0)()
            assert attempt.outcome == ladder.CARRIED
            return True
        return run()
    assert _run(body)


# --- the code the vendor actually dialled -------------------------------------------------

def test_a_code_the_vendor_changed_fails_rather_than_matching_digits_it_never_dialled(
        monkeypatch):
    """"nothing in the reference promises the vendor can always allocate a number ending
    in the four digits we asked for". Matching ours would be indistinguishable, from the
    outside, from every subscriber suddenly typing the wrong code — and every instance of
    it is paid for."""
    def body():
        async def run():
            vid = await _open(code="1234")
            _patch(monkeypatch, call=_accepted(code="9876"), infos=[_info()])
            attempt, _ = await _carry(vid)()
            assert attempt.outcome == ladder.FAILED
            assert "digits" in attempt.reason or "code" in attempt.reason
            assert attempt.vendor_ref == "57251313", "the paid authorisation lost its id"
            return True
        return run()
    assert _run(body)


def test_a_code_that_changed_only_by_the_time_of_getinfo_is_caught_too(monkeypatch):
    """The vendor reports a `code` twice — once when it takes the call and once when it
    reports on it. Both are read, because a check at one end only is a check that the
    other end can walk past."""
    def body():
        async def run():
            vid = await _open(code="1234")
            _patch(monkeypatch, call=_accepted(code="1234"), infos=[_info(code="9876")])
            attempt, _ = await _carry(vid)()
            assert attempt.outcome == ladder.FAILED
            return True
        return run()
    assert _run(body)


# --- what is refused before anything is bought ---------------------------------------------

def test_a_verification_that_ended_under_us_buys_nothing(monkeypatch):
    def body():
        async def run():
            vid = await _open()
            await queries.fail_verification(vid, reason="gone")
            calls: list = []
            _patch(monkeypatch, call=_accepted(), infos=[_info()], calls=calls)
            attempt, _ = await _carry(vid)()
            assert attempt.outcome == ladder.INCAPABLE
            assert calls == [], "a vendor was paid for a verification that had ended"
            # The reason, not just the outcome. Without the code the next guard down —
            # the vendor's range — refuses the same call for a different reason, so an
            # outcome-only assertion passes against a carrier that never asks whether the
            # verification is still alive, and the operator reading the row is told the
            # digits were unusable when what happened is that nobody was waiting.
            assert "ended" in attempt.reason, attempt.reason
            return True
        return run()
    assert _run(body)


def test_a_code_outside_the_vendors_range_is_incapable_rather_than_a_decline(monkeypatch):
    """A decline is a statement about the subscriber, and a rung that appears to decline
    people for a reason of ours is a rung taken out of the rule for the wrong reason."""
    def body():
        async def run():
            vid = await _open(code="0000")
            calls: list = []
            _patch(monkeypatch, call=_accepted(), infos=[_info()], calls=calls)
            attempt, _ = await _carry(vid)()
            assert attempt.outcome == ladder.INCAPABLE
            assert calls == []
            return True
        return run()
    assert _run(body)


# --- what the vendor's refusals mean --------------------------------------------------------

@pytest.mark.parametrize("kind, outcome", [
    (ucaller.DECLINED, ladder.DECLINED),
    (ucaller.REFUSED, ladder.REFUSED),
    (ucaller.UNCLASSIFIED, ladder.UNCLASSIFIED),
    (ucaller.UNANSWERED, ladder.UNANSWERED),
])
def test_a_refusal_carries_its_own_kind_to_the_ladder(monkeypatch, kind, outcome):
    def body():
        async def run():
            vid = await _open()
            _patch(monkeypatch, call=ucaller.Call(kind=kind, error="why"))
            attempt, _ = await _carry(vid)()
            assert attempt.outcome == outcome
            assert attempt.vendor_ref is None
            return True
        return run()
    assert _run(body)


def test_a_vendor_refusing_this_gateway_wakes_the_operator(monkeypatch):
    """With two paid rungs, "the vendor is out of credit" is the question the operator has
    to answer before they can act, so the alert names uCaller."""
    said: list = []
    monkeypatch.setattr("app.alerting.notify",
                        lambda kind, text, **kw: said.append(text))

    def body():
        async def run():
            vid = await _open()
            _patch(monkeypatch, call=ucaller.Call(
                kind=ucaller.REFUSED, error="Insufficient funds", error_code=1002))
            await _carry(vid)()
            assert said and "uCaller" in said[0]
            return True
        return run()
    assert _run(body)


def test_an_accepted_answer_with_no_id_is_not_read_as_a_placed_call(monkeypatch):
    """An authorisation may exist that we cannot follow up or attribute a cost to. That is
    the state an unexplained fall in the vendor's balance comes from, and it needs a name
    to look for rather than a silent success."""
    def body():
        async def run():
            vid = await _open()
            _patch(monkeypatch, call=ucaller.Call(
                kind=ucaller.ACCEPTED,
                placed=ucaller.Placed(ucaller_id=None, code="1234", phone=None,
                                      status=True)))
            attempt, _ = await _carry(vid)()
            assert attempt.outcome == ladder.UNANSWERED
            assert attempt.vendor_ref is None
            return True
        return run()
    assert _run(body)


# --- the balance this rung reports ------------------------------------------------------------

def test_the_balance_watched_is_the_one_after_this_call_is_charged(monkeypatch):
    """`getInfo.balance` is the balance **before** the charge. Watched as it stands, a
    floor held against it fires one verification late."""
    seen: list = []
    monkeypatch.setattr("app.verification.balance.observe",
                        lambda route, value: seen.append((route, value)))

    def body():
        async def run():
            vid = await _open()
            _patch(monkeypatch, call=_accepted(),
                   infos=[_info(cost=0.8, balance=100.8)])
            await _carry(vid)()
            assert seen == [(FLASH_CALL, 100.0)]
            return True
        return run()
    assert _run(body)
