"""The Gateway's callback door: public by necessity, and therefore shut by default.

The vendor has to reach this endpoint, so it carries no application token. What stands in
place of one is the signature, and every test here is about the door refusing before it
changes anything. An unauthenticated callback that moves a verification's state is a way
to confirm a verification without the code ever reaching the person — the same guarantee
the code's secrecy protects, given away at a different door.

Nothing here has ever run against the live vendor: no callback has arrived, because no
request has yet been made that had one to report. The signature computation is the
vendor's reference, read 20.09.2026 and quoted in the adapter.
"""

import asyncio
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app.db import queries
from app.db.connection import close_db, init_db
from app.db.migrate import run_migrations
from app.settings_store import store
from app.verification import tg_callback
from app.verification.routes import TG_GATEWAY

PHONE = "+79261234888"
TOKEN = "AAExample:token"
REQUEST_ID = "142431475830971"


def sign(body: bytes, timestamp: str, token: str = TOKEN) -> str:
    secret = hashlib.sha256(token.encode()).digest()
    return hmac.new(secret, timestamp.encode() + b"\n" + body, hashlib.sha256).hexdigest()


def status_body(status: str, **extra) -> bytes:
    payload = {"request_id": REQUEST_ID, "phone_number": "79261234888",
               "request_cost": 0.01, "delivery_status": {"status": status,
                                                         "updated_at": 1789713190}}
    payload.update(extra)
    return json.dumps(payload).encode()


class FakeModem:
    caller_id_held = True
    link_in_service = True
    can_transmit = True
    can_receive = True

    def health_snapshot(self):
        return {"modem_detected": True}


async def _open_verification_on_the_telegram_rung() -> int:
    """A verification already carried by this rung, with its vendor reference recorded."""
    verification_id = await queries.create_verification(
        "app1", PHONE, code="1173", ttl_seconds=300)
    await queries.select_route(verification_id, "app1", route=TG_GATEWAY)
    await queries.record_verification_rung(
        verification_id, route=TG_GATEWAY, vendor_ref=REQUEST_ID, cost=0.01)
    return verification_id


@pytest.fixture
def alerts(monkeypatch):
    sent = []
    import app.alerting as alerting
    monkeypatch.setattr(
        alerting, "notify",
        lambda event, text, dedup_extra=None, phone=None: sent.append(
            (event, text, dedup_extra)))
    return sent


def _run(body):
    async def go():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("app1", "token-app1")
        await store.load()
        await store.set_many({"tg_gateway_token": TOKEN})
        tg_callback.rejections.clear()
        return await body()

    try:
        return asyncio.run(go())
    finally:
        asyncio.run(close_db())


async def _deliver(body: bytes, *, timestamp="1789713190", signature=None,
                   now=1789713200.0):
    return await tg_callback.handle_callback(
        body,
        timestamp=timestamp,
        signature=sign(body, timestamp) if signature is None else signature,
        token=store.tg_gateway_token,
        tolerance=store.tg_gateway_callback_tolerance_seconds,
        now=now,
    )


# --- what a verified callback is allowed to move ----------------------------------------

def test_a_verified_callback_records_the_delivery_against_the_rung_that_carried_it():
    async def body():
        verification_id = await _open_verification_on_the_telegram_rung()
        outcome = await _deliver(status_body("delivered"))
        rungs = await queries.verification_rungs(verification_id)
        row = await queries.get_verification(verification_id, "app1")
        return outcome, rungs, row

    outcome, rungs, row = _run(body)
    assert outcome.accepted is True
    assert rungs[0]["outcome"] == "delivered"
    assert row["status"] == "pending"          # delivered is not confirmed


def test_a_read_receipt_still_does_not_confirm_the_verification():
    """The strongest thing this rung can report, and it is still not the code being
    used. Only a correct code at the check door confirms."""
    async def body():
        verification_id = await _open_verification_on_the_telegram_rung()
        await _deliver(status_body("read"))
        rungs = await queries.verification_rungs(verification_id)
        return (await queries.get_verification(verification_id, "app1"))["status"], rungs

    status, rungs = _run(body)
    assert status == "pending"
    assert rungs[0]["outcome"] == "read"


