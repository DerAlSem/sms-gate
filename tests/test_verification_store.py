"""A verification is a stored thing with an owner, a deadline and a secret that stops
existing.

The store is written before any door onto it, because every guarantee the capability makes
is a property of these rows: that a verification belongs to one application, that it can be
confirmed once, that four digits are survivable only because attempts are bounded, and that
the row stops holding a live secret the moment it stops being usable.

Two rules here are about *how* rather than *what*, and they are the ones that break under
load rather than under review. Confirming and consuming an attempt are each decided by a
single conditional update, on the rows it changed — not by reading the state and writing it
back, because a person standing at a barrier double-taps Confirm as a matter of course. And
a code stops being readable at the moment the verification stops being confirmable, not at
some later tidying pass.
"""

import asyncio

import pytest

from app.db import queries
from app.db.connection import close_db, get_db, init_db
from app.db.migrate import run_migrations
from app.settings_store import store

# The shipped bound, read once: the tests are about the rule, not the number.
LIMIT = 5

PHONE = "+79261234888"
OTHER = "+79031680015"


def _run(body):
    async def go():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("app1", "token-app1")
        await queries.create_app("app2", "token-app2")
        await store.load()
        return await body()

    try:
        return asyncio.run(go())
    finally:
        asyncio.run(close_db())


async def _open(app_id="app1", phone=PHONE, code="1234", ttl=300):
    return await queries.create_verification(app_id, phone, code=code, ttl_seconds=ttl)


# --- the row itself --------------------------------------------------------------------

def test_a_verification_is_persisted_with_its_owner_deadline_and_state():
    async def body():
        vid = await _open()
        row = await queries.get_verification(vid, "app1")
        return dict(row)

    row = _run(body)
    assert row["app_id"] == "app1"
    assert row["phone"] == PHONE
    assert row["status"] == "pending"
    assert row["attempts"] == 0
    assert row["expires_at"] > row["created_at"]


def test_a_verification_answers_only_to_the_application_that_opened_it():
    """One application's token walking another's verifications by id is worse than a read:
    it spends their attempts, locking a real person out of a barrier they are standing at.
    Indistinguishable from missing, so the id itself tells the caller nothing."""
    async def body():
        vid = await _open(app_id="app1")
        seen = await queries.get_verification(vid, "app2")
        outcome = await queries.check_verification(vid, "app2", max_attempts=LIMIT, code="1234")
        mine = await queries.get_verification(vid, "app1")
        return seen, outcome, dict(mine)["attempts"]

    seen, outcome, attempts = _run(body)
    assert seen is None
    assert outcome == "not_found"
    assert attempts == 0, "a stranger's wrong code must not spend the owner's attempts"


def test_two_open_verifications_for_one_number_do_not_share_a_code():
    """Two codes alike would make an arriving answer attributable to neither with
    certainty, which is the one job the code has."""
    async def body():
        await queries.create_verification("app1", PHONE, code="1234", ttl_seconds=300)
        taken = await queries.open_codes_for(PHONE)
        # A second for the same number, and one for a different number.
        await queries.create_verification("app1", OTHER, code="1234", ttl_seconds=300)
        return taken, await queries.open_codes_for(PHONE)

    taken, still = _run(body)
    assert taken == {"1234"}
    assert still == {"1234"}, "another number's code is not this number's business"


# --- confirming, once ------------------------------------------------------------------

def test_the_right_code_confirms_and_records_when():
    async def body():
        vid = await _open()
        outcome = await queries.check_verification(vid, "app1", max_attempts=LIMIT, code="1234")
        row = dict(await queries.get_verification(vid, "app1"))
        return outcome, row

    outcome, row = _run(body)
    assert outcome == "confirmed"
    assert row["status"] == "confirmed"
    assert row["confirmed_at"] is not None
    assert row["confirmed_by"] == "check"


def test_the_same_code_checked_twice_does_not_confirm_twice():
    async def body():
        vid = await _open()
        first = await queries.check_verification(vid, "app1", max_attempts=LIMIT, code="1234")
        second = await queries.check_verification(vid, "app1", max_attempts=LIMIT, code="1234")
        return first, second

    assert _run(body) == ("confirmed", "already_confirmed")


def test_a_confirmed_verification_stops_holding_a_usable_secret():
    """The row holds a subscriber's number together with a live secret. It stops being a
    secret the moment it stops being usable, not at some later tidying pass."""
    async def body():
        vid = await _open()
        await queries.check_verification(vid, "app1", max_attempts=LIMIT, code="1234")
        db = await get_db()
        async with db.execute(
            "SELECT code FROM verifications WHERE id = ?", (vid,)
        ) as cur:
            return (await cur.fetchone())[0]

    assert _run(body) is None


