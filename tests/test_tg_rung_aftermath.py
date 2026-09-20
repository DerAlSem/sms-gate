"""What happens to a Telegram message after the verification it carried has ended.

Two obligations, and they pull in opposite directions from the same fact — that the
vendor's message keeps existing after we stop caring about it.

**A verification that ended revokes its outstanding message.** Not because revocation is
a guarantee — it is measurably not one: on 18.09.2026 `revokeVerificationMessage`
answered `true` for a message the subscriber had already read and for one revoked within
a second of delivery, and in both trials the message stayed visibly in the chat. The
guarantee that a finished verification stops being usable is carried by its terminal
state. Revoking is the courtesy on top: a code the person can still see in a chat, for a
login that already happened, is a code somebody else can see too.

**The attempt counter is ours.** `checkVerificationStatus` is deliberately not used —
handing the vendor the code to compare would move the count of wrong attempts to a place
this gateway cannot read, and the bound on four digits is the only thing that makes four
digits survivable.
"""

import asyncio

import pytest

from app.db import queries
from app.db.connection import close_db, init_db
from app.db.migrate import run_migrations
from app.settings_store import store
from app.verification import dispatch, ladder, tg_gateway
from app.verification.routes import CALL_IN, TG_GATEWAY

PHONE = "+79851600019"


def _run(body):
    async def go():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("app1", "token-app1")
        await store.load()
        await store.set_many({"tg_gateway_token": "a-token"})
        return await body()

    try:
        return asyncio.run(go())
    finally:
        asyncio.run(close_db())


def _watch_vendor(monkeypatch):
    """Every vendor method, replaced by a recorder. Nothing here may reach the wire."""
    calls = []

    async def revoke(request_id, *, token, timeout=5.0, client=None):
        calls.append(("revoke", request_id))
        return True

    async def check(phone, *, token, timeout=5.0, client=None):
        calls.append(("check", phone))
        raise AssertionError("no ability check belongs in this path")

    async def status(*a, **kw):
        calls.append(("status", a))
        raise AssertionError("the attempt counter is this gateway's")

    monkeypatch.setattr(tg_gateway, "request_revocation", revoke)
    monkeypatch.setattr(tg_gateway, "check_send_ability", check)
    monkeypatch.setattr(tg_gateway, "send_verification_message", status)
    return calls


async def _carried(route=TG_GATEWAY, vendor_ref="req-1", code="1234"):
    vid = await queries.create_verification("app1", PHONE, code=code, ttl_seconds=300)
    await queries.select_route(vid, "app1", route=route)
    await queries.record_verification_rung(vid, route=route, vendor_ref=vendor_ref,
                                           outcome=ladder.CARRIED, cost=0.01)
    return vid


# --- the message is withdrawn when the verification ends ------------------------------

@pytest.mark.parametrize("ending", ["confirmed", "expired", "no_attempts_left"])
def test_a_finished_telegram_verification_revokes_its_outstanding_message(
        monkeypatch, ending):
    """Task 4.42, over all three ways a verification ends while a message is outstanding.
    """
    async def body():
        calls = _watch_vendor(monkeypatch)
        vid = await _carried()

        if ending == "confirmed":
            assert await queries.check_verification(
                vid, "app1", code="1234", max_attempts=5) == "confirmed"
        elif ending == "expired":
            await queries.shorten_verification_window(vid, ttl_seconds=-1)
        else:
            for _ in range(5):
                await queries.check_verification(vid, "app1", code="0000",
                                                 max_attempts=5)

        await dispatch.announce_verification_outcomes()

        assert ("revoke", "req-1") in calls, calls

    _run(body)


def test_a_verification_carried_by_another_route_revokes_nothing(monkeypatch):
    async def body():
        calls = _watch_vendor(monkeypatch)
        vid = await _carried(route=CALL_IN, vendor_ref="ucaller-1")
        await queries.fail_verification(vid, reason="nobody called")
        await dispatch.announce_verification_outcomes()

        assert calls == [], calls

    _run(body)