def test_an_expired_message_fails_the_verification_with_that_reason():
    async def body():
        verification_id = await _open_verification_on_the_telegram_rung()
        await _deliver(status_body("expired", is_refunded=True))
        row = await queries.get_verification(verification_id, "app1")
        rungs = await queries.verification_rungs(verification_id)
        return row, rungs

    row, rungs = _run(body)
    assert row["status"] == "failed"
    assert "expired" in row["reason"]
    assert rungs[0]["refunded"] == 1


def test_a_refund_the_vendor_did_not_mention_is_not_recorded_as_one():
    """`is_refunded` was absent from all seven captures. Absent is not `false`, and the
    norm forbids assuming either — so the affirmative is the only thing that writes the
    flag, and what the vendor actually said is kept in the rung's reason."""
    async def body():
        verification_id = await _open_verification_on_the_telegram_rung()
        await _deliver(status_body("expired"))
        return await queries.verification_rungs(verification_id)

    rungs = _run(body)
    assert rungs[0]["refunded"] == 0
    assert "said nothing about a refund" in rungs[0]["reason"]


def test_a_vendor_that_says_the_fee_was_not_refunded_is_recorded_as_saying_so():
    """The pair to the test above: three states, two of which the column alone cannot
    tell apart, so the distinguishing one has to be written down."""
    async def body():
        verification_id = await _open_verification_on_the_telegram_rung()
        await _deliver(status_body("expired", is_refunded=False))
        return await queries.verification_rungs(verification_id)

    rungs = _run(body)
    assert rungs[0]["refunded"] == 0
    assert "not refunded" in rungs[0]["reason"]


# --- what an unverified callback may not move --------------------------------------------

def test_a_callback_whose_signature_does_not_verify_changes_nothing_and_is_counted():
    async def body():
        verification_id = await _open_verification_on_the_telegram_rung()
        outcome = await _deliver(status_body("expired"), signature="deadbeef")
        row = await queries.get_verification(verification_id, "app1")
        rungs = await queries.verification_rungs(verification_id)
        return outcome, row, rungs, dict(tg_callback.rejections)

    outcome, row, rungs, rejections = _run(body)
    assert outcome.accepted is False
    assert row["status"] == "pending"
    assert rungs[0]["outcome"] is None
    assert rejections == {"signature": 1}


def test_a_correctly_signed_callback_replayed_later_changes_nothing_and_is_counted():
    """The rung is asserted as well as the row, and not for symmetry's sake.

    "Changes no state" is the whole of the requirement, and the rung's recorded delivery
    outcome is state. Asserting only the verification's own status leaves a stale
    callback free to write the rung — which is a plausible edit in its own right
    ("record what the vendor said, just do not act on it"), and one the requirement
    forbids. Measured: with only the row asserted, that edit left the whole suite green.
    """
    async def body():
        verification_id = await _open_verification_on_the_telegram_rung()
        outcome = await _deliver(status_body("expired"), now=1789720000.0)
        row = await queries.get_verification(verification_id, "app1")
        rungs = await queries.verification_rungs(verification_id)
        return outcome, row, rungs, dict(tg_callback.rejections)

    outcome, row, rungs, rejections = _run(body)
    assert outcome.accepted is False
    assert row["status"] == "pending"
    assert rungs[0]["outcome"] is None, "a callback refused on its timestamp wrote the rung"
    # `stale` rather than `signature` since 22.09.2026 (task 4.66): a callback outside the
    # window is refused as stale whatever its signature says, and the two are counted
    # apart because a clock and a credential are different events.
    assert rejections == {"stale": 1}