def test_two_checks_at_once_confirm_at_most_once():
    """A person at a barrier double-taps Confirm. Decided by one conditional update on the
    rows it changed, so the loser of the race sees "already confirmed" rather than both
    winning a read-then-write."""
    async def body():
        vid = await _open()
        outcomes = await asyncio.gather(
            queries.check_verification(vid, "app1", max_attempts=LIMIT, code="1234"),
            queries.check_verification(vid, "app1", max_attempts=LIMIT, code="1234"),
        )
        return sorted(outcomes)

    assert _run(body) == ["already_confirmed", "confirmed"]


# --- the attempt limit, which is what makes four digits survivable ---------------------

def test_wrong_codes_are_bounded_and_the_right_one_afterwards_is_too_late():
    """Four digits is a small space; without a limit a caller reaches the right answer in
    a few thousand requests. Five is `blacklist_threshold` — one answer to "enough"."""
    async def body():
        vid = await _open()
        seen = [
            await queries.check_verification(vid, "app1", max_attempts=LIMIT, code="0000")
            for _ in range(LIMIT)
        ]
        after = await queries.check_verification(vid, "app1", max_attempts=LIMIT, code="1234")
        return seen, after

    seen, after = _run(body)
    assert seen[:-1] == ["wrong_code"] * (LIMIT - 1)
    assert after == "no_attempts_left", "the right code must not rescue an exhausted one"


def test_an_exhausted_verification_stops_holding_a_usable_secret():
    async def body():
        vid = await _open()
        for _ in range(LIMIT):
            await queries.check_verification(vid, "app1", max_attempts=LIMIT, code="0000")
        db = await get_db()
        async with db.execute(
            "SELECT code, status FROM verifications WHERE id = ?", (vid,)
        ) as cur:
            return tuple(await cur.fetchone())

    assert _run(body) == (None, "failed")


def test_two_wrong_checks_at_once_spend_one_attempt_each_and_no_more():
    async def body():
        vid = await _open()
        await asyncio.gather(
            queries.check_verification(vid, "app1", max_attempts=LIMIT, code="0000"),
            queries.check_verification(vid, "app1", max_attempts=LIMIT, code="0000"),
        )
        return dict(await queries.get_verification(vid, "app1"))["attempts"]

    assert _run(body) == 2


# --- the deadline ----------------------------------------------------------------------

def test_the_right_code_after_expiry_does_not_confirm_and_says_so():
    async def body():
        vid = await _open(ttl=-1)          # already past its deadline
        return await queries.check_verification(vid, "app1", max_attempts=LIMIT, code="1234")

    assert _run(body) == "expired"


def test_the_sweep_expires_what_nobody_came_back_for():
    """An expiry computed only when somebody next asks never fires for the case that
    matters: the person who never got the call has no reason to come back with a code."""
    async def body():
        stale = await _open(ttl=-1)
        live = await _open(code="5678")
        swept = await queries.expire_due_verifications()
        db = await get_db()
        async with db.execute(
            "SELECT id, status, code FROM verifications ORDER BY id"
        ) as cur:
            rows = [tuple(r) for r in await cur.fetchall()]
        return stale, live, swept, rows

    stale, live, swept, rows = _run(body)
    assert swept == [stale], "the sweep took the wrong rows"
    assert rows == [(stale, "expired", None), (live, "pending", "5678")]


def test_the_sweep_hands_each_expiry_over_exactly_once():
    """Notified once per verification. A sweep that returns the same row on its next pass
    would tell the application its verification expired twice."""
    async def body():
        await _open(ttl=-1)
        first = await queries.expire_due_verifications()
        second = await queries.expire_due_verifications()
        return first, second

    first, second = _run(body)
    assert len(first) == 1 and second == []


# --- retention -------------------------------------------------------------------------

def test_finished_verifications_are_removed_once_past_their_retention():
    """This row holds a subscriber's number. Every other store here that holds subscriber
    data has a retention rule, and this one has the strongest reason for it."""
    async def body():
        vid = await _open()
        await queries.check_verification(vid, "app1", max_attempts=LIMIT, code="1234")
        db = await get_db()
        await db.execute(
            "UPDATE verifications SET created_at = datetime('now', '-40 days')")
        await db.commit()
        live = await _open(code="5678")
        gone = await queries.prune_verifications(max_age_days=30)
        remaining = await queries.get_verification(live, "app1")
        return gone, remaining is not None

    assert _run(body) == (1, True)


def test_retention_does_not_take_a_verification_somebody_is_standing_at():
    """Age alone is not the rule: an open verification past the retention window is a
    person still waiting, and deleting it answers their barrier with a 404."""
    async def body():
        vid = await _open()
        db = await get_db()
        await db.execute(
            "UPDATE verifications SET created_at = datetime('now', '-40 days')")
        await db.commit()
        gone = await queries.prune_verifications(max_age_days=30)
        return gone, await queries.get_verification(vid, "app1") is not None

    assert _run(body) == (0, True)
