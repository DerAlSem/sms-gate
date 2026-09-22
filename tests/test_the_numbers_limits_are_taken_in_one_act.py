"""The per-number limits are decided and taken in one act: task 4.62.

Found by the critic circle of 22.09.2026. The gate asked what this number had already
spent, and the row recording *this* attempt was written only after every gate had passed
— so two verifications for one number, which this capability **explicitly permits**, both
read an empty history, both were allowed, and both reached a vendor inside a gap the
gateway promised would be fifteen seconds. The claim on the route does not close it: it
is keyed on the verification, and these are two verifications.

The cost is not the second call. It is the vendor holding the number for **ten hours**,
which is the outcome the whole limit exists to prevent and the one thing nothing we do
afterwards shortens.

🔴 **The obvious remedy is wrong, and this file guards against it twice.** Writing the
`attempting` row before the gate makes it a paid attempt aged zero seconds against a
minimum gap of fifteen: it refuses the very selection that wrote it. The same trap bites
one level deeper — a ladder's second paid rung is written while the first one's row is
zero seconds old, so a claim that counted this verification's own rungs would make the
ladder unable to advance at all, and every neighbouring guard would stay green because
they all walk a ladder of one rung that carries.

Every property here carries its control, because a claim that refuses everything satisfies
"the vendor was contacted once" perfectly:

- two selections for one number → one carried — controlled by two selections for **two**
  numbers, where both are carried and the vendor is contacted twice;
- the refused one records no rung — controlled by the carried one recording exactly one;
- the ladder advances from the first paid rung to the second inside one walk.

The gates are handed in **empty** throughout. That is the point of the norm rather than an
economy of the test: the limits are enforced where the row is written, so a caller that
forgets the gate list cannot spend the subscriber's ten hours by forgetting.
"""

import asyncio

import pytest

from app.db import queries
from app.db.connection import close_db, init_db
from app.db.migrate import run_migrations
from app.settings_store import store
from app.verification import ladder
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


def _carrier(asked, outcome=ladder.CARRIED):
    """A carrier that yields to the event loop before answering.

    The yield is what makes the race reachable at all: without it the first walk runs to
    its vendor call and back before the second one starts, and the test would pass against
    the defect it exists to catch.
    """
    async def carrier(phone, *, seconds_left, rung_id):
        asked.append(phone)
        await asyncio.sleep(0)
        return ladder.Attempt(outcome=outcome)

    return carrier


async def _walk(vid, phone, rungs, carriers):
    return await ladder.walk(
        vid, app_id="app1", operator="МегаФон", phone=phone, rungs=list(rungs),
        gates=(), carriers=carriers, bound=5.0)


# --- two selections for one number, arriving together ---------------------------------

def test_two_selections_for_one_number_reach_the_vendor_once():
    async def body():
        asked = []
        carriers = {TG_GATEWAY: _carrier(asked)}
        ids = [await queries.create_verification("app1", PHONE, code=c, ttl_seconds=300)
               for c in ("1111", "2222")]

        walks = await asyncio.gather(
            *[_walk(vid, PHONE, [TG_GATEWAY], carriers) for vid in ids])

        assert len(asked) == 1, (
            f"the vendor was contacted {len(asked)} times for one number inside the "
            f"fifteen-second gap; that is the ten-hour block this limit exists to prevent")
        assert sum(1 for w in walks if w.carried_by) == 1
        refused = [w for w in walks if w.refused_by]
        assert len(refused) == 1, "the second selection was not refused by the limits"
        assert "too_soon" in refused[0].refused_by, refused[0].refused_by

    _run(body)


def test_two_selections_for_two_numbers_are_both_carried():
    """The control. A claim that refuses everything satisfies the test above perfectly."""
    async def body():
        asked = []
        carriers = {TG_GATEWAY: _carrier(asked)}
        pairs = [(await queries.create_verification("app1", p, code=c, ttl_seconds=300), p)
                 for p, c in ((PHONE, "1111"), (OTHER, "2222"))]

        walks = await asyncio.gather(
            *[_walk(vid, phone, [TG_GATEWAY], carriers) for vid, phone in pairs])

        assert len(asked) == 2, "two different numbers do not share a per-number limit"
        assert all(w.carried_by == TG_GATEWAY for w in walks)

    _run(body)


def test_the_refused_selection_records_no_rung():
    """Our own refusal is not a row in the count of what the vendors did — and the
    carried one is, which is the control that the recording works at all."""
    async def body():
        asked = []
        carriers = {TG_GATEWAY: _carrier(asked)}
        ids = [await queries.create_verification("app1", PHONE, code=c, ttl_seconds=300)
               for c in ("1111", "2222")]

        walks = await asyncio.gather(
            *[_walk(vid, PHONE, [TG_GATEWAY], carriers) for vid in ids])

        rungs = {vid: await queries.verification_rungs(vid) for vid in ids}
        carried = [vid for vid, w in zip(ids, walks) if w.carried_by]
        refused = [vid for vid, w in zip(ids, walks) if w.refused_by]
        assert len(rungs[carried[0]]) == 1
        assert rungs[refused[0]] == [], (
            "a refusal of ours was recorded as a rung the vendor was asked for")

    _run(body)


# --- and the ladder still advances inside one walk ------------------------------------

def test_a_ladder_advances_from_one_paid_rung_to_the_next():
    """🔴 The mutation only this guard catches: a claim that counts this verification's
    own rungs.

    The second paid rung is claimed while the first one's row is zero seconds old against
    a minimum gap of fifteen. A claim that read its own walk would refuse it — and every
    other guard in this file stays green, because they all walk a ladder of one rung.
    """
    async def body():
        asked = []

        async def declines(phone, *, seconds_left, rung_id):
            asked.append(TG_GATEWAY)
            await asyncio.sleep(0)
            return ladder.Attempt(outcome=ladder.DECLINED,
                                  reason="the Gateway cannot reach this subscriber")

        carriers = {TG_GATEWAY: declines, FLASH_CALL: _carrier(asked)}
        vid = await queries.create_verification("app1", PHONE, code="1111",
                                                ttl_seconds=300)

        walk = await _walk(vid, PHONE, [TG_GATEWAY, FLASH_CALL], carriers)

        assert walk.carried_by == FLASH_CALL, (
            f"the ladder could not advance past its own first rung: "
            f"{walk.refused_by or walk.reason}")
        assert asked == [TG_GATEWAY, PHONE]
        assert len(await queries.verification_rungs(vid)) == 2

    _run(body)
