"""The Telegram Gateway rung: our code, carried to a subscriber reachable in Telegram.

Written against the samples captured live on 18.09.2026 and 20.09.2026 and kept in
`openspec/changes/route-sends-by-operator/captures/`, not against the documentation
alone. Five things the captures say that the reference does not, and each of them is a
line of code here:

- **the number comes back without its `+`.** We send `+79267889888`; every response
  says `79267889888`. A response compared to its own request by string equality never
  finds the row it belongs to, so the join is `same_number`, on digits;
- **fields arrive when they are needed and not otherwise.** An ability check carries no
  `delivery_status`; a status answer carries no `remaining_balance`; `is_refunded` has
  now been absent from ten captures running, the billed ones included. A parser that
  requires any of them falls over on a perfectly ordinary response, so every optional
  field parses to None — and `None` stays distinguishable from a vendor that said
  `false`, which is the whole of what `is_refunded` costs us;
- 🔴 **`remaining_balance` is the account's balance only in the answer to
  `checkSendAbility`.** Measured 20.09.2026 within one request: the check answered
  `remaining_balance: 99.99`, and the free send that followed it answered
  `remaining_balance: 0` with nothing in between to spend it. 18.09 could not tell —
  the account really did hold zero then, and the field agreed by accident. So this
  module parses the number wherever the vendor puts it and **names no balance**:
  whatever comes to hold a "the balance is running out" alarm reads it from the check
  and from nowhere else. It is also why there is no "is the balance sufficient"
  precondition here: the vendor decides, and it decides per request;
- 🔴 **revocation moves something on the paid path, and it is not the delivery.**
  On 18.09 `revokeVerificationMessage` answered `{"ok": true, "result": true}` twice
  for free messages to the account holder's own number, and both stayed in the chat
  with `delivery_status.status` never becoming `revoked`. On 20.09 the same call
  against a **billed** message to a third party answered the same `true` — and the
  status afterwards carried `verification_status: expired`, a field no earlier capture
  had ever shown, while `delivery_status` read `delivered` and still not `revoked`. So
  "inert" was the free path's answer and does not carry over; what carries over is the
  narrower fact. The function here is called `request_revocation` and returns whether
  the request was **accepted**, and nothing in this capability may rest on it having
  removed anything from anyone's screen — which remains unobserved on both paths.
  The reference, re-read 20.09.2026, says why: revocation "does not guarantee that the
  message will be deleted... if the message has already been delivered or read, it
  will not be removed". All three trials revoked something already delivered, which is
  the case the vendor excludes; revoking a still-undelivered message was never tried.
  A guarantee that expires on delivery is not one this capability could lean on.

Three vendor methods are reachable from here and a fourth deliberately is not.
`checkVerificationStatus` matches a code and counts attempts on a counter of the
vendor's own; using it would put two authorities on one question, with different
limits, and a person exhausting one while the other still says four left. The gateway
matches the code it generated.

Money, stated once because the design would otherwise be built as though it were free:
`checkSendAbility` is billed when it **confirms**. What is free is the second half —
one `sendVerificationMessage` carrying the returned `request_id` — and an undelivered
message is refunded at the end of its `ttl`. So a confirmed check must be followed by
exactly one send, never abandoned and never repeated with the same `request_id`, and
every gate that could refuse a verification has to have been passed before the check
is made at all. Those are the ladder's obligations; this module's part is to make them
expressible — the `request_id` rides forward, and an unanswered check has its own name
rather than being folded into a decline.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://gatewayapi.telegram.org"

# What this adapter may ask the vendor. Named as a value so that the exclusion of
# `checkVerificationStatus` is a fact a test can read rather than a habit.
VENDOR_METHODS = frozenset({
    "checkSendAbility", "sendVerificationMessage", "revokeVerificationMessage",
})

# The vendor's supported range for `ttl`, in seconds.
TTL_MIN = 30
TTL_MAX = 3600

# The vendor's supported shape for a code it is asked to carry.
_CODE = re.compile(r"^\d{4,8}$")

# How an ability check ended.
ABLE = "able"                    # confirmed — one fee incurred, one send owed
DECLINED = "declined"            # the subscriber cannot be reached — nothing charged
REFUSED = "refused"              # the vendor refused *us*: token, balance, our request
UNANSWERED = "unanswered"        # no readable answer within the bound — possibly charged
UNCLASSIFIED = "unclassified"    # `ok: false` with an error string we cannot place

# The error strings we can place. The vendor's reference documents exactly one of them
# and names none at all for "this subscriber is not in Telegram" — the decline the
# whole ladder is built on. `PHONE_NUMBER_NOT_AVAILABLE` is therefore not read out of
# any document: it was captured live on 20.09.2026 (`captures/probe-1.7-check-
# declined.json`) against a real, working number whose owner has no Telegram, and it
# cost nothing, as a decline must.
#
# ⚠️ One sample names the spelling; it does not bound the meaning. Whether the vendor
# answers the same string for a number that is malformed, unallocated or merely
# unroutable is **not** established, and both readings send the ladder the same way,
# so nothing here turns on it yet. What would turn on it is a count: a rung that
# appears to decline everyone is a rung taken out of the rule for the wrong reason.
#
# Everything still unplaceable stays `UNCLASSIFIED` — the ladder advances as it would
# past a decline **and** the operator is told — because choosing silently between the
# two is choosing which way to be invisibly wrong.
FATAL_ERRORS = frozenset({"ACCESS_TOKEN_INVALID"})
DECLINE_ERRORS: frozenset[str] = frozenset({"PHONE_NUMBER_NOT_AVAILABLE"})


@dataclass(frozen=True)
class RequestStatus:
    """The vendor's `RequestStatus`, with every optional field optional here too.

    `phone_number` is kept exactly as the vendor said it — without the `+` — because
    storing our own spelling of it would hide the discrepancy that `same_number`
    exists to bridge.
    """

    request_id: str
    phone_number: str
    request_cost: float | None = None
    remaining_balance: float | None = None
    is_refunded: bool | None = None
    delivery_status: str | None = None
    delivery_updated_at: int | None = None
    verification_status: str | None = None
    payload: str | None = None


@dataclass(frozen=True)
class Ability:
    """What an ability check answered, and what it may have cost.

    `kind` is one of the five above. `request_id` is set only on `ABLE`, and it is the
    thing the send that follows must carry.
    """

    kind: str
    request_id: str | None = None
    error: str = ""
    status: RequestStatus | None = None


@dataclass(frozen=True)
class Sent:
    """What a send answered. `status` is absent when the vendor refused the request."""

    ok: bool
    status: RequestStatus | None = None
    error: str = ""


# --- numbers -------------------------------------------------------------------------

def wire_number(phone: str) -> str:
    """The number as the vendor wants to receive it: E.164, `+` included."""
    return "+" + re.sub(r"\D", "", phone)


def same_number(ours: str, theirs: str) -> bool:
    """Whether a number the vendor echoed is the one we sent.

    The vendor drops the leading `+` on the way back. Everything else is identical, so
    the comparison is on digits and nothing more clever is warranted.
    """
    return bool(re.sub(r"\D", "", ours)) and \
        re.sub(r"\D", "", ours) == re.sub(r"\D", "", theirs)


# --- parsing ---------------------------------------------------------------------------

def parse_request_status(result: object) -> RequestStatus:
    """Parse a `RequestStatus`. Only `request_id` and `phone_number` are required.

    Raises ValueError when the object is not a request status at all, which is a
    different thing from a request status missing its optional halves.
    """
    if not isinstance(result, dict):
        raise ValueError("not a request status object")
    request_id = result.get("request_id")
    phone_number = result.get("phone_number")
    if not request_id or not phone_number:
        raise ValueError("request status without an id or a number")

    delivery = result.get("delivery_status")
    delivery = delivery if isinstance(delivery, dict) else {}
    verification = result.get("verification_status")
    verification = verification if isinstance(verification, dict) else {}

    return RequestStatus(
        request_id=str(request_id),
        phone_number=str(phone_number),
        request_cost=_as_float(result.get("request_cost")),
        remaining_balance=_as_float(result.get("remaining_balance")),
        is_refunded=result.get("is_refunded") if "is_refunded" in result else None,
        delivery_status=delivery.get("status"),
        delivery_updated_at=delivery.get("updated_at"),
        verification_status=verification.get("status"),
        payload=result.get("payload"),
    )


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


# --- the send request ------------------------------------------------------------------

def build_send_body(
    *, phone: str, code: str, ttl: int, request_id: str | None = None,
    callback_url: str = "", payload: str = "", sender_username: str = "",
) -> dict:
    """The body of a `sendVerificationMessage`, refusing here what the vendor would
    refuse after a round trip — and a round trip is a thing that can be billed.

    `code_length` is never present. It asks the vendor to generate a code, and a code
    the gateway did not generate is one it cannot match at `POST /verifications/{id}/check`.
    """
    if not _CODE.match(code or ""):
        raise ValueError("the vendor carries a numeric code of 4 to 8 digits")
    if ttl < TTL_MIN:
        # Not clamped up. The `ttl` is the verification's remaining lifetime, and
        # inflating it would hand the vendor a message that outlives the verification
        # it belongs to — while the automatic refund on non-delivery is tied to that
        # same `ttl`. Too little life left is a reason not to buy the rung at all.
        raise ValueError(
            f"only {ttl}s of the verification's life remain, below the vendor's "
            f"{TTL_MIN}s floor")

    body: dict = {
        "phone_number": wire_number(phone),
        "code": code,
        "ttl": min(ttl, TTL_MAX),
    }
    if request_id:
        body["request_id"] = request_id
    if callback_url:
        body["callback_url"] = callback_url
    if payload:
        body["payload"] = payload
    if sender_username:
        body["sender_username"] = sender_username
    return body


# --- the three calls ---------------------------------------------------------------------

async def check_send_ability(
    phone: str, *, token: str, timeout: float = 5.0,
    client: httpx.AsyncClient | None = None,
) -> Ability:
    """Ask whether this subscriber can be reached. Confirmation is billable.

    Never raises: every failure has a `kind`, because the ladder's next step differs
    per failure and an exception would make them one.
    """
    try:
        ok, result, error = await _call(
            "checkSendAbility", {"phone_number": wire_number(phone)},
            token=token, timeout=timeout, client=client)
    except _Unreadable as e:
        # Possibly charged, and deliberately not a decline: a confirmation we never saw
        # is a fee that can be neither spent nor refunded, and an unexplained fall in
        # the vendor's balance needs a count with a name to look for.
        logger.warning("tg_gateway: the ability check gave no readable answer (%s)", e)
        return Ability(kind=UNANSWERED, error=str(e))

    if ok:
        try:
            status = parse_request_status(result)
        except ValueError as e:
            logger.warning("tg_gateway: ability confirmed but unparseable (%s)", e)
            return Ability(kind=UNANSWERED, error=str(e))
        return Ability(kind=ABLE, request_id=status.request_id, status=status)

    return Ability(kind=_classify(error), error=error)


async def send_verification_message(
    phone: str, *, code: str, ttl: int, token: str, request_id: str | None = None,
    callback_url: str = "", payload: str = "", sender_username: str = "",
    timeout: float = 10.0, client: httpx.AsyncClient | None = None,
) -> Sent:
    """Send our code. Where `request_id` is given this is the free half of a confirmed
    ability check, and it may be made exactly once for that id."""
    body = build_send_body(phone=phone, code=code, ttl=ttl, request_id=request_id,
                           callback_url=callback_url, payload=payload,
                           sender_username=sender_username)
    try:
        ok, result, error = await _call("sendVerificationMessage", body,
                                        token=token, timeout=timeout, client=client)
    except _Unreadable as e:
        return Sent(ok=False, error=str(e))
    if not ok:
        return Sent(ok=False, error=error)
    try:
        return Sent(ok=True, status=parse_request_status(result))
    except ValueError as e:
        return Sent(ok=False, error=str(e))


async def request_revocation(
    request_id: str, *, token: str, timeout: float = 5.0,
    client: httpx.AsyncClient | None = None,
) -> bool:
    """Ask the vendor to withdraw an outstanding message. Returns whether the request
    was **accepted** — not whether anything was withdrawn.

    🔴 Measured twice on 18.09.2026: `true` came back for a message the subscriber had
    already read and for one revoked within a second of delivery, and in both trials
    the message stayed visibly in the chat while `delivery_status.status` remained
    `read` and `delivered`. The vendor's `true` reports that the request was taken.
    The guarantee that a finished verification stops being usable is carried by the
    terminal state here, never by this call.

    Runs on the way to a state already decided, so it returns False rather than raising:
    a vendor's mood must not be able to leave a verification open.
    """
    try:
        ok, result, error = await _call("revokeVerificationMessage",
                                        {"request_id": request_id},
                                        token=token, timeout=timeout, client=client)
    except _Unreadable as e:
        logger.info("tg_gateway: revocation gave no readable answer (%s)", e)
        return False
    if not ok:
        logger.info("tg_gateway: revocation refused (%s)", error)
        return False
    return result is True


def _classify(error: str) -> str:
    if error in FATAL_ERRORS:
        return REFUSED
    if error in DECLINE_ERRORS:
        return DECLINED
    return UNCLASSIFIED


# --- the wire -----------------------------------------------------------------------

class _Unreadable(Exception):
    """No answer, or one that cannot be read as the vendor's envelope."""


