"""The Telegram Gateway adapter, against the samples captured live on 18.09.2026.

Every test that can stand on a capture stands on one: the files in
`openspec/changes/route-sends-by-operator/captures/` are what the vendor actually
answered, and a parser agreeing with the documentation while disagreeing with them is
the failure this suite exists to catch. Where a capture does not exist — the ability
check, which is billable and was never called, and the signed callback, which needs a
public address and a request worth reporting — the test stands on the vendor's
reference and says so in its name.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from pathlib import Path

import httpx
import pytest

from app.verification import tg_gateway as tg

CAPTURES = (Path(__file__).resolve().parent.parent
            / "openspec" / "changes" / "route-sends-by-operator" / "captures")


def capture(name: str) -> dict:
    return json.loads((CAPTURES / f"{name}.json").read_text())


def transport(handler):
    """An httpx client whose every request is answered by `handler(request)`."""
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def answering(payload: dict, *, status_code: int = 200, seen: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status_code, json=payload)
    return handler


# --- the captured wire, parsed -------------------------------------------------------

def test_the_captured_send_response_parses():
    status = tg.parse_request_status(capture("sendVerificationMessage")["result"])
    assert status.request_id == "142431475830971"
    assert status.phone_number == "79267889888"
    assert status.request_cost == 0
    assert status.remaining_balance == 0
    assert status.delivery_status == "sent"
    assert status.delivery_updated_at == 1789713189
    assert status.payload == "sms-gate probe 1.5"


def test_a_status_response_without_remaining_balance_still_parses():
    """`remaining_balance` is in the answer to a send and absent from the answer to a
    status. A parser that requires it falls over on a perfectly ordinary response."""
    status = tg.parse_request_status(capture("checkVerificationStatus")["result"])
    assert status.remaining_balance is None
    assert status.delivery_status == "delivered"


def test_verification_status_and_is_refunded_are_absent_and_that_is_not_an_error():
    """Neither field appeared in any of the seven captures. Absent is the ordinary
    case; `None` distinguishes it from a vendor that said `false`."""
    for name in ("sendVerificationMessage", "checkVerificationStatus",
                 "probe-1.5b-send", "probe-1.5b-status"):
        status = tg.parse_request_status(capture(name)["result"])
        assert status.is_refunded is None
        assert status.verification_status is None


def test_a_response_with_no_delivery_status_at_all_parses():
    """The field is optional in the reference and the ability check has no delivery to
    report. Absent must not be read as a delivery status of the empty string."""
    status = tg.parse_request_status({"request_id": "1", "phone_number": "79267889888",
                                      "request_cost": 0.01})
    assert status.delivery_status is None
    assert status.delivery_updated_at is None


# --- the number the vendor echoes back is not the number we sent ---------------------

def test_the_echoed_number_joins_with_the_number_we_sent():
    """We send `+79267889888`; the vendor answers `79267889888`. Every capture does it.
    Without this the response never finds its own row."""
    sent = "+79267889888"
    echoed = capture("sendVerificationMessage")["result"]["phone_number"]
    assert echoed != sent                      # the trap, stated
    assert tg.same_number(sent, echoed)


def test_the_join_still_refuses_a_different_number():
    """The positive control's pair: a comparison that accepts everything would pass the
    test above just as well."""
    assert not tg.same_number("+79267889888", "79851600019")


def test_the_number_leaves_here_in_e164_with_its_plus():
    """The reference asks for E.164. The echo drops the `+`; the request must not."""
    assert tg.wire_number("+7 926 788-98-88") == "+79267889888"
    assert tg.wire_number("79267889888") == "+79267889888"


# --- what the gateway may put in a send ----------------------------------------------

def test_the_code_is_ours_and_code_length_is_never_sent():
    """`code_length` asks the vendor to generate one. The gateway generates the code it
    will later match, and a vendor-generated code is one it cannot match."""
    body = tg.build_send_body(phone="+79267889888", code="1173", ttl=300)
    assert body["code"] == "1173"
    assert "code_length" not in body


def test_the_ttl_is_the_remaining_lifetime_rather_than_a_constant():
    assert tg.build_send_body(phone="+79267889888", code="1173", ttl=300)["ttl"] == 300
    assert tg.build_send_body(phone="+79267889888", code="1173", ttl=118)["ttl"] == 118


def test_a_remaining_lifetime_below_the_vendors_floor_refuses_instead_of_inflating():
    """The supported range starts at 30 s. Rounding 11 s up to 30 would hand the vendor
    a message outliving the verification that paid for it — and the automatic refund on
    non-delivery is tied to that same `ttl`."""
    with pytest.raises(ValueError):
        tg.build_send_body(phone="+79267889888", code="1173", ttl=11)


def test_a_lifetime_past_the_vendors_ceiling_is_clamped_down_never_up():
    body = tg.build_send_body(phone="+79267889888", code="1173", ttl=9000)
    assert body["ttl"] == tg.TTL_MAX


def test_a_code_the_vendor_cannot_carry_is_refused_here():
    """4 to 8 digits, numeric. Refused before the request rather than by the vendor,
    because a refusal there is a round trip that can be billed."""
    for bad in ("117", "117311731", "11a3", ""):
        with pytest.raises(ValueError):
            tg.build_send_body(phone="+79267889888", code=bad, ttl=300)


def test_an_ability_checks_request_id_rides_the_send_that_follows_it():
    """A confirmed check is a fee already incurred; the send carrying its `request_id`
    is the free second half. A send without it buys the same message twice."""
    body = tg.build_send_body(phone="+79267889888", code="1173", ttl=300,
                              request_id="142431475830971")
    assert body["request_id"] == "142431475830971"


# --- the three calls the adapter may make, and the one it may not --------------------

def test_the_adapter_knows_only_three_vendor_methods():
    """`checkVerificationStatus` is deliberately not among them: it matches a code and
    counts attempts on a counter of its own, and two authorities counting the same
    thing is a person exhausting one while the other says four left."""
    assert tg.VENDOR_METHODS == frozenset({
        "checkSendAbility", "sendVerificationMessage", "revokeVerificationMessage"})


def test_every_call_goes_to_a_method_the_adapter_admits_to():
    async def go():
        seen: list[httpx.Request] = []
        async with transport(answering(capture("sendVerificationMessage"), seen=seen)) as c:
            await tg.check_send_ability("+79267889888", token="t", client=c)
            await tg.send_verification_message("+79267889888", code="1173", ttl=300,
                                               token="t", client=c)
        async with transport(answering(capture("revokeVerificationMessage"), seen=seen)) as c:
            await tg.request_revocation("142431475830971", token="t", client=c)

        assert len(seen) == 3
        for request in seen:
            method = request.url.path.lstrip("/")
            assert method in tg.VENDOR_METHODS
            assert request.headers["Authorization"] == "Bearer t"

    asyncio.run(go())


# --- the ability check: billable, undocumented in its refusals -----------------------

def test_a_confirmed_ability_check_carries_the_request_id_forward():
    async def go():
        async with transport(answering(capture("sendVerificationMessage"))) as c:
            ability = await tg.check_send_ability("+79267889888", token="t", client=c)
        assert ability.kind == tg.ABLE
        assert ability.request_id == "142431475830971"

    asyncio.run(go())


def test_a_refusal_arrives_on_http_200_and_is_still_a_refusal():
    """Captured live 20.09.2026 in `captures/ok-false-ACCESS_TOKEN_INVALID.json`: the
    vendor answers a refused request with **HTTP 200** and `ok: false`. A parser that
    decided by status code would read every refusal as a success."""
    async def go():
        payload = capture("ok-false-ACCESS_TOKEN_INVALID")
        assert payload == {"ok": False, "error": "ACCESS_TOKEN_INVALID"}
        async with transport(answering(payload, status_code=200)) as c:
            ability = await tg.check_send_ability("+79267889888", token="t", client=c)
        assert ability.kind == tg.REFUSED
        assert ability.error == "ACCESS_TOKEN_INVALID"

    asyncio.run(go())


def test_a_vendor_refusal_naming_a_documented_error_is_not_a_decline():
    """`ACCESS_TOKEN_INVALID` is the only error string the vendor documents. Read as a
    decline it would spend the dear rung on every verification and tell nobody."""
    async def go():
        async with transport(answering({"ok": False, "error": "ACCESS_TOKEN_INVALID"})) as c:
            ability = await tg.check_send_ability("+79267889888", token="t", client=c)
        assert ability.kind == tg.REFUSED
        assert ability.error == "ACCESS_TOKEN_INVALID"

    asyncio.run(go())


def test_an_error_string_the_vendor_never_documented_is_unclassified():
    """The reference names no error for "this subscriber is not in Telegram", so the
    decline the ladder is built on has no known spelling. Unclassified is its own
    answer: the ladder advances as it would past a decline **and** the operator is
    told, because the alternative is choosing which of the two to be silently wrong
    about. A captured refusal (task 1.7) is what turns this into a decline."""
    async def go():
        async with transport(answering({"ok": False, "error": "SOMETHING_NEW"})) as c:
            ability = await tg.check_send_ability("+79267889888", token="t", client=c)
        assert ability.kind == tg.UNCLASSIFIED
        assert ability.error == "SOMETHING_NEW"

    asyncio.run(go())


def test_an_ability_check_that_does_not_answer_is_possibly_charged():
    """Not a decline. A confirmation we never saw is a fee that can be neither spent
    nor refunded, and without its own name an unexplained fall in the balance has
    nothing to look for."""
    async def go():
        def timing_out(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("no answer", request=request)

        async with transport(timing_out) as c:
            ability = await tg.check_send_ability("+79267889888", token="t", client=c)
        assert ability.kind == tg.UNANSWERED

    asyncio.run(go())


def test_a_non_json_body_is_not_read_as_an_answer():
    async def go():
        def html(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>gateway</html>")

        async with transport(html) as c:
            ability = await tg.check_send_ability("+79267889888", token="t", client=c)
        assert ability.kind == tg.UNANSWERED

    asyncio.run(go())


# --- revocation: the vendor's `true` is a fact about our request ---------------------

def test_revocation_reports_that_the_request_was_accepted_and_nothing_more():
    """Measured twice on 18.09.2026: `{"ok": true, "result": true}` for a message the
    subscriber had already read and for one revoked a second after delivery. Both
    stayed visibly in the chat. The name of what comes back is `accepted`."""
    async def go():
        async with transport(answering(capture("revokeVerificationMessage"))) as c:
            assert await tg.request_revocation("142431475830971", token="t", client=c) is True

    asyncio.run(go())


def test_the_status_after_a_true_revocation_is_still_read():
    """The other half of the same measurement, held as a test so that a future reader
    who assumes `revoked` has to delete this line to do it."""
    after = tg.parse_request_status(
        capture("checkVerificationStatus-after-revoke")["result"])
    assert after.delivery_status == "read"
    assert after.delivery_status != "revoked"


def test_the_status_after_revoking_an_unread_message_is_still_delivered():
    """The second trial: revoked within a second of delivery, before it could be read."""
    after = tg.parse_request_status(capture("probe-1.5b-status")["result"])
    assert after.delivery_status == "delivered"


def test_a_revocation_the_vendor_refuses_is_false_rather_than_an_exception():
    """Revocation runs on the way to a terminal state that has already been decided.
    Raising here would make a vendor's mood able to leave a verification open."""
    async def go():
        async with transport(answering({"ok": False, "error": "REQUEST_ID_INVALID"})) as c:
            assert await tg.request_revocation("nope", token="t", client=c) is False

    asyncio.run(go())


