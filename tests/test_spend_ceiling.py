"""The spend ceiling: what this gateway may spend in total, not per number.

Tasks 4.26, 4.52 and — with the gates assembled and handed to the driver — 4.37.

**It is not the vendors' limits.** Those are per number, four a minute and thirty a day,
and a loop over five hundred numbers violates none of them while spending four hundred
roubles. **It is not a balance floor either**, which reports money that has already gone.

**It counts both paid rungs together.** The ladder advances from Telegram to the call by
design, so a ceiling held per vendor lets one run of verifications spend twice the
intended amount without either half reaching its own limit. What is bounded is the bill,
and the bill is one.

**Every attempt counts, including the free ones.** A ceiling that counted only confirmed
charges would be blind to exactly the attempts most likely to have cost money in silence:
an ability check that never answered may have been confirmed and billed without our ever
learning its `request_id`.
"""

import asyncio

import pytest

from app.db import queries
from app.db.connection import close_db, get_db, init_db
from app.db.migrate import run_migrations
from app.settings_store import store
from app.verification import gates, ladder
from app.verification.routes import FLASH_CALL, SMS_OUT, TG_GATEWAY

PHONE = "+79851600019"


def _run(body):
    async def go():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("app1", "token-app1")
        await queries.set_app_may_spend("app1", True)
        await store.load()
        return await body()

    try:
        return asyncio.run(go())
    finally:
        asyncio.run(close_db())


async def _attempts(n, *, seconds_ago, route=FLASH_CALL, phone=PHONE):
    """`n` paid rungs attempted that many seconds ago, each on its own verification."""
    db = await get_db()
    for _ in range(n):
        vid = await queries.create_verification("app1", phone, code="1234",
                                                ttl_seconds=300)
        rung_id = await queries.record_verification_rung(vid, route=route,
                                                         outcome=ladder.ATTEMPTING)
        await db.execute(
            "UPDATE verification_rungs SET started_at = datetime('now', ? || ' seconds') "
            " WHERE id = ?", (f"{-int(seconds_ago):+d}", rung_id))
    await db.commit()


# --- the hourly ceiling ----------------------------------------------------------------

def test_the_hourly_ceiling_refuses_and_names_itself():
    async def body():
        await store.set_many({"verification_paid_per_hour": "10"})
        await _attempts(10, seconds_ago=120)
        refusal = await gates.ceiling_gate()()
        assert refusal
        assert "ceiling" in refusal and "10" in refusal

    _run(body)


def test_one_below_the_hourly_ceiling_is_allowed():
    """The positive control. Without it the gate could be refusing everything."""
    async def body():
        await store.set_many({"verification_paid_per_hour": "10"})
        await _attempts(9, seconds_ago=120)
        assert await gates.ceiling_gate()() == ""

    _run(body)


def test_a_gateway_with_no_history_is_allowed():
    async def body():
        assert await gates.ceiling_gate()() == ""

    _run(body)


def test_the_hourly_window_rolls_rather_than_resetting_on_the_clock():
    async def body():
        await store.set_many({"verification_paid_per_hour": "10"})
        await _attempts(10, seconds_ago=3600 + 120)
        assert await gates.ceiling_gate()() == "", \
            "attempts older than the rolling hour must have fallen out of it"
        await _attempts(10, seconds_ago=3000)
        assert await gates.ceiling_gate()(), \
            "attempts 50 minutes old are inside a rolling hour"

    _run(body)


# --- the daily ceiling -----------------------------------------------------------------

def test_the_daily_ceiling_refuses_when_the_hourly_one_would_not():
    """The two are different instruments: a steady trickle never reaches the hour and
    still adds up to a day's worth of money."""
    async def body():
        await store.set_many({"verification_paid_per_hour": "100",
                              "verification_paid_per_day": "20"})
        for i in range(20):
            await _attempts(1, seconds_ago=3600 + i * 900)
        assert await gates.ceiling_gate()(), "twenty in a rolling day is the ceiling"

    _run(body)


def test_the_daily_window_is_rolling_rather_than_a_calendar_day():
    """A calendar day read in the wrong zone resets three hours early, and the gateway
    spends confidently in exactly those three hours."""
    async def body():
        await store.set_many({"verification_paid_per_day": "20"})
        for i in range(20):
            await _attempts(1, seconds_ago=20 * 3600 + i * 60)
        assert await gates.ceiling_gate()(), \
            "a rolling day must still be counting attempts from 20 hours ago"

    _run(body)


# --- task 4.52: the ceiling counts the ladder, not the rung ----------------------------

