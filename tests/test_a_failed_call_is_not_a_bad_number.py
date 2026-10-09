# tests/test_a_failed_call_is_not_a_bad_number.py
"""Task 4.21, second half: a call that fails to connect is not a fact about the number.

The permanent-failure count is the **modem's**. `record_permanent_fail` has exactly one
caller in the application — `app/modem/manager.py`, on a delivery report whose TP-status
says the SMSC has stopped trying — and crossing `blacklist_threshold` blocks the number
outright: `POST /verifications` refuses it before opening anything, `POST /send` refuses
it, the sender skips it and the Telegram poller refuses it. It is the one state in this
gateway that shuts every route to a person at once, and nothing clears it but a hand.

A `flash_call` the vendor could not connect says nothing about any of that. The phone was
off, or busy, or the vendor's route to that operator failed; none of it is evidence that an
SMS could not be written to them — and the whole reason this change exists is that МегаФон
subscribers are exactly the people the modem route has been failing, which is when the
gateway calls them instead. Counted, five unconnected calls would blacklist a number that
texts perfectly well, and the next verification for it is refused at the door.

**Guarded by running the rung rather than by reading it.** The property is an absence, and
an absence reads as satisfied in any implementation that never exercises the path — the
unwritten one included. So both endings are driven here against a live database:

- the carrier's own not-connected branch, which is the ladder's answer inside the bound;
- `resolve_outstanding`, which reaches the same ending a minute later for the rung the
  ladder stopped waiting on. That is the path a later change forgets, because it is the
  one that does not look like a failure while it is being written.

And both are paired with the control that the counter is alive and does move for the thing
it is actually about, without which every assertion here passes against a table nothing
ever writes to.
"""

from __future__ import annotations

import asyncio

from app.db import queries
from app.db.connection import close_db, init_db
from app.db.migrate import run_migrations
from app.settings_store import store
from app.verification import flash_carrier, ladder, ucaller
from app.verification.routes import FLASH_CALL

PHONE = "+79851600019"
BEARER = "SECRET.747277"


def _run(body):
    async def go():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("app1", "token-app1")
        await store.load()
        await store.set_many({"ucaller_key": "SECRET", "ucaller_service_id": "747277"})
        return await body()

    try:
        return asyncio.run(go())
    finally:
        asyncio.run(close_db())


def _vendor(monkeypatch, *, call_status):
    """uCaller allocating an authorisation and then reporting this outcome for it."""
    async def init_call(phone, *, code, unique, bearer, timeout=10.0, client=None,
                        client_label=""):
        return ucaller.Call(kind=ucaller.ACCEPTED, placed=ucaller.Placed(
            ucaller_id=57251313, code=code, phone="7985***019", status=True))

    async def get_info(uid, *, bearer, timeout=10.0, client=None):
        return ucaller.Fetched(kind=ucaller.ACCEPTED, info=ucaller.Info(
            ucaller_id=uid, call_status=call_status, code="1234", cost=0.8,
            balance_before=100.8))

    monkeypatch.setattr(ucaller, "init_call", init_call)
    monkeypatch.setattr(ucaller, "get_info", get_info)


async def _carry_one_call(phone=PHONE):
    """One whole rung, from `initCall` to the ladder's answer."""
    vid = await queries.create_verification("app1", phone, code="1234", ttl_seconds=300)
    rung_id = await queries.record_verification_rung(vid, route=FLASH_CALL,
                                                     outcome=ladder.ATTEMPTING)
    carry = flash_carrier.carrier(vid, app_id="app1", bearer=BEARER)
    attempt = await carry(phone, seconds_left=5.0, rung_id=rung_id)
    await queries.set_rung_outcome(rung_id, outcome=attempt.outcome,
                                   reason=attempt.reason or None,
                                   vendor_ref=attempt.vendor_ref, cost=attempt.cost)
    return vid, attempt


async def _unresolved_rung(phone=PHONE):
    """A rung exactly where the ladder left it when the vendor was still thinking."""
    vid = await queries.create_verification("app1", phone, code="1234", ttl_seconds=300)
    rung_id = await queries.record_verification_rung(vid, route=FLASH_CALL,
                                                     outcome=ladder.ATTEMPTING)
    await queries.set_rung_outcome(rung_id, outcome=ladder.UNRESOLVED,
                                   vendor_ref="57251313")
    await queries.select_route(vid, "app1", route=FLASH_CALL)
    return vid