def test_a_correctly_signed_callback_stamped_in_the_future_is_refused_on_the_same_terms():
    """The other side of the same window, and it is not symmetry for its own sake.

    A window checked in one direction only is a window a captured callback stays valid
    in for ever, because the timestamp is signed and an attacker who replays one cannot
    move it back inside a bound that has no far edge. Measured: with only the stale
    direction guarded, narrowing the check to `now - sent_at > tolerance` left the whole
    suite green.
    """
    async def body():
        verification_id = await _open_verification_on_the_telegram_rung()
        outcome = await _deliver(status_body("expired"), timestamp="1789813190")
        row = await queries.get_verification(verification_id, "app1")
        rungs = await queries.verification_rungs(verification_id)
        return outcome, row, rungs, dict(tg_callback.rejections)

    outcome, row, rungs, rejections = _run(body)
    assert outcome.accepted is False
    assert row["status"] == "pending"
    assert rungs[0]["outcome"] is None
    assert rejections == {"stale": 1}


def test_the_door_is_shut_entirely_while_the_gateway_holds_no_token():
    """Not configured is a refusal, not a pass. A blank token must not be a blank
    signature's counterpart."""
    async def body():
        verification_id = await _open_verification_on_the_telegram_rung()
        await store.set_many({"tg_gateway_token": ""})
        outcome = await tg_callback.handle_callback(
            status_body("expired"), timestamp="1789713190", signature="",
            token=store.tg_gateway_token,
            tolerance=store.tg_gateway_callback_tolerance_seconds, now=1789713200.0)
        row = await queries.get_verification(verification_id, "app1")
        return outcome, row

    outcome, row = _run(body)
    assert outcome.accepted is False
    assert row["status"] == "pending"


def test_a_verified_callback_for_a_request_nobody_claims_moves_nothing():
    """Correctly signed and genuinely the vendor's, but naming a `request_id` no rung
    holds. Accepted — arguing with the vendor is not this door's job — and attributed
    to nothing, which is a different thing from rejected and is counted separately."""
    async def body():
        await _open_verification_on_the_telegram_rung()
        payload = json.loads(status_body("expired"))
        payload["request_id"] = "999999999999999"
        outcome = await _deliver(json.dumps(payload).encode())
        return outcome, dict(tg_callback.rejections)

    outcome, rejections = _run(body)
    assert outcome.accepted is True
    assert outcome.verification_id is None
    assert rejections == {"unattributed": 1}


def test_a_verified_callback_that_is_not_a_request_status_is_refused():
    async def body():
        await _open_verification_on_the_telegram_rung()
        outcome = await _deliver(b'{"hello": "world"}')
        return outcome, dict(tg_callback.rejections)

    outcome, rejections = _run(body)
    assert outcome.accepted is False
    assert rejections == {"unreadable": 1}


def test_a_callback_cannot_move_a_verification_that_has_already_ended():
    """The terminal state decides, and a late `expired` must not overwrite a
    confirmation that already happened."""
    async def body():
        verification_id = await _open_verification_on_the_telegram_rung()
        await queries.check_verification(verification_id, "app1",
                                         code="1173", max_attempts=5)
        await _deliver(status_body("expired"))
        return await queries.get_verification(verification_id, "app1")

    row = _run(body)
    assert row["status"] == "confirmed"


# --- the door as it is actually mounted ---------------------------------------------------

@pytest.fixture
def client():
    from fastapi import FastAPI

    from app.api.router import router

    async def setup():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("app1", "token-app1")
        await store.load()
        await store.set_many({"tg_gateway_token": TOKEN})
        tg_callback.rejections.clear()
        return await _open_verification_on_the_telegram_rung()

    verification_id = asyncio.run(setup())
    application = FastAPI()
    application.include_router(router)
    application.state.modem = FakeModem()
    try:
        with TestClient(application) as test_client:
            test_client.verification_id = verification_id
            yield test_client
    finally:
        asyncio.run(close_db())