# --- the signed callback -------------------------------------------------------------
# [unbacked · vendor reference read 20.09.2026: data_check_string =
#  X-Request-Timestamp + "\n" + post_body; secret_key = SHA256(api_token);
#  hex(HMAC_SHA256(data_check_string, secret_key)) == X-Request-Signature]

TOKEN = "AAExample:token"


def sign(body: bytes, timestamp: str, token: str = TOKEN) -> str:
    secret = hashlib.sha256(token.encode()).digest()
    data = timestamp.encode() + b"\n" + body
    return hmac.new(secret, data, hashlib.sha256).hexdigest()


def test_a_correctly_signed_and_timely_callback_verifies():
    body = json.dumps(capture("checkVerificationStatus")["result"]).encode()
    assert tg.callback_verifies(body, timestamp="1789713190",
                                signature=sign(body, "1789713190"),
                                token=TOKEN, tolerance=300, now=1789713200)


def test_a_body_changed_after_signing_does_not_verify():
    body = b'{"request_id":"142431475830971","phone_number":"79267889888"}'
    signature = sign(body, "1789713190")
    tampered = body.replace(b"79267889888", b"79851600019")
    assert not tg.callback_verifies(tampered, timestamp="1789713190",
                                    signature=signature, token=TOKEN,
                                    tolerance=300, now=1789713200)