def test_the_ceiling_counts_both_paid_rungs_together():
    """Neither rung reaches the ceiling alone; the two together do, which is exactly what
    a ladder that advances from one to the other produces."""
    async def body():
        await store.set_many({"verification_paid_per_hour": "10"})
        await _attempts(5, seconds_ago=120, route=TG_GATEWAY)
        await _attempts(5, seconds_ago=130, route=FLASH_CALL)
        assert await gates.ceiling_gate()(), \
            "five Telegram attempts and five calls are ten paid rungs"

    _run(body)


def test_five_on_each_rung_does_not_reach_a_ceiling_of_eleven():
    """The control for the test above: it must be the count that refuses, not the mixing
    of two routes."""
    async def body():
        await store.set_many({"verification_paid_per_hour": "11"})
        await _attempts(5, seconds_ago=120, route=TG_GATEWAY)
        await _attempts(5, seconds_ago=130, route=FLASH_CALL)
        assert await gates.ceiling_gate()() == ""

    _run(body)


def test_the_unpaid_route_does_not_count_towards_the_ceiling():
    """What is bounded is this gateway's spending. A modem message costs nothing here and
    must not be able to refuse a paid verification."""
    async def body():
        await store.set_many({"verification_paid_per_hour": "3"})
        await _attempts(20, seconds_ago=120, route=SMS_OUT)
        assert await gates.ceiling_gate()() == ""

    _run(body)


def test_the_ceiling_counts_every_number_and_every_application():
    """The whole difference from the per-number limits: no single number is anywhere near
    its own limit, and the bill is the same."""
    async def body():
        await store.set_many({"verification_paid_per_hour": "10"})
        for i in range(10):
            await _attempts(1, seconds_ago=120 + i, phone=f"+7985160{i:04d}")
        assert await gates.ceiling_gate()(), \
            "ten different numbers, one attempt each, is still ten paid rungs"

    _run(body)


# --- it is a setting, and it is loud ----------------------------------------------------

def test_the_ceiling_is_changeable_without_a_deploy():
    async def body():
        await store.set_many({"verification_paid_per_hour": "10"})
        await _attempts(6, seconds_ago=120)
        assert await gates.ceiling_gate()() == ""
        await store.set_many({"verification_paid_per_hour": "6"})
        assert await gates.ceiling_gate()()

    _run(body)


def test_a_refusal_alerts_the_operator_on_stock_settings(monkeypatch):
    """A ceiling that refuses silently presents as a gateway that has stopped verifying
    anyone, which is the one symptom nobody attributes to a setting."""
    async def body():
        sent = []
        import app.alerting as alerting
        monkeypatch.setattr(
            alerting, "notify",
            lambda event, text, dedup_extra=None, phone=None: sent.append(
                (event, text, dedup_extra)))

        await store.set_many({"verification_paid_per_hour": "5"})
        await _attempts(5, seconds_ago=120)
        assert await gates.ceiling_gate()()

        assert sent, "the refusal must reach the operator"
        event, text, dedup = sent[0]
        assert event == "routing", \
            "notify_routing_errors is the toggle that is on by default"
        assert "ceiling" in text
        assert dedup and "spend_ceiling" in dedup

    _run(body)


def test_nothing_is_alerted_when_the_ceiling_is_not_reached(monkeypatch):
    async def body():
        sent = []
        import app.alerting as alerting
        monkeypatch.setattr(
            alerting, "notify",
            lambda *a, **kw: sent.append(a))
        await store.set_many({"verification_paid_per_hour": "5"})
        await _attempts(4, seconds_ago=120)
        assert await gates.ceiling_gate()() == ""
        assert sent == []

    _run(body)


# --- task 4.26 / 4.37: the refusal reaches no rung at all ------------------------------

def test_the_ceiling_refuses_before_any_rung_is_contacted():
    """Asserted on the vendor client not being called rather than on the outcome. A gate
    evaluated after a confirmed ability check refuses something already bought, and the
    fee has no refund path of its own."""
    async def body():
        asked = []

        async def carrier(phone, *, seconds_left, rung_id):
            asked.append(phone)
            return ladder.Attempt(outcome=ladder.CARRIED)

        await store.set_many({"verification_paid_per_hour": "3"})
        await _attempts(3, seconds_ago=120)

        vid = await queries.create_verification("app1", PHONE, code="4321",
                                                ttl_seconds=300)
        walk = await ladder.walk(
            vid, app_id="app1", operator="МегаФон", phone=PHONE, rungs=[TG_GATEWAY, FLASH_CALL],
            gates=(gates.ceiling_gate(),),
            carriers={TG_GATEWAY: carrier, FLASH_CALL: carrier}, bound=5.0)

        assert asked == []
        assert "spend_ceiling" in walk.refused_by
        assert await queries.verification_rungs(vid) == []
        assert walk.attempts == ()
        assert walk.reason == "", "a refusal of ours carries no vendor's reason"

    _run(body)


