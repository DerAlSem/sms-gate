"""The ladder's driver: who calls the rungs, in what order, and what it refuses to buy.

The vendor half of this change has been built and proved live; what this covers is the
thing that calls it. Until it existed, `check_send_ability` and `send_verification_message`
had no production caller at all and no verification could reach either.

Four of these tests fail on the implementation that is natural to write:

- one that treats a rung's silence as a decline, which is how a fee that was charged and
  never spent becomes invisible;
- one that bounds each rung separately, which doubles the wait the application was
  promised on a slow day;
- one that runs a gate after the ability check, which refuses something already paid for
  and for which no refund path exists;
- one that holds the ladder's order in the code, which satisfies "Telegram first" while
  defeating the rule that is supposed to decide it.
"""

import asyncio
import time

import pytest

from app.db import queries
from app.db.connection import close_db, init_db
from app.db.migrate import run_migrations
from app.settings_store import store
from app.verification import ladder, rule
from app.verification.routes import FLASH_CALL, SMS_OUT, TG_GATEWAY

PHONE = "+79851600019"


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


async def _open(ttl=300, phone=PHONE):
    return await queries.create_verification("app1", phone, code="1234", ttl_seconds=ttl)


def _carrier(outcome, *, asked, delay=0.0, cost=None, vendor_ref=None, reason=""):
    """A rung that answers `outcome`, recording that it was asked at all."""
    async def carry(phone, *, seconds_left, rung_id):
        asked.append((phone, seconds_left))
        if delay:
            await asyncio.sleep(delay)
        return ladder.Attempt(outcome=outcome, cost=cost, vendor_ref=vendor_ref,
                              reason=reason)

    return carry


def _gate(reason):
    async def gate():
        return reason

    return gate


# --- the order is the rule's, and the rule can change under a running service ----------

def test_the_order_of_the_rungs_comes_from_the_rule_and_not_from_the_code():
    """Task 4.32. An implementation that tries Telegram first because the code says so
    passes every other test here."""
    async def body():
        order = []

        async def walk_once(phone):
            # A number of its own per walk, because the two walks here happen inside one
            # second and every rung of both is a paid attempt: on one number the second
            # walk is refused by that number's own allowance before it reaches a rung,
            # and this test would then be asserting about an empty list. Task 4.62.
            seen = []
            carriers = {r: _noting(r, seen, ladder.DECLINED)
                        for r in (TG_GATEWAY, FLASH_CALL)}
            await ladder.walk(await _open(phone=phone), app_id="app1",
                              operator="МегаФон", phone=phone,
                              rungs=rule.route_for("МегаФон"), gates=(),
                              carriers=carriers, bound=5.0)
            order.append(tuple(seen))

        await walk_once(PHONE)
        await store.set_many({"operator_routes": _rule_json(
            ("МегаФон", [FLASH_CALL, TG_GATEWAY]))})
        await walk_once("+79031680015")

        assert order[0] == (TG_GATEWAY, FLASH_CALL)
        assert order[1] == (FLASH_CALL, TG_GATEWAY), \
            "the entry was rewritten while the service ran and the order did not follow"

    _run(body)


def _noting(route, seen, outcome, **kw):
    async def carry(phone, *, seconds_left, rung_id):
        seen.append(route)
        return ladder.Attempt(outcome=outcome, **kw)

    return carry


def _rule_json(*pairs):
    import json
    entries = [{"operator": op, "routes": routes} for op, routes in pairs]
    entries += [{"operator": "*", "routes": [SMS_OUT]},
                {"operator": "?", "routes": [SMS_OUT]}]
    return json.dumps(entries, ensure_ascii=False)


# --- what a decline is, and what it is not --------------------------------------------

def test_a_declining_rung_advances_the_ladder_and_is_recorded_against_that_rung():
    """Task 4.33. The decline costs nothing, which is the whole reason the cheap rung is
    tried first."""
    async def body():
        seen = []
        vid = await _open()
        walk = await ladder.walk(
            vid, app_id="app1", operator="МегаФон", phone=PHONE, rungs=[TG_GATEWAY, FLASH_CALL], gates=(),
            carriers={TG_GATEWAY: _noting(TG_GATEWAY, seen, ladder.DECLINED,
                                          reason="PHONE_NUMBER_NOT_AVAILABLE"),
                      FLASH_CALL: _noting(FLASH_CALL, seen, ladder.CARRIED)},
            bound=5.0)

        assert seen == [TG_GATEWAY, FLASH_CALL]
        assert walk.carried_by == FLASH_CALL
        rungs = await queries.verification_rungs(vid)
        assert [(r["route"], r["outcome"]) for r in rungs] == [
            (TG_GATEWAY, ladder.DECLINED), (FLASH_CALL, ladder.CARRIED)]
        assert rungs[0]["cost"] in (None, 0)
        assert rungs[0]["reason"] == "PHONE_NUMBER_NOT_AVAILABLE"

    _run(body)