def test_the_mounted_door_needs_no_application_token(client, monkeypatch):
    """The vendor has none. If this route ever acquires one, every callback is lost
    silently and the only symptom is verifications that never report a delivery."""
    monkeypatch.setattr(tg_callback.time, "time", lambda: 1789713200.0)
    body = status_body("delivered")
    response = client.post("/verifications/tg-callback", content=body,
                           headers={"X-Request-Timestamp": "1789713190",
                                    "X-Request-Signature": sign(body, "1789713190")})
    assert response.status_code == 200


def test_the_mounted_door_refuses_an_unsigned_callback(client, monkeypatch):
    monkeypatch.setattr(tg_callback.time, "time", lambda: 1789713200.0)
    response = client.post("/verifications/tg-callback", content=status_body("expired"),
                           headers={"X-Request-Timestamp": "1789713190"})
    assert response.status_code == 403

    async def still_pending():
        return await queries.get_verification(client.verification_id, "app1")

    assert asyncio.run(still_pending())["status"] == "pending"


# --- 4.41 — the rung reports delivery; only the code confirms -----------------------------

def test_delivered_and_read_leave_the_verification_open_for_the_code_to_confirm():
    """4.41 — the positive control the two assertions above are worth nothing without.

    `delivered` and `read` are the strongest things this rung can report, and neither is
    evidence the code was used: the message reaching the phone and the message being
    opened both happen without anybody typing anything. But "still pending" on its own is
    satisfied by an implementation that confirms nothing at all, and "open" means more
    than "not confirmed" — it means the code can still do its work. So the same
    verification is carried all the way through: delivered, read, and then confirmed by
    its own code at the check door.
    """
    async def body():
        verification_id = await _open_verification_on_the_telegram_rung()
        await _deliver(status_body("delivered"))
        after_delivered = await queries.get_verification(verification_id, "app1")
        await _deliver(status_body("read"))
        after_read = await queries.get_verification(verification_id, "app1")
        answer = await queries.check_verification(
            verification_id, "app1", code="1173", max_attempts=5)
        return (after_delivered["status"], after_read["status"], answer,
                (await queries.get_verification(verification_id, "app1"))["status"])

    after_delivered, after_read, answer, final = _run(body)
    assert (after_delivered, after_read) == ("pending", "pending"), \
        "a delivery report ended the verification; only the code may do that"
    assert answer == "confirmed", \
        "the reports closed the door the code comes through — the verification was not left open"
    assert final == "confirmed"


def test_a_delivered_message_does_not_make_a_wrong_code_right():
    """The negative half of the control above. `delivered` must not weaken what the check
    door demands — otherwise "still open" has been bought by a door that accepts
    anything."""
    async def body():
        verification_id = await _open_verification_on_the_telegram_rung()
        await _deliver(status_body("delivered"))
        answer = await queries.check_verification(
            verification_id, "app1", code="9999", max_attempts=5)
        return answer, (await queries.get_verification(verification_id, "app1"))["status"]

    answer, status = _run(body)
    assert answer == "wrong_code"
    assert status == "pending"


# --- a rotation does not look like an attack, task 4.66 --------------------------------
#
# Owner's decision of 22.09.2026, on the circle's finding: the loss is **made visible**
# rather than softened — the previous credential is not honoured for a grace period, and
# the signature check is not weakened by a second. What changes is that the two rejections
# stop being one number, and that a run of them says out loud what it may cost.
#
# A rotation takes effect with no restart, so messages already bought go on reporting,
# signed with the key just replaced. The callback is the **only** path a refund ever takes,
# so every one of those refunds is lost and the recorded spend stands above the money
# actually spent — the one direction this ledger is elsewhere written to forbid.

def test_a_stale_callback_and_a_bad_signature_are_two_different_numbers():
    """🔴 They were one (`signature`) until 22.09.2026, so a run of clock skew and a run
    of forged callbacks were indistinguishable — and so was a credential rotation, which
    is neither. The module's own docstring already said the kinds are counted apart
    because they mean different things."""
    async def body():
        await _open_verification_on_the_telegram_rung()
        stale = await _deliver(status_body("expired"), now=1789720000.0)
        forged = await _deliver(status_body("expired"), signature="deadbeef")
        return stale, forged, dict(tg_callback.rejections)

    stale, forged, rejections = _run(body)
    assert stale.accepted is False and forged.accepted is False
    assert rejections == {"stale": 1, "signature": 1}, rejections
    assert stale.reason == "stale" and forged.reason == "signature"


