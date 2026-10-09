"""The per-number limits, held here rather than discovered at the vendor.

uCaller allows four authorisations per number per minute with at least fifteen seconds
between them and thirty per number per day, and a number that exceeds them is blocked by
the vendor for **ten hours**. That is the asymmetry the whole mechanism exists for: being
told to wait fifteen seconds costs a person fifteen seconds, and being blocked at the
vendor costs them a working day of not being able to log in at all.

Three properties are worth more than the numbers, and all three are guarded here:

**The limits are the ladder's, not the flash call's.** Telegram's reference publishes no
rate limits at all, and silence is the absence of a statement rather than a statement of
absence. A rung whose block conditions are unpublished is the one to be more careful
with, not less.

**The window is rolling, not a calendar day.** This database stores naive UTC and the
vendor is Russian: a calendar day read in the wrong zone leaves a three-hour window in
which our counter has reset and theirs has not, and in that window the gateway
confidently places the call that costs the subscriber ten hours. A rolling window is the
stricter of the two readings everywhere, which is what the norm asks for.

🔴 **The allowance is decided and taken in one act**, and since task 4.62 that is what
these tests drive: `limits.claim` both decides and writes the rung's row, so a claim that
answers "allowed" has already taken the slot it allowed. What two arriving requests do to
each other is guarded next door, in
`tests/test_the_numbers_limits_are_taken_in_one_act.py`; what is guarded here is the
arithmetic of the three limits themselves.

Every refusal here has its positive control, because a claim that refused everything would
satisfy each of them on its own.
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


async def _claim(phone=PHONE, *, route=TG_GATEWAY):
    """A fresh verification asks this number's allowance for one paid rung.

    Answers the reason it was refused, or the empty string. A claim that is allowed has
    **taken** the slot — that is the norm rather than an accident of the helper — so a test
    that calls this twice is asking a history that its own first call has moved.
    """
    vid = await queries.create_verification("app1", phone, code="4321", ttl_seconds=300)
    rung_id, refusal = await limits.claim(vid, route=route, phone=phone,
                                          outcome=ladder.ATTEMPTING)
    assert (rung_id is None) == bool(refusal), \
        "a claim answered with a rung and a refusal at once"
    return refusal


# --- the gap between two attempts -----------------------------------------------------

def test_a_second_attempt_inside_the_gap_is_refused_with_the_wait_named():
    async def body():
        await _attempt_at(PHONE, seconds_ago=8)
        refusal = await _claim()
        assert refusal
        assert "wait" in refusal or "too_soon" in refusal

    _run(body)


def test_an_attempt_after_the_gap_has_passed_is_allowed():
    """The positive control. Without it the claim could be refusing everything."""
    async def body():
        await _attempt_at(PHONE, seconds_ago=20)
        assert await _claim() == ""

    _run(body)


def test_a_number_with_no_history_is_allowed():
    async def body():
        assert await _claim() == ""

    _run(body)


def test_an_allowed_claim_records_the_rung_it_allowed():
    """The other half of "decided and taken": an allowance granted and not written is an
    allowance the next request cannot see."""
    async def body():
        vid = await queries.create_verification("app1", PHONE, code="4321",
                                                ttl_seconds=300)
        rung_id, refusal = await limits.claim(vid, route=TG_GATEWAY, phone=PHONE,
                                              outcome=ladder.ATTEMPTING)
        assert refusal == "" and rung_id is not None
        rows = await queries.verification_rungs(vid)
        assert [(r["route"], r["outcome"]) for r in rows] == \
               [(TG_GATEWAY, ladder.ATTEMPTING)]

    _run(body)


# --- the ceilings, counted across the whole ladder ------------------------------------

def test_the_minute_ceiling_counts_both_rungs_together():
    """Task 4.55. Counted per rung, a ladder that advances from Telegram to the call
    passes a ceiling it has in fact reached — and the Gateway publishes no limits of its
    own to catch it."""
    async def body():
        for i, route in enumerate([TG_GATEWAY, FLASH_CALL, TG_GATEWAY, FLASH_CALL]):
            await _attempt_at(PHONE, seconds_ago=20 + i * 5, route=route)
        refusal = await _claim()
        assert refusal, "four attempts in a minute must reach the minute ceiling"
        assert "minute" in refusal

    _run(body)


def test_the_minute_ceiling_is_not_reached_by_three_attempts():
    async def body():
        for i in range(3):
            await _attempt_at(PHONE, seconds_ago=20 + i * 5)
        assert await _claim() == ""

    _run(body)


def test_the_daily_ceiling_refuses_and_names_itself():
    async def body():
        for i in range(30):
            await _attempt_at(PHONE, seconds_ago=3600 + i * 60)
        refusal = await _claim()
        assert refusal and "day" in refusal

    _run(body)


def test_the_daily_window_is_rolling_rather_than_a_calendar_day():
    """A calendar day read in the wrong zone resets three hours early, and in those three
    hours the gateway places the call that costs the subscriber ten hours."""
    async def body():
        for i in range(30):
            # Yesterday evening by the clock, and inside a rolling day.
            await _attempt_at(PHONE, seconds_ago=20 * 3600 + i * 60)
        assert await _claim(), \
            "a rolling window must still be counting attempts from 20 hours ago"

    _run(body)


def test_attempts_on_another_number_do_not_count():
    async def body():
        for i in range(10):
            await _attempt_at(OTHER, seconds_ago=20 + i * 5)
        assert await _claim() == ""

    _run(body)


# --- the limits are the vendor's numbers, not ours ------------------------------------

def test_the_limits_are_configurable_without_a_deploy():
    """The refused claim is asked **first** and the allowed one second, deliberately: a
    claim that is allowed takes the slot it allowed, so asking in the other order would
    leave the second question answering about a history the first one wrote."""
    async def body():
        await _attempt_at(PHONE, seconds_ago=20)
        await _attempt_at(PHONE, seconds_ago=25)

        await store.set_many({"verification_per_minute": "2"})
        refusal = await _claim()
        assert refusal and "minute" in refusal, refusal

        await store.set_many({"verification_per_minute": "4"})
        assert await _claim() == "", \
            "the same history under the vendor's own number must still be allowed"

    _run(body)


# --- and they are taken where the rung is recorded, not in a list a caller assembles ---

def test_a_number_over_its_limit_reaches_no_rung_at_all():
    """Asserted on the vendor not being called rather than on the outcome: the whole
    point of holding the limits here is that nothing is placed.

    🔴 The gate list is handed in **empty**, and that is the norm of task 4.62 rather than
    an economy of the test. The limits are taken at the row that records the attempt, so a
    caller who assembles the list by hand and forgets them cannot spend the subscriber's
    ten-hour block by forgetting.
    """
    async def body():
        asked = []

        async def carrier(phone, *, seconds_left, rung_id):
            asked.append(phone)
            return ladder.Attempt(outcome=ladder.CARRIED)

        await _attempt_at(PHONE, seconds_ago=2)
        vid = await queries.create_verification("app1", PHONE, code="4321",
                                                ttl_seconds=300)
        walk = await ladder.walk(
            vid, app_id="app1", operator="МегаФон", phone=PHONE,
            rungs=[TG_GATEWAY, FLASH_CALL], gates=(),
            carriers={TG_GATEWAY: carrier, FLASH_CALL: carrier}, bound=5.0)

        assert asked == []
        assert walk.refused_by
        assert await queries.verification_rungs(vid) == []

    _run(body)