def test_a_rung_that_does_not_answer_is_counted_as_possibly_charged_not_as_a_decline():
    """Task 4.36. Treating a timeout as a decline is the natural way to write this and
    the way that hides money: a confirmation we never saw is a fee that can be neither
    spent nor refunded, and the only symptom is a balance that drifts."""
    async def body():
        vid = await _open()
        walk = await ladder.walk(
            vid, app_id="app1", operator="МегаФон", phone=PHONE, rungs=[TG_GATEWAY, FLASH_CALL], gates=(),
            carriers={TG_GATEWAY: _noting(TG_GATEWAY, [], ladder.UNANSWERED),
                      FLASH_CALL: _noting(FLASH_CALL, [], ladder.CARRIED)},
            bound=5.0)

        assert walk.carried_by == FLASH_CALL
        rungs = await queries.verification_rungs(vid)
        assert rungs[0]["outcome"] == ladder.UNANSWERED
        assert rungs[0]["outcome"] != ladder.DECLINED

    _run(body)


def test_a_vendor_refusing_us_is_not_counted_as_a_decline_against_the_rung():
    """A rung that appears to decline every subscriber is a rung that will be taken out
    of the rule for the wrong reason."""
    async def body():
        vid = await _open()
        await ladder.walk(
            vid, app_id="app1", operator="МегаФон", phone=PHONE, rungs=[TG_GATEWAY, FLASH_CALL], gates=(),
            carriers={TG_GATEWAY: _noting(TG_GATEWAY, [], ladder.REFUSED,
                                          reason="ACCESS_TOKEN_INVALID"),
                      FLASH_CALL: _noting(FLASH_CALL, [], ladder.CARRIED)},
            bound=5.0)
        rungs = await queries.verification_rungs(vid)
        assert rungs[0]["outcome"] == ladder.REFUSED

    _run(body)


# --- what the money gates buy ---------------------------------------------------------

def test_a_gate_that_refuses_contacts_no_rung_at_all():
    """Tasks 4.26 and 4.37. Asserted on the vendor not being called rather than on the
    outcome: a gate evaluated after a confirmed ability check refuses something already
    paid for, and the outcome looks identical either way."""
    async def body():
        asked = []
        vid = await _open()
        walk = await ladder.walk(
            vid, app_id="app1", operator="МегаФон", phone=PHONE, rungs=[TG_GATEWAY, FLASH_CALL],
            gates=(_gate(""), _gate("spend_ceiling_reached"), _gate("")),
            carriers={TG_GATEWAY: _carrier(ladder.CARRIED, asked=asked),
                      FLASH_CALL: _carrier(ladder.CARRIED, asked=asked)},
            bound=5.0)

        assert asked == [], "a rung was contacted after a gate had refused"
        assert walk.carried_by is None
        assert walk.refused_by == "spend_ceiling_reached"
        assert await queries.verification_rungs(vid) == []

    _run(body)


def test_a_refusal_by_a_gate_is_not_reported_as_a_vendor_failure():
    async def body():
        vid = await _open()
        walk = await ladder.walk(
            vid, app_id="app1", operator="МегаФон", phone=PHONE, rungs=[TG_GATEWAY], carriers={},
            gates=(_gate("entitlement_off"),), bound=5.0)
        assert walk.refused_by == "entitlement_off"
        assert walk.attempts == ()

    _run(body)


def test_a_rule_that_refuses_contacts_nothing():
    async def body():
        asked = []
        vid = await _open()
        walk = await ladder.walk(
            vid, app_id="app1", operator="МегаФон", phone=PHONE, rungs=[rule.REFUSE], gates=(),
            carriers={TG_GATEWAY: _carrier(ladder.CARRIED, asked=asked)}, bound=5.0)
        assert asked == []
        assert walk.refused_by == "rule"

    _run(body)


# --- the bound is the ladder's, not the rung's ----------------------------------------

