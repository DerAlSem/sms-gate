"""The per-number limits, held here rather than discovered at the vendor.

uCaller allows four authorisations per number per minute with at least fifteen seconds
between them and thirty per number per day, and a number that exceeds them is blocked by
the vendor for **ten hours**. That is the asymmetry the whole gate exists for: being told
to wait fifteen seconds costs a person fifteen seconds, and being blocked at the vendor
costs them a working day of not being able to log in at all.

Two properties are worth more than the numbers, and both are guarded here:

**The limits are the ladder's, not the flash call's.** Telegram's reference publishes no
rate limits at all, and silence is the absence of a statement rather than a statement of
absence. A rung whose block conditions are unpublished is the one to be more careful
with, not less.

**The window is rolling, not a calendar day.** This database stores naive UTC and the
vendor is Russian: a calendar day read in the wrong zone leaves a three-hour window in
which our counter has reset and theirs has not, and in that window the gateway
confidently places the call that costs the subscriber ten hours. A rolling window is the
stricter of the two readings everywhere, which is what the norm asks for.
"""

import asyncio

import pytest

from app.db import queries
from app.db.connection import close_db, get_db, init_db
from app.db.migrate import run_migrations
from app.settings_store import store
from app.verification import ladder, limits
from app.verification.routes import FLASH_CALL, TG_GATEWAY

PHONE = "+79851600019"
OTHER = "+79031680015"


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


async def _attempt_at(phone, *, seconds_ago, route=FLASH_CALL):
    """One paid rung attempted for this number, that many seconds ago."""
    vid = await queries.create_verification("app1", phone, code="1234", ttl_seconds=300)
    rung_id = await queries.record_verification_rung(vid, route=route,
                                                     outcome=ladder.CARRIED)
    db = await get_db()
    await db.execute(
        "UPDATE verification_rungs SET started_at = datetime('now', ? || ' seconds') "
        " WHERE id = ?", (f"{-int(seconds_ago):+d}", rung_id))
    await db.commit()
    return vid


# --- the gap between two attempts -----------------------------------------------------

def test_a_second_attempt_inside_the_gap_is_refused_with_the_wait_named():
    async def body():
        await _attempt_at(PHONE, seconds_ago=8)
        refusal = await limits.per_number_gate(PHONE)()
        assert refusal
        assert "wait" in refusal or "too_soon" in refusal

    _run(body)


def test_an_attempt_after_the_gap_has_passed_is_allowed():
    """The positive control. Without it the gate could be refusing everything."""
    async def body():
        await _attempt_at(PHONE, seconds_ago=20)
        assert await limits.per_number_gate(PHONE)() == ""

    _run(body)


def test_a_number_with_no_history_is_allowed():
    async def body():
        assert await limits.per_number_gate(PHONE)() == ""

    _run(body)


# --- the ceilings, counted across the whole ladder ------------------------------------

def test_the_minute_ceiling_counts_both_rungs_together():
    """Task 4.55. Counted per rung, a ladder that advances from Telegram to the call
    passes a ceiling it has in fact reached — and the Gateway publishes no limits of its
    own to catch it."""
    async def body():
        for i, route in enumerate([TG_GATEWAY, FLASH_CALL, TG_GATEWAY, FLASH_CALL]):
            await _attempt_at(PHONE, seconds_ago=20 + i * 5, route=route)
        refusal = await limits.per_number_gate(PHONE)()
        assert refusal, "four attempts in a minute must reach the minute ceiling"
        assert "minute" in refusal

    _run(body)


def test_the_minute_ceiling_is_not_reached_by_three_attempts():
    async def body():
        for i in range(3):
            await _attempt_at(PHONE, seconds_ago=20 + i * 5)
        assert await limits.per_number_gate(PHONE)() == ""

    _run(body)


def test_the_daily_ceiling_refuses_and_names_itself():
    async def body():
        for i in range(30):
            await _attempt_at(PHONE, seconds_ago=3600 + i * 60)
        refusal = await limits.per_number_gate(PHONE)()
        assert refusal and "day" in refusal

    _run(body)


def test_the_daily_window_is_rolling_rather_than_a_calendar_day():
    """A calendar day read in the wrong zone resets three hours early, and in those three
    hours the gateway places the call that costs the subscriber ten hours."""
    async def body():
        for i in range(30):
            # Yesterday evening by the clock, and inside a rolling day.
            await _attempt_at(PHONE, seconds_ago=20 * 3600 + i * 60)
        assert await limits.per_number_gate(PHONE)(), \
            "a rolling window must still be counting attempts from 20 hours ago"

    _run(body)


def test_attempts_on_another_number_do_not_count():
    async def body():
        for i in range(10):
            await _attempt_at(OTHER, seconds_ago=20 + i * 5)
        assert await limits.per_number_gate(PHONE)() == ""

    _run(body)


# --- the limits are the vendor's numbers, not ours ------------------------------------

def test_the_limits_are_configurable_without_a_deploy():
    async def body():
        await _attempt_at(PHONE, seconds_ago=20)
        await _attempt_at(PHONE, seconds_ago=25)
        assert await limits.per_number_gate(PHONE)() == ""
        await store.set_many({"verification_per_minute": "2"})
        assert await limits.per_number_gate(PHONE)()

    _run(body)


# --- and they run before any rung is contacted ----------------------------------------

def test_a_number_over_its_limit_reaches_no_rung_at_all():
    """Asserted on the vendor not being called rather than on the outcome: the whole
    point of holding the limits here is that nothing is placed."""
    async def body():
        asked = []

        async def carrier(phone, *, seconds_left, rung_id):
            asked.append(phone)
            return ladder.Attempt(outcome=ladder.CARRIED)

        await _attempt_at(PHONE, seconds_ago=2)
        vid = await queries.create_verification("app1", PHONE, code="4321",
                                                ttl_seconds=300)
        walk = await ladder.walk(
            vid, app_id="app1", phone=PHONE, rungs=[TG_GATEWAY, FLASH_CALL],
            gates=(limits.per_number_gate(PHONE),),
            carriers={TG_GATEWAY: carrier, FLASH_CALL: carrier}, bound=5.0)

        assert asked == []
        assert walk.refused_by
        assert await queries.verification_rungs(vid) == []

    _run(body)
