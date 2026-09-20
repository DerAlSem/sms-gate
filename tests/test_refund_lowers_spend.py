"""A refund lowers the recorded spend to nothing. Task 4.54.

The vendor is explicit: *"If a message is not delivered within the specified `ttl`, the
request fee will be refunded automatically"*. A verification whose fee came back cost
nothing, and a ledger that keeps the charge and files the refund next to it overstates
the bill in the one direction that makes the paid route look worse than it is — silently,
because every reader would have to remember to subtract.

🔴 **The refund cannot be exercised by a probe.** A confirming ability check is a
statement that the subscriber is reachable, and every message this gateway has sent was
delivered within a second, so the refund path is reached only by a subscriber who was
confirmed reachable and then was not reached. Nothing here is built on having seen one —
these tests drive the recording directly, which is honest about what has been observed
and what has not.

**What stays.** `refunded` still holds the fact, and the vendor's own words still sit in
`reason`. What goes is the number: the spend recorded against the rung, which is the one
thing a bill is read from.
"""

import asyncio

import pytest

from app.db import queries
from app.db.connection import close_db, init_db
from app.db.migrate import run_migrations
from app.verification import ladder
from app.verification.routes import FLASH_CALL, TG_GATEWAY

PHONE = "+79851600019"


def _run(body):
    async def go():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("app1", "token-app1")
        return await body()

    try:
        return asyncio.run(go())
    finally:
        asyncio.run(close_db())


async def _charged_rung(*, vendor_ref="req-1", cost=0.01, route=TG_GATEWAY):
    """A rung that was confirmed and charged, as the carrier leaves it."""
    vid = await queries.create_verification("app1", PHONE, code="1234", ttl_seconds=300)
    rung_id = await queries.record_verification_rung(vid, route=route,
                                                     outcome=ladder.ATTEMPTING)
    await queries.set_rung_outcome(rung_id, outcome=ladder.CARRIED,
                                   vendor_ref=vendor_ref, cost=cost)
    return vid, rung_id


async def _rung(vid):
    rungs = await queries.verification_rungs(vid)
    assert len(rungs) == 1
    return rungs[0]


def test_a_refund_lowers_the_recorded_spend_to_nothing():
    async def body():
        vid, _ = await _charged_rung()
        assert (await _rung(vid))["cost"] == 0.01

        await queries.record_rung_delivery(
            "req-1", route=TG_GATEWAY, outcome="expired",
            reason="the vendor reported the fee refunded", refunded=True)

        row = await _rung(vid)
        assert row["cost"] == 0, \
            "a refunded request must not keep the charge with a note beside it"

    _run(body)


def test_the_refund_stays_recorded_as_a_fact_and_in_the_vendors_words():
    """The spend goes to nothing; what happened does not go with it."""
    async def body():
        vid, _ = await _charged_rung()
        await queries.record_rung_delivery(
            "req-1", route=TG_GATEWAY, outcome="expired",
            reason="the vendor reported the fee refunded", refunded=True)

        row = await _rung(vid)
        assert row["refunded"] == 1
        assert "refund" in (row["reason"] or "")
        assert row["outcome"] == "expired"

    _run(body)


def test_a_delivery_that_was_not_refunded_keeps_its_charge():
    """The positive control, and the expensive direction to get wrong: a delivered
    message is not refunded, and zeroing it would make the paid route look free."""
    async def body():
        vid, _ = await _charged_rung()
        await queries.record_rung_delivery(
            "req-1", route=TG_GATEWAY, outcome="delivered",
            reason="the vendor did not mention the fee", refunded=False)

        row = await _rung(vid)
        assert row["cost"] == 0.01
        assert row["refunded"] == 0

    _run(body)


def test_the_vendor_not_mentioning_the_refund_is_not_a_refund():
    """`is_refunded` has been absent from ten captures running, and absence may not be
    read as either answer. Read as a refund it would zero every delivered message."""
    async def body():
        vid, _ = await _charged_rung()
        await queries.record_rung_delivery(
            "req-1", route=TG_GATEWAY, outcome="delivered",
            reason="the vendor did not mention the fee")

        assert (await _rung(vid))["cost"] == 0.01

    _run(body)


def test_a_refunded_rung_is_not_recharged_by_a_later_outcome():
    """The invariant put at the write rather than left as a note. Nothing in the ordinary
    sequence writes a cost after a refund — the charge is recorded between the ability
    check and the send, and the refund arrives with a callback long after — but a
    resurrected charge would be a bill nobody could explain."""
    async def body():
        vid, rung_id = await _charged_rung()
        await queries.record_rung_delivery(
            "req-1", route=TG_GATEWAY, outcome="expired",
            reason="refunded", refunded=True)
        assert (await _rung(vid))["cost"] == 0

        await queries.set_rung_outcome(rung_id, outcome=ladder.FAILED, cost=0.01)

        assert (await _rung(vid))["cost"] == 0, \
            "a settled refund must not be undone by a later write"

    _run(body)


def test_only_the_refunded_rung_of_a_ladder_is_lowered():
    """A verification that advanced from Telegram to the call holds two charges against
    one code, and a refund at one vendor says nothing about the other."""
    async def body():
        vid = await queries.create_verification("app1", PHONE, code="1234",
                                                ttl_seconds=300)
        tg = await queries.record_verification_rung(vid, route=TG_GATEWAY,
                                                    outcome=ladder.ATTEMPTING)
        await queries.set_rung_outcome(tg, outcome=ladder.FAILED,
                                       vendor_ref="req-1", cost=0.01)
        call = await queries.record_verification_rung(vid, route=FLASH_CALL,
                                                      outcome=ladder.ATTEMPTING)
        await queries.set_rung_outcome(call, outcome=ladder.CARRIED,
                                       vendor_ref="uc-1", cost=3.5)

        await queries.record_rung_delivery("req-1", route=TG_GATEWAY, outcome="expired",
                                           reason="refunded", refunded=True)

        by_route = {r["route"]: r for r in await queries.verification_rungs(vid)}
        assert by_route[TG_GATEWAY]["cost"] == 0
        assert by_route[FLASH_CALL]["cost"] == 3.5, \
            "a refund at one vendor must not touch the other vendor's charge"

    _run(body)


def test_a_refund_for_a_request_no_rung_holds_changes_nothing():
    """A correctly signed callback naming a request we have no record of is the vendor's,
    and arguing with it is not this layer's job — but it must not lower anything."""
    async def body():
        vid, _ = await _charged_rung()
        assert await queries.record_rung_delivery(
            "req-someone-elses", route=TG_GATEWAY, outcome="expired",
            refunded=True) is None
        assert (await _rung(vid))["cost"] == 0.01

    _run(body)


def test_a_refund_is_matched_on_the_vendor_and_the_reference_together():
    """A vendor reference is unique at its own vendor and this gateway has two. The day
    the second issues the same digits, an unqualified match would zero the wrong rung."""
    async def body():
        vid, _ = await _charged_rung(vendor_ref="shared-ref", route=FLASH_CALL, cost=3.5)
        await queries.record_rung_delivery("shared-ref", route=TG_GATEWAY,
                                           outcome="expired", refunded=True)
        assert (await _rung(vid))["cost"] == 3.5, \
            "a Telegram refund must not lower a call's charge that shares its reference"

    _run(body)
