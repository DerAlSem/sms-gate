"""The Telegram rung as the ladder sees it: what it buys, in what order, and what it
refuses to buy twice.

This is where the proved vendor half meets the driver. Everything here is about money
ordering rather than about the wire — the wire is covered by
`tests/test_tg_gateway_adapter.py` against samples captured from the live Gateway.

The rule the whole file exists for: **a confirmed ability check is a fee already
incurred**, it has no refund path of its own, and the vendor's own refund is tied to
non-delivery within a `ttl` that does not start until a message is sent. So the charge is
recorded before the send is attempted, the send that follows is made exactly once, and a
rung that accepted and then failed does not hand the verification to the dearer rung —
that would buy the same code twice.
"""

import asyncio

import pytest

from app.db import queries
from app.db.connection import close_db, init_db
from app.db.migrate import run_migrations
from app.settings_store import store
from app.verification import ladder, tg_gateway
from app.verification.routes import FLASH_CALL, TG_GATEWAY

PHONE = "+79851600019"
TOKEN = "a-token"


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


def _able(request_id="req-1", cost=0.01, balance=99.99):
    return tg_gateway.Ability(
        kind=tg_gateway.ABLE, request_id=request_id,
        status=tg_gateway.RequestStatus(
            request_id=request_id, phone_number=PHONE.lstrip("+"),
            request_cost=cost, remaining_balance=balance))


def _patch(monkeypatch, *, ability, sent=None, checks=None, sends=None):
    async def check(phone, *, token, timeout=5.0, client=None):
        if checks is not None:
            checks.append({"phone": phone, "token": token, "timeout": timeout})
        if isinstance(ability, Exception):
            raise ability
        return ability

    async def send(phone, *, code, ttl, token, request_id=None, callback_url="",
                   payload="", sender_username="", timeout=10.0, client=None):
        if sends is not None:
            sends.append({"phone": phone, "code": code, "ttl": ttl,
                          "request_id": request_id, "timeout": timeout})
        return sent

    monkeypatch.setattr(tg_gateway, "check_send_ability", check)
    monkeypatch.setattr(tg_gateway, "send_verification_message", send)


def _ok_send(request_id="req-1"):
    return tg_gateway.Sent(ok=True, status=tg_gateway.RequestStatus(
        request_id=request_id, phone_number=PHONE.lstrip("+"), request_cost=0.01,
        delivery_status="sent"))


# --- the cheap half: a decline costs nothing ------------------------------------------

def test_a_declined_subscriber_costs_nothing_and_no_send_is_attempted(monkeypatch):
    async def body():
        sends = []
        _patch(monkeypatch,
               ability=tg_gateway.Ability(kind=tg_gateway.DECLINED,
                                          error="PHONE_NUMBER_NOT_AVAILABLE"),
               sends=sends)
        vid = await _open()
        rung_id = await queries.record_verification_rung(
            vid, route=TG_GATEWAY, outcome=ladder.ATTEMPTING)
        carry = tg_gateway_carrier_for(vid)
        attempt = await carry(PHONE, seconds_left=5.0, rung_id=rung_id)

        assert attempt.outcome == ladder.DECLINED
        assert attempt.reason == "PHONE_NUMBER_NOT_AVAILABLE"
        assert attempt.cost is None
        assert sends == [], "a declined subscriber must not be sent to"

    _run(body)


# --- the dear half: the fee is recorded before the send -------------------------------

def test_the_fee_is_recorded_against_the_rung_before_the_send_is_attempted(monkeypatch):
    """A crash between the vendor's confirmation and our record leaves a fee attributable
    to nothing. The row is therefore written on the way in, not on the way out."""
    async def body():
        seen_at_send = {}

        async def send(phone, *, code, ttl, token, request_id=None, **kw):
            rows = await queries.verification_rungs(vid)
            seen_at_send["vendor_ref"] = rows[-1]["vendor_ref"]
            seen_at_send["cost"] = rows[-1]["cost"]
            return _ok_send(request_id)

        _patch(monkeypatch, ability=_able())
        monkeypatch.setattr(tg_gateway, "send_verification_message", send)

        vid = await _open()
        rung_id = await queries.record_verification_rung(
            vid, route=TG_GATEWAY, outcome=ladder.ATTEMPTING)
        attempt = await tg_gateway_carrier_for(vid)(
            PHONE, seconds_left=5.0, rung_id=rung_id)

        assert seen_at_send == {"vendor_ref": "req-1", "cost": 0.01}
        assert attempt.outcome == ladder.CARRIED
        assert attempt.vendor_ref == "req-1"
        assert attempt.cost == 0.01

    _run(body)