def test_a_callback_signed_with_another_token_does_not_verify():
    body = b'{"request_id":"1"}'
    assert not tg.callback_verifies(body, timestamp="1789713190",
                                    signature=sign(body, "1789713190", "other"),
                                    token=TOKEN, tolerance=300, now=1789713200)


def test_a_correctly_signed_callback_replayed_later_does_not_verify():
    body = b'{"request_id":"1"}'
    signature = sign(body, "1789713190")
    assert not tg.callback_verifies(body, timestamp="1789713190", signature=signature,
                                    token=TOKEN, tolerance=300, now=1789714000)


def test_a_callback_timestamped_in_the_future_beyond_tolerance_does_not_verify():
    """A clock ahead is as much a replay window as a clock behind."""
    body = b'{"request_id":"1"}'
    signature = sign(body, "1789714000")
    assert not tg.callback_verifies(body, timestamp="1789714000", signature=signature,
                                    token=TOKEN, tolerance=300, now=1789713190)


def test_a_callback_with_an_unreadable_timestamp_does_not_verify():
    body = b'{"request_id":"1"}'
    assert not tg.callback_verifies(body, timestamp="not-a-time",
                                    signature=sign(body, "not-a-time"),
                                    token=TOKEN, tolerance=300, now=1789713190)


def test_a_callback_with_no_signature_at_all_does_not_verify():
    body = b'{"request_id":"1"}'
    assert not tg.callback_verifies(body, timestamp="1789713190", signature="",
                                    token=TOKEN, tolerance=300, now=1789713200)


def test_a_callback_does_not_verify_when_the_gateway_holds_no_token():
    """Blank token, blank signature and a body: the degenerate pair must not agree.
    This is the rung not being configured, which is a refusal and not a pass."""
    body = b'{"request_id":"1"}'
    assert not tg.callback_verifies(body, timestamp="1789713190",
                                    signature=sign(body, "1789713190", ""),
                                    token="", tolerance=300, now=1789713200)