async def _fail_count(phone=PHONE) -> int | None:
    """This number's permanent-failure count, or `None` if it has no row at all."""
    for row in await queries.list_bad_numbers():
        if row["phone"] == phone:
            return row["fail_count"]
    return None


# --- the ladder's own ending ----------------------------------------------------------

def test_a_call_that_could_not_connect_leaves_the_number_uncounted(monkeypatch):
    def body():
        async def run():
            _vendor(monkeypatch, call_status=ucaller.NOT_CONNECTED)
            _, attempt = await _carry_one_call()
            assert attempt.outcome == ladder.FAILED, attempt
            assert await _fail_count() is None, (
                "an unconnected call opened a bad-numbers row for a subscriber the modem "
                "may well be able to text")
            assert not await queries.is_phone_blocked(PHONE)
        return run()

    _run(body)


def test_the_threshold_is_not_reached_by_failed_calls_however_many(monkeypatch):
    """🔴 The load-bearing one. A single uncounted call is also what a gateway that
    counts one per *verification* looks like; the ceiling is what tells them apart, and
    the ceiling is where the damage is — at `blacklist_threshold` the number stops being
    reachable by any route this gateway has, silently, until somebody clears it."""
    def body():
        async def run():
            _vendor(monkeypatch, call_status=ucaller.NOT_CONNECTED)
            for _ in range(store.blacklist_threshold + 1):
                await _carry_one_call()
            assert await _fail_count() is None
            assert not await queries.is_phone_blocked(PHONE), (
                f"{store.blacklist_threshold + 1} unconnected calls blocked this number "
                "on every route the gateway has")
        return run()

    _run(body)


def test_a_call_that_connects_leaves_it_uncounted_too(monkeypatch):
    """The other half of the same statement: the count does not move on this rung in
    either direction. A rung that *cleared* a count would be just as wrong — it would be
    the call route voting on what the modem has learned."""
    def body():
        async def run():
            await queries.record_permanent_fail(PHONE, "boom", 99)
            _vendor(monkeypatch, call_status=ucaller.PLACED)
            _, attempt = await _carry_one_call()
            assert attempt.outcome == ladder.CARRIED, attempt
            assert await _fail_count() == 1, "the call rung rewrote the modem's count"
        return run()

    _run(body)


# --- the ending that arrives after the ladder has stopped waiting ---------------------

def test_the_sweep_that_settles_a_late_failure_does_not_count_it_either(monkeypatch):
    """The path that does not look like a failure while it is being written: by the time
    this runs, the person's verification is being failed and the cost recorded, which is
    exactly the shape into which "and mark the number bad" gets added."""
    def body():
        async def run():
            _vendor(monkeypatch, call_status=ucaller.NOT_CONNECTED)
            vid = await _unresolved_rung()

            assert await flash_carrier.resolve_outstanding() == 1
            row = await queries.get_verification(vid, "app1")
            assert row["status"] == "failed", "the sweep did not reach the failing branch"

            assert await _fail_count() is None, (
                "the late sweep counted an unconnected call against the number")
            assert not await queries.is_phone_blocked(PHONE)
        return run()

    _run(body)


# --- the control: the counter is alive, and it belongs to the modem -------------------

def test_the_permanent_failure_count_does_move_for_what_it_is_about(monkeypatch):
    """Without this every assertion above passes against a table nothing writes to — and
    it would have passed on the day the blacklist stopped working entirely."""
    def body():
        async def run():
            threshold = store.blacklist_threshold
            for i in range(threshold):
                await queries.record_permanent_fail(PHONE, "unknown subscriber", threshold)
                assert await _fail_count() == i + 1
            assert await queries.is_phone_blocked(PHONE), (
                "the modem's own permanent failures no longer block a number")
        return run()

    _run(body)


def test_a_blocked_number_stays_blocked_when_its_call_fails(monkeypatch):
    """The failing direction of the same seam. The call rung must not *clear* a block
    either — a number blocked by the modem and then called is still blocked, and the
    refusal the next verification gets is the door's."""
    def body():
        async def run():
            await queries.block_phone(PHONE)
            _vendor(monkeypatch, call_status=ucaller.NOT_CONNECTED)
            await _carry_one_call()
            assert await queries.is_phone_blocked(PHONE)
        return run()

    _run(body)