def test_a_confirmed_check_is_followed_by_exactly_one_send_carrying_that_request_id(
        monkeypatch):
    """Tasks 4.34 and 4.35. A second call with the same `request_id` is answered by the
    vendor with an error rather than a second message, and the first one is the free
    half of a fee already paid — so it is made once and never abandoned."""
    async def body():
        sends = []
        _patch(monkeypatch, ability=_able(), sent=_ok_send(), sends=sends)
        vid = await _open()
        rung_id = await queries.record_verification_rung(
            vid, route=TG_GATEWAY, outcome=ladder.ATTEMPTING)
        await tg_gateway_carrier_for(vid)(PHONE, seconds_left=5.0, rung_id=rung_id)

        assert len(sends) == 1
        assert sends[0]["request_id"] == "req-1"

    _run(body)


def test_the_ttl_handed_to_the_vendor_is_the_verifications_remaining_lifetime(monkeypatch):
    """Task 4.40. A constant of the adapter's would hand the vendor a message that
    outlives the verification it belongs to — while the automatic refund on non-delivery
    is tied to that same `ttl`."""
    async def body():
        sends = []
        _patch(monkeypatch, ability=_able(), sent=_ok_send(), sends=sends)
        vid = await _open(ttl=120)
        rung_id = await queries.record_verification_rung(
            vid, route=TG_GATEWAY, outcome=ladder.ATTEMPTING)
        await tg_gateway_carrier_for(vid)(PHONE, seconds_left=5.0, rung_id=rung_id)

        assert 100 <= sends[0]["ttl"] <= 120, sends

    _run(body)


def test_a_verification_with_too_little_life_left_is_not_bought_at_all(monkeypatch):
    """The vendor's floor is 30 seconds, and inflating the `ttl` to reach it would hand
    the vendor a message outliving the verification. Too little life left is a reason not
    to buy the rung — and not a decline, which would be counted against the rung."""
    async def body():
        checks = []
        _patch(monkeypatch, ability=_able(), sent=_ok_send(), checks=checks)
        vid = await _open(ttl=20)
        rung_id = await queries.record_verification_rung(
            vid, route=TG_GATEWAY, outcome=ladder.ATTEMPTING)
        attempt = await tg_gateway_carrier_for(vid)(
            PHONE, seconds_left=5.0, rung_id=rung_id)

        assert checks == [], "the rung was bought for a verification it cannot carry"
        assert attempt.outcome == ladder.INCAPABLE
        assert attempt.outcome != ladder.DECLINED

    _run(body)


# --- the two refusals that are not the subscriber's -----------------------------------

def test_a_refusal_of_us_alerts_and_names_the_vendor(monkeypatch):
    async def body():
        alerts = []
        import app.alerting as alerting
        monkeypatch.setattr(alerting, "notify",
                            lambda kind, text, **kw: alerts.append((kind, text)))
        _patch(monkeypatch, ability=tg_gateway.Ability(
            kind=tg_gateway.REFUSED, error="ACCESS_TOKEN_INVALID"))
        vid = await _open()
        rung_id = await queries.record_verification_rung(
            vid, route=TG_GATEWAY, outcome=ladder.ATTEMPTING)
        attempt = await tg_gateway_carrier_for(vid)(
            PHONE, seconds_left=5.0, rung_id=rung_id)

        assert attempt.outcome == ladder.REFUSED
        assert alerts, "a vendor refusing our credentials must be loud"
        assert "Telegram" in alerts[0][1]

    _run(body)