def test_a_refused_signature_says_what_a_rotation_would_have_cost(alerts):
    """The loss, made visible as a number rather than as a warning.

    The rungs awaiting a report are exactly the messages whose refunds a rotation drops,
    so the alert carries that count: an operator who has just rotated the token reads it
    as the size of what they gave up, and one who has not reads it as an attack. Both
    readings are named, because from here the two are genuinely indistinguishable.
    """
    async def body():
        await _open_verification_on_the_telegram_rung()
        await _deliver(status_body("expired"), signature="deadbeef")

    _run(body)
    assert alerts, "a run of refused signatures reached nobody"
    text = alerts[0][1]
    assert "1" in text, f"the alert does not say how many reports are in flight: {text}"
    assert "rotat" in text.lower(), text


def test_clock_skew_alone_does_not_cry_rotation(alerts):
    """The control, and it is the point of having split the counter at all: a stale
    callback is a clock, not a credential, and waking somebody about a lost refund for it
    would be the false alarm that gets the channel muted."""
    async def body():
        await _open_verification_on_the_telegram_rung()
        await _deliver(status_body("expired"), now=1789720000.0)

    _run(body)
    assert alerts == [], f"clock skew raised a credential alert: {alerts}"


def test_a_callback_that_verifies_raises_nothing(alerts):
    """The other control: the alert is about refusals, not about callbacks."""
    async def body():
        await _open_verification_on_the_telegram_rung()
        await _deliver(status_body("delivered"))

    _run(body)
    assert alerts == []


def test_a_stale_callback_with_a_forged_signature_is_still_only_stale(alerts):
    """🔴 Found by `bite-rotation-is-not-an-attack.sh`: the order of the two checks was
    unguarded, and it is not a matter of taste.

    Checked signature-first, anything outside the window that is also badly signed counts
    as a *signature* refusal — which means anyone who can reach this public door can raise
    the credential alarm at will by posting stale garbage. The window is what already made
    that traffic harmless; counting it under the expensive key hands an attacker the alert
    as a tool.
    """
    async def body():
        await _open_verification_on_the_telegram_rung()
        outcome = await _deliver(status_body("expired"), signature="deadbeef",
                                 now=1789720000.0)
        return outcome, dict(tg_callback.rejections)

    outcome, rejections = _run(body)
    assert outcome.reason == "stale", (
        "a callback the window already refused was counted as a credential problem")
    assert rejections == {"stale": 1}
    assert alerts == [], "stale traffic raised the credential alarm"


def test_the_count_in_flight_is_what_a_rotation_would_actually_cost(alerts):
    """The control on the number, without which "it prints a number" is the whole claim.

    Three rungs on this route and only one of them is at risk: one has already reported —
    its refund, if any, has been recorded — and one holds no vendor reference at all,
    which means nothing was ever bought for it and there is nothing to report.
    """
    async def body():
        in_flight = await _open_verification_on_the_telegram_rung()
        assert in_flight

        reported = await queries.create_verification(
            "app1", PHONE, code="2222", ttl_seconds=300)
        already = await queries.record_verification_rung(
            reported, route=TG_GATEWAY, vendor_ref="req-old", cost=0.01)
        await queries.set_rung_outcome(already, outcome="delivered")

        never_bought = await queries.create_verification(
            "app1", PHONE, code="3333", ttl_seconds=300)
        await queries.record_verification_rung(never_bought, route=TG_GATEWAY)

        await _deliver(status_body("expired"), signature="deadbeef")

    _run(body)
    assert alerts, "a refused signature reached nobody"
    text = alerts[0][1]
    assert "1 message" in text, (
        f"the alert overstates or understates what is actually in flight: {text}")