def test_one_bound_covers_the_whole_ladder_rather_than_each_rung():
    """Task 4.38. A slow first rung does not double the time the application waits."""
    async def body():
        started = time.monotonic()
        seen_left = []

        async def slow(phone, *, seconds_left, rung_id):
            seen_left.append(seconds_left)
            await asyncio.sleep(0.25)
            return ladder.Attempt(outcome=ladder.UNANSWERED)

        async def quick(phone, *, seconds_left, rung_id):
            seen_left.append(seconds_left)
            return ladder.Attempt(outcome=ladder.CARRIED)

        vid = await _open()
        walk = await ladder.walk(
            vid, app_id="app1", operator="МегаФон", phone=PHONE, rungs=[TG_GATEWAY, FLASH_CALL], gates=(),
            carriers={TG_GATEWAY: slow, FLASH_CALL: quick}, bound=0.4)

        assert walk.carried_by == FLASH_CALL
        assert time.monotonic() - started < 0.4 + 0.15
        assert seen_left[1] < seen_left[0], \
            "the second rung was handed the whole bound again"

    _run(body)


def test_a_ladder_out_of_time_does_not_contact_the_next_rung():
    async def body():
        asked = []

        async def eats_the_bound(phone, *, seconds_left, rung_id):
            await asyncio.sleep(0.2)
            return ladder.Attempt(outcome=ladder.UNANSWERED)

        vid = await _open()
        walk = await ladder.walk(
            vid, app_id="app1", operator="МегаФон", phone=PHONE, rungs=[TG_GATEWAY, FLASH_CALL], gates=(),
            carriers={TG_GATEWAY: eats_the_bound,
                      FLASH_CALL: _carrier(ladder.CARRIED, asked=asked)},
            bound=0.2)

        assert asked == []
        assert walk.carried_by is None

    _run(body)


# --- a rung that cannot be attempted at all -------------------------------------------

def test_a_rung_with_nothing_to_carry_it_is_not_attempted_alerts_and_the_ladder_advances(
        monkeypatch):
    """Task 4.50. The one place where a configuration gap costs money rather than
    traffic, and therefore the one that must be loud: the ladder simply moves to the
    dearer rung and every verification still succeeds."""
    async def body():
        alerts = []
        import app.alerting as alerting
        monkeypatch.setattr(alerting, "notify",
                            lambda kind, text, **kw: alerts.append((kind, text)))

        vid = await _open()
        walk = await ladder.walk(
            vid, app_id="app1", operator="МегаФон", phone=PHONE, rungs=[TG_GATEWAY, FLASH_CALL], gates=(),
            carriers={FLASH_CALL: _noting(FLASH_CALL, [], ladder.CARRIED)}, bound=5.0)

        assert walk.carried_by == FLASH_CALL
        rungs = await queries.verification_rungs(vid)
        assert [(r["route"], r["outcome"]) for r in rungs] == [
            (TG_GATEWAY, ladder.ABSENT), (FLASH_CALL, ladder.CARRIED)]
        assert alerts and TG_GATEWAY in alerts[0][1]
        assert alerts[0][0] == "routing"

    _run(body)


# --- what is recorded, and when -------------------------------------------------------

def test_every_rung_is_recorded_before_it_is_contacted():
    """Each rung is an attempt of its own, and its row exists before the vendor does
    anything — so a crash mid-flight leaves a record of which rung was in flight rather
    than of nothing at all."""
    async def body():
        vid = await _open()
        seen_rows = []

        async def look(phone, *, seconds_left, rung_id):
            rows = await queries.verification_rungs(vid)
            seen_rows.append([(r["route"], r["outcome"], r["id"]) for r in rows])
            assert rung_id == rows[-1]["id"]
            return ladder.Attempt(outcome=ladder.CARRIED)

        await ladder.walk(vid, app_id="app1", operator="МегаФон", phone=PHONE, rungs=[TG_GATEWAY], gates=(),
                          carriers={TG_GATEWAY: look}, bound=5.0)

        assert seen_rows[0][0][0] == TG_GATEWAY
        assert seen_rows[0][0][1] == ladder.ATTEMPTING

    _run(body)


def test_the_operator_a_verification_was_routed_for_is_recorded(): 
    """Task 6.8. The norm asks for the unknown-operator case to be **countable rather
    than invisible**, and on the paid rungs there was nothing to count it with: a
    verification carried by `tg_gateway` or `flash_call` creates no `messages` row at
    all, and neither `verifications` nor `verification_rungs` held an operator.

    Recorded on the verification rather than on each rung because it is one fact per
    walk: the ladder is the rule's answer for **this subscriber's** operator, and every
    rung of it was routed for the same one.
    """
    async def body():
        vid = await _open()
        await ladder.walk(vid, app_id="app1", operator="МегаФон", phone=PHONE,
                          rungs=[TG_GATEWAY], gates=(),
                          carriers={TG_GATEWAY: _carrier(ladder.CARRIED, asked=[])},
                          bound=5.0)
        return dict(await queries.get_verification(vid, "app1"))

    row = _run(body)
    assert row["routed_operator"] == "МегаФон"