def test_an_unplaceable_refusal_advances_and_alerts(monkeypatch):
    """Read as a decline, a rotated token would advance every verification to the dearer
    rung and tell nobody — the bill would be the only symptom."""
    async def body():
        alerts = []
        import app.alerting as alerting
        monkeypatch.setattr(alerting, "notify",
                            lambda kind, text, **kw: alerts.append((kind, text)))
        _patch(monkeypatch, ability=tg_gateway.Ability(
            kind=tg_gateway.UNCLASSIFIED, error="SOMETHING_NEW"))
        vid = await _open()
        rung_id = await queries.record_verification_rung(
            vid, route=TG_GATEWAY, outcome=ladder.ATTEMPTING)
        attempt = await tg_gateway_carrier_for(vid)(
            PHONE, seconds_left=5.0, rung_id=rung_id)

        assert attempt.outcome == ladder.UNCLASSIFIED
        assert attempt.outcome in ladder._ADVANCING
        assert alerts and "SOMETHING_NEW" in alerts[0][1]

    _run(body)


def test_an_unanswered_check_is_possibly_charged_and_says_so(monkeypatch):
    async def body():
        _patch(monkeypatch, ability=tg_gateway.Ability(
            kind=tg_gateway.UNANSWERED, error="timed out"))
        vid = await _open()
        rung_id = await queries.record_verification_rung(
            vid, route=TG_GATEWAY, outcome=ladder.ATTEMPTING)
        attempt = await tg_gateway_carrier_for(vid)(
            PHONE, seconds_left=5.0, rung_id=rung_id)

        assert attempt.outcome == ladder.UNANSWERED
        rows = await queries.verification_rungs(vid)
        assert rows[-1]["vendor_ref"] is None

    _run(body)


# --- the failure that must not become a second purchase -------------------------------

def test_a_send_that_fails_after_the_fee_stops_the_ladder_rather_than_advancing(
        monkeypatch):
    """The ladder advances only on a rung *declining to carry*, never on one that carried
    and then failed. Advancing here would buy the same code at the second vendor while
    the first one's fee is unrefundable until its `ttl` runs out."""
    async def body():
        asked = []
        _patch(monkeypatch, ability=_able(),
               sent=tg_gateway.Sent(ok=False, error="FLOOD_WAIT"))
        vid = await _open()

        async def flash(phone, *, seconds_left, rung_id):
            asked.append(phone)
            return ladder.Attempt(outcome=ladder.CARRIED)

        walk = await ladder.walk(
            vid, app_id="app1", operator="МегаФон", phone=PHONE, rungs=[TG_GATEWAY, FLASH_CALL], gates=(),
            carriers={TG_GATEWAY: tg_gateway_carrier_for(vid), FLASH_CALL: flash},
            bound=5.0)

        assert asked == [], "the dearer rung was bought after the first had been charged"
        assert walk.carried_by is None
        row = await queries.get_verification(vid, "app1")
        assert row["status"] == "failed"
        rows = await queries.verification_rungs(vid)
        assert rows[-1]["cost"] == 0.01, "the fee already incurred must stay recorded"

    _run(body)


# --- the whole ladder, end to end -----------------------------------------------------

def test_the_declined_subscriber_reaches_the_call_rung(monkeypatch):
    """Task 4.33 end to end: the cheap rung declines for free, the ladder advances, and
    the decline is recorded against the rung that made it."""
    async def body():
        _patch(monkeypatch, ability=tg_gateway.Ability(
            kind=tg_gateway.DECLINED, error="PHONE_NUMBER_NOT_AVAILABLE"))
        vid = await _open()

        async def flash(phone, *, seconds_left, rung_id):
            return ladder.Attempt(outcome=ladder.CARRIED, vendor_ref="ucaller-1",
                                  cost=0.8)

        walk = await ladder.walk(
            vid, app_id="app1", operator="МегаФон", phone=PHONE, rungs=[TG_GATEWAY, FLASH_CALL], gates=(),
            carriers={TG_GATEWAY: tg_gateway_carrier_for(vid), FLASH_CALL: flash},
            bound=5.0)

        assert walk.carried_by == FLASH_CALL
        rows = await queries.verification_rungs(vid)
        assert [(r["route"], r["outcome"], r["cost"]) for r in rows] == [
            (TG_GATEWAY, ladder.DECLINED, None), (FLASH_CALL, ladder.CARRIED, 0.8)]
        assert (await queries.get_verification(vid, "app1"))["route"] == FLASH_CALL

    _run(body)


def tg_gateway_carrier_for(verification_id):
    from app.verification.tg_carrier import carrier
    return carrier(verification_id, app_id="app1", token=TOKEN,
                   callback_url="https://gate.example.org/verifications/tg-callback")