def test_the_refusal_sends_nothing_over_the_modem_instead():
    async def body():
        async def carrier(phone, *, seconds_left, rung_id):
            raise AssertionError("no rung may be contacted")

        await store.set_many({"verification_paid_per_hour": "3"})
        await _attempts(3, seconds_ago=120)

        vid = await queries.create_verification("app1", PHONE, code="4321",
                                                ttl_seconds=300)
        await ladder.walk(
            vid, app_id="app1", operator="МегаФон", phone=PHONE, rungs=[TG_GATEWAY, FLASH_CALL],
            gates=(gates.ceiling_gate(),),
            carriers={TG_GATEWAY: carrier, FLASH_CALL: carrier}, bound=5.0)

        db = await get_db()
        async with db.execute(
            "SELECT COUNT(*) FROM messages WHERE phone = ?", (PHONE,)
        ) as cursor:
            assert (await cursor.fetchone())[0] == 0

    _run(body)


# --- task 4.37: both gates are assembled, and both run before the first rung -----------

def test_the_assembled_gates_run_the_entitlement_and_the_ceiling_before_any_rung():
    """The gate list the paid ladder is walked with is assembled in one place, so that a
    door added later cannot be a door that forgot one. Both refusals are exercised here
    against the same assembled list."""
    async def body():
        asked = []

        async def carrier(phone, *, seconds_left, rung_id):
            asked.append(phone)
            return ladder.Attempt(outcome=ladder.CARRIED)

        async def walk_with_assembled_gates(app_id):
            vid = await queries.create_verification(app_id, PHONE, code="4321",
                                                    ttl_seconds=300)
            return await ladder.walk(
                vid, app_id=app_id, operator="МегаФон", phone=PHONE, rungs=[TG_GATEWAY, FLASH_CALL],
                gates=gates.for_paid_ladder(app_id, PHONE, [TG_GATEWAY, FLASH_CALL]),
                carriers={TG_GATEWAY: carrier, FLASH_CALL: carrier}, bound=5.0)

        # The entitlement half.
        await queries.create_app("unentitled", "token-unentitled")
        walk = await walk_with_assembled_gates("unentitled")
        assert asked == [] and "entitlement" in walk.refused_by

        # The ceiling half, for an application that does hold the entitlement.
        await store.set_many({"verification_paid_per_hour": "3"})
        await _attempts(3, seconds_ago=120)
        walk = await walk_with_assembled_gates("app1")
        assert asked == [] and "spend_ceiling" in walk.refused_by

    _run(body)


def test_the_assembled_gates_let_an_entitled_application_through():
    """The positive control for the assembly: with the entitlement granted, nothing over
    any ceiling and no history on the number, the ladder is attempted normally."""
    async def body():
        asked = []

        async def carrier(phone, *, seconds_left, rung_id):
            asked.append(phone)
            return ladder.Attempt(outcome=ladder.CARRIED)

        vid = await queries.create_verification("app1", PHONE, code="4321",
                                                ttl_seconds=300)
        walk = await ladder.walk(
            vid, app_id="app1", operator="МегаФон", phone=PHONE, rungs=[TG_GATEWAY, FLASH_CALL],
            gates=gates.for_paid_ladder("app1", PHONE, [TG_GATEWAY, FLASH_CALL]),
            carriers={TG_GATEWAY: carrier, FLASH_CALL: carrier}, bound=5.0)

        assert asked == [PHONE]
        assert walk.carried_by == TG_GATEWAY
        assert walk.refused_by == ""

    _run(body)


def test_the_assembled_gates_still_carry_the_per_number_limits():
    """The third gate in the list, and the one that was already built. An assembly that
    quietly dropped it would be invisible in every test above."""
    async def body():
        async def carrier(phone, *, seconds_left, rung_id):
            raise AssertionError("no rung may be contacted")

        await _attempts(1, seconds_ago=2)          # inside the vendor's minimum gap
        vid = await queries.create_verification("app1", PHONE, code="4321",
                                                ttl_seconds=300)
        walk = await ladder.walk(
            vid, app_id="app1", operator="МегаФон", phone=PHONE, rungs=[TG_GATEWAY, FLASH_CALL],
            gates=gates.for_paid_ladder("app1", PHONE, [TG_GATEWAY, FLASH_CALL]),
            carriers={TG_GATEWAY: carrier, FLASH_CALL: carrier}, bound=5.0)

        assert walk.refused_by and "too_soon" in walk.refused_by

    _run(body)
