"""A rung that calls its vendor twice does not spend the ladder's bound twice: task 4.63.

Found by the critic circle of 22.09.2026. The norm said "each carrier SHALL apply it to its
own vendor calls", and that sentence is satisfied by handing every call the *whole* of what
the rung was given. `tg_carrier` did exactly that: `seconds_left` is computed once, on entry,
and passed to `checkSendAbility` and again to `sendVerificationMessage`. Its neighbour
`flash_carrier`, under the same norm, takes a deadline on entry and spends what is left of
it — two carriers, one norm, opposite implementations, and no guard that could tell them
apart, because every existing one only asks whether the bound *reached* the vendor.

What it costs: the ability check answers slowly but within the bound, the send is then handed
the bound again, and the door answers at up to twice the time the application was promised.
`ladder.walk` then finds `seconds_left <= 0` and stops, so the next rung is never tried —
the ladder silently stops being a ladder on exactly the slow day it exists for.

The control matters as much as the assertion here: a carrier that passed `0.1` to everything
would satisfy "the second is smaller" while breaking the rung outright.
"""

import asyncio
import time

import pytest

from app.db import queries
from app.db.connection import close_db, init_db
from app.db.migrate import run_migrations
from app.settings_store import store
from app.verification import ladder, tg_carrier, tg_gateway

PHONE = "+79261234999"
BOUND = 10.0
SPENT_BY_THE_CHECK = 0.30


@pytest.fixture
def seen(monkeypatch):
    """Record the timeout each vendor call is handed, and make the first one slow."""
    timeouts = {}

    async def check_send_ability(phone, *, token, timeout):
        timeouts["check"] = timeout
        await asyncio.sleep(SPENT_BY_THE_CHECK)
        return tg_gateway.Ability(
            kind=tg_gateway.ABLE, request_id="req-1",
            status=tg_gateway.RequestStatus(
                request_id="req-1", phone_number=PHONE.lstrip("+"), request_cost=0.4,
                remaining_balance=None),
            error="")

    async def send_verification_message(phone, *, code, ttl, token, request_id,
                                        callback_url, sender_username, timeout):
        timeouts["send"] = timeout
        return tg_gateway.Sent(ok=True, error="")

    monkeypatch.setattr(tg_gateway, "check_send_ability", check_send_ability)
    monkeypatch.setattr(tg_gateway, "send_verification_message", send_verification_message)
    return timeouts


def _run(coro_factory):
    async def go():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("app1", "token-app1")
        await store.load()
        try:
            return await coro_factory()
        finally:
            await close_db()
    return asyncio.run(go())


def _carry(timeouts):
    async def body():
        vid = await queries.create_verification("app1", PHONE, code="4321",
                                                ttl_seconds=300)
        rung_id = await queries.record_verification_rung(
            vid, route="tg_gateway", outcome=ladder.ATTEMPTING)
        carry = tg_carrier.carrier(vid, app_id="app1", token="t",
                                   callback_url="")
        started = time.monotonic()
        attempt = await carry(PHONE, seconds_left=BOUND, rung_id=rung_id)
        return attempt, time.monotonic() - started
    return _run(body)


def test_the_second_vendor_call_gets_what_is_left_of_the_bound(seen):
    attempt, _ = _carry(seen)

    assert "check" in seen and "send" in seen, f"a vendor call was not made: {seen}"
    assert seen["send"] < seen["check"] - SPENT_BY_THE_CHECK / 2, (
        f"the send was handed {seen['send']:.2f}s after the check had already spent "
        f"{SPENT_BY_THE_CHECK}s of a {BOUND}s bound — the rung is spending the ladder's "
        f"budget twice")


def test_the_rung_is_still_given_a_workable_bound(seen):
    """The control: 'smaller' must not be satisfied by handing everything a floor value."""
    _carry(seen)

    assert seen["check"] == pytest.approx(BOUND, abs=0.05), seen
    assert seen["send"] > BOUND / 2, (
        f"the send was left only {seen['send']:.2f}s of a {BOUND}s bound; that is not a "
        f"deadline, it is a floor")