def test_a_verification_routed_without_a_known_operator_says_so_in_a_countable_word():
    """🔴 The case the clause exists for, and the reason it is a word rather than a
    `NULL`: a null cannot tell "routed for nobody" from "written before this column
    existed", and the count the rule is reviewed by would quietly include every old row.

    The word is the rule's own `?` — the entry that answers for an operator that could
    not be resolved — and it is spelled with a character an operator name cannot contain,
    so a real network can never be mistaken for it.
    """
    async def body():
        vid = await _open()
        await ladder.walk(vid, app_id="app1", operator=None, phone=PHONE,
                          rungs=[TG_GATEWAY], gates=(),
                          carriers={TG_GATEWAY: _carrier(ladder.CARRIED, asked=[])},
                          bound=5.0)
        row = dict(await queries.get_verification(vid, "app1"))
        db = await _db()
        async with db.execute(
            "SELECT COUNT(*) FROM verifications WHERE routed_operator = ?",
            (rule.UNKNOWN,),
        ) as cur:
            countable = (await cur.fetchone())[0]
        return row, countable

    row, countable = _run(body)
    assert row["routed_operator"] == rule.UNKNOWN
    assert countable == 1


def test_the_operator_is_recorded_even_where_the_ladder_places_nothing():
    """A walk refused by a gate, or by the rule itself, was still routed — and the
    unknown-operator entry being *set to a refusal* is the configuration this clause was
    written about. Recorded before the refusals for that reason: a case that disappears
    from the count exactly when it is refused is the invisible one all over again."""
    async def body():
        vid = await _open()
        await ladder.walk(vid, app_id="app1", operator=None, phone=PHONE,
                          rungs=[rule.REFUSE], gates=(), carriers={}, bound=5.0)
        return dict(await queries.get_verification(vid, "app1"))

    row = _run(body)
    assert row["routed_operator"] == rule.UNKNOWN


def test_the_word_for_no_known_operator_is_the_rules_own(): 
    """The two spellings are one decision. The store writes the word and the rule reads
    it; kept apart they drift, and the drift is silent — a count that matches nothing and
    a rule entry nobody hits."""
    assert queries.ROUTED_WITHOUT_A_KNOWN_OPERATOR == rule.UNKNOWN


async def _db():
    from app.db.connection import get_db
    return await get_db()


def test_the_verification_names_the_rung_that_carried_it_not_the_first_tried():
    """An application told to expect a Telegram message for a person the Gateway declined
    would put the wrong instruction on the screen: the person waits in the wrong place
    while a phone they are holding rings."""
    async def body():
        vid = await _open()
        walk = await ladder.walk(
            vid, app_id="app1", operator="МегаФон", phone=PHONE, rungs=[TG_GATEWAY, FLASH_CALL], gates=(),
            carriers={TG_GATEWAY: _noting(TG_GATEWAY, [], ladder.DECLINED),
                      FLASH_CALL: _noting(FLASH_CALL, [], ladder.CARRIED)}, bound=5.0)

        row = await queries.get_verification(vid, "app1")
        assert walk.carried_by == FLASH_CALL
        assert row["route"] == FLASH_CALL
        assert row["status"] == "pending"

    _run(body)


def test_a_ladder_every_rung_of_which_declined_fails_the_verification_with_that_reason():
    """A ladder ends in a route that either carries or fails. Left open, it would report
    "expired" to a person nobody ever tried to reach."""
    async def body():
        vid = await _open()
        walk = await ladder.walk(
            vid, app_id="app1", operator="МегаФон", phone=PHONE, rungs=[TG_GATEWAY, FLASH_CALL], gates=(),
            carriers={TG_GATEWAY: _noting(TG_GATEWAY, [], ladder.DECLINED),
                      FLASH_CALL: _noting(FLASH_CALL, [], ladder.DECLINED)}, bound=5.0)

        row = await queries.get_verification(vid, "app1")
        assert walk.carried_by is None
        assert row["status"] == "failed"
        assert row["reason"]

    _run(body)


def test_a_last_rung_that_did_not_answer_leaves_the_verification_in_flight():
    """The vendor may yet deliver what it never told us it took. Failing it here would
    tell the application the code is not coming while the code is on its way."""
    async def body():
        vid = await _open()
        walk = await ladder.walk(
            vid, app_id="app1", operator="МегаФон", phone=PHONE, rungs=[TG_GATEWAY], gates=(),
            carriers={TG_GATEWAY: _noting(TG_GATEWAY, [], ladder.UNANSWERED)}, bound=5.0)

        row = await queries.get_verification(vid, "app1")
        assert walk.carried_by is None
        assert row["status"] == "pending"

    _run(body)