def test_a_telegram_rung_that_never_reached_the_vendor_revokes_nothing(monkeypatch):
    """A rung whose ability check declined holds no `request_id`, and asking the vendor
    to withdraw nothing is a round trip that can only produce a confusing error."""
    async def body():
        calls = _watch_vendor(monkeypatch)
        vid = await queries.create_verification("app1", PHONE, code="1234",
                                                ttl_seconds=300)
        await queries.record_verification_rung(vid, route=TG_GATEWAY,
                                               outcome=ladder.DECLINED)
        await queries.fail_verification(vid, reason="declined everywhere")
        await dispatch.announce_verification_outcomes()

        assert calls == [], calls

    _run(body)


def test_a_vendor_that_refuses_the_revocation_does_not_hold_up_the_announcement(
        monkeypatch):
    """A vendor's mood must not be able to leave a verification unannounced: the
    revocation runs on the way to a state already decided."""
    async def body():
        async def refuse(request_id, *, token, timeout=5.0, client=None):
            raise RuntimeError("the vendor is having a day")

        monkeypatch.setattr(tg_gateway, "request_revocation", refuse)
        pushed = []
        monkeypatch.setattr(dispatch, "push_verification",
                            lambda *a, **kw: _true(pushed, a))

        vid = await _carried()
        await queries.fail_verification(vid, reason="ended")
        announced = await dispatch.announce_verification_outcomes()

        assert announced == 1
        assert pushed and pushed[0][0] == vid

    _run(body)


def _true(sink, args):
    sink.append(args)

    async def go():
        return True

    return go()


# --- the count of wrong codes is ours -------------------------------------------------

def test_a_wrong_code_consumes_one_of_our_attempts_and_asks_the_vendor_nothing(
        monkeypatch):
    """Task 4.44. `checkVerificationStatus` would move the count somewhere this gateway
    cannot read, and an unbounded count is what makes four digits unsurvivable."""
    async def body():
        calls = _watch_vendor(monkeypatch)
        vid = await _carried()

        assert await queries.check_verification(
            vid, "app1", code="9999", max_attempts=5) == "wrong_code"
        row = await queries.get_verification(vid, "app1")

        assert row["attempts"] == 1
        assert row["status"] == "pending"
        assert calls == [], "the vendor was asked to decide a wrong code"

    _run(body)


def test_the_vendors_status_endpoint_is_not_among_the_methods_this_gateway_calls():
    """The one vendor method deliberately not used: it would move the count of wrong
    attempts to the vendor, where this gateway cannot read it and cannot bound it. The
    method table is what a convenience would have to be added to first."""
    assert "checkVerificationStatus" not in tg_gateway.VENDOR_METHODS


# --- an expired Telegram message does not buy a call ----------------------------------

def test_a_message_the_gateway_took_and_did_not_deliver_places_no_call(monkeypatch):
    """Task 4.39. The owner's default of 18.09.2026, pinned until they decide otherwise:
    the safe default is the one that cannot spend money on a decision nobody has taken."""
    async def body():
        import json
        import time as _time

        from app.verification import tg_callback

        calls = _watch_vendor(monkeypatch)
        vid = await _carried()

        body_bytes = json.dumps({
            "request_id": "req-1", "phone_number": PHONE.lstrip("+"),
            "request_cost": 0.01, "is_refunded": True,
            "delivery_status": {"status": "expired", "updated_at": 1},
        }).encode()
        ts = str(int(_time.time()))
        sig = _sign(body_bytes, ts, "a-token")

        outcome = await tg_callback.handle_callback(
            body_bytes, timestamp=ts, signature=sig, token="a-token",
            tolerance=300, now=_time.time())

        assert outcome.accepted
        row = await queries.get_verification(vid, "app1")
        assert row["status"] == "failed"
        assert "expired" in row["reason"]
        rungs = await queries.verification_rungs(vid)
        assert [r["route"] for r in rungs] == [TG_GATEWAY], \
            "a call was placed for a message the Gateway had already been paid for"
        assert rungs[0]["refunded"] == 1
        assert calls == []

    _run(body)


def _sign(body: bytes, timestamp: str, token: str) -> str:
    import hashlib
    import hmac

    secret = hashlib.sha256(token.encode()).digest()
    return hmac.new(secret, timestamp.encode() + b"\n" + body, hashlib.sha256).hexdigest()