async def _call(
    method: str, body: dict, *, token: str, timeout: float,
    client: httpx.AsyncClient | None,
) -> tuple[bool, object, str]:
    """One vendor call, returning (ok, result, error). Bodies are never logged: a send
    body holds the code, and the code appears in no log line anywhere in this gateway.
    """
    if method not in VENDOR_METHODS:
        raise ValueError(f"{method} is not a method this adapter makes")

    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=timeout)
    try:
        response = await client.post(
            f"{BASE_URL}/{method}", json=body,
            headers={"Authorization": f"Bearer {token}",
                     "User-Agent": "sms-gate/1.0"},
            timeout=timeout,
        )
    except httpx.HTTPError as e:
        raise _Unreadable(f"{method}: {e}") from e
    finally:
        if own:
            await client.aclose()

    try:
        envelope = response.json()
    except ValueError as e:
        raise _Unreadable(f"{method}: HTTP {response.status_code}, non-JSON body") from e
    if not isinstance(envelope, dict) or "ok" not in envelope:
        raise _Unreadable(f"{method}: HTTP {response.status_code}, not the vendor's envelope")
    if envelope["ok"]:
        return True, envelope.get("result"), ""
    return False, None, str(envelope.get("error") or "")


# --- the signed callback ---------------------------------------------------------------
# [unbacked · vendor reference, read 20.09.2026:
#  data_check_string = X-Request-Timestamp + "\n" + post_body
#  secret_key = SHA256(api_token)
#  hex(HMAC_SHA256(data_check_string, secret_key)) == X-Request-Signature ]

def callback_verifies(
    body: bytes, *, timestamp: str, signature: str, token: str,
    tolerance: float, now: float,
) -> bool:
    """Whether this callback is the vendor's, and recent enough to act on.

    Both halves are refusals in the failing direction. An endpoint that moves a
    verification's state without them is a way to confirm a verification without the
    code ever reaching the person — the same guarantee the code's secrecy protects,
    given away at a different door. The endpoint is public by necessity: the vendor has
    to reach it.

    `now` is passed rather than read so that the tolerance is testable at all; there is
    no correct default for it.
    """
    return not callback_refusal(body, timestamp=timestamp, signature=signature,
                                token=token, tolerance=tolerance, now=now)


def callback_refusal(
    body: bytes, *, timestamp: str, signature: str, token: str,
    tolerance: float, now: float,
) -> str:
    """Why this callback is refused — `""`, `"stale"` or `"signature"`.

    🔴 **The two are one refusal and two different events, and saying which is the whole
    of task 4.66's cheap half.** A run of `stale` is a clock; a run of `signature` is a
    forged callback — or a credential rotated while messages were in flight, which is
    neither, and which silently drops every refund those messages would have reported.
    Counted under one key, all three looked alike, and the one that costs money looked
    exactly like the one that does not.

    The order is deliberate: a callback outside the window is refused as stale whatever
    its signature says, because a signature computed over a replayed body verifies
    perfectly and the window is what makes the replay useless. The failing direction is
    unchanged — anything this cannot read is `"signature"`.
    """
    if not token or not signature:
        return "signature"
    try:
        sent_at = float(timestamp)
    except (TypeError, ValueError):
        return "signature"
    if abs(now - sent_at) > tolerance:
        return "stale"

    secret = hashlib.sha256(token.encode()).digest()
    expected = hmac.new(secret, timestamp.encode() + b"\n" + body,
                        hashlib.sha256).hexdigest()
    return "" if hmac.compare_digest(expected, signature) else "signature"
