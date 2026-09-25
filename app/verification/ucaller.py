"""uCaller's credential, and the one thing its reference settles about the wire.

The `flash_call` rung's adapter is task 4.17 and waits on samples (task 1.3). What does
not wait is how the vendor is authenticated, because that is answered by the reference
alone — read by layers on 22.09.2026 and captured verbatim in the change's
`captures/ucaller-reference-2026-09-22.md`.

The vendor accepts the same two values three interchangeable ways: `?key=&service_id=` on
a GET, both fields in a JSON body, or the header

    Authorization: Bearer <Секретный ключ вашего сервиса>.<Идентификатор сервиса>

so the bearer is a *derived* form of a pair, not a credential of its own. The two halves
live as two settings for a reason written where they are declared: a joined string whose
dot is missing or doubled looks configured on the settings page and arrives as the
vendor's `401` on the first paid call.

⚠️ **Nothing in production calls this yet.** The settings page reads the rows — that is
what an operator configures — but the vendor is not called by anything until 4.17 lands
the adapter, and until its probe is registered the `flash_call` rung is not offered at
all. Said out loud here rather than discovered later.
"""

from __future__ import annotations

from app.settings_store import store


def bearer(key: str | None, service_id: str | None) -> str | None:
    """The vendor's `Authorization: Bearer` value, or `None` if there is no credential.

    Written from the opposite side — nothing is a credential unless both halves say so —
    because the failure it guards is a half-configured estate offering the vendor a
    truncated bearer and reading the refusal as a wrong key.

    Both halves are stripped. A row holding a stray newline is what a paste leaves
    behind, and a bearer built from one is refused as authentication rather than reported
    as an unconfigured rung.
    """
    left = (key or "").strip()
    right = (service_id or "").strip()
    if not left or not right:
        return None
    return f"{left}.{right}"


def configured_bearer() -> str | None:
    """The bearer the estate is configured with, or `None`. What 4.17 will read."""
    return bearer(store.ucaller_key, store.ucaller_service_id)


# =========================================================================================
# The wire (task 4.17)
#
# Written against the samples captured live on 22.09.2026 on the vendor's own test numbers
# (`captures/uc-1.3-*.json`) and against the reference read by layers the same day, not
# against either alone. Three things the samples say that the reference does not, and each
# of them is a line of code here:
#
# 🔴 **`status: false` is not the error envelope.** An unreachable subscriber answers
#    `{"status":false,"ucaller_id":57251317,"phone":"7900***0002","code":"1234"}` — no
#    `error`, no numeric code, and the whole successful payload including **our own
#    verification code as a string, under the same `code` key the error envelope uses for
#    its number**. So a parser written from the reference as "not `status` → `code` is the
#    error" hands back the verification code as an error number, and one written as "not
#    `status` → nothing was created" discards an authorisation that exists, answers
#    `getInfo`, costs money on a real number and carries two free repeats. The
#    discriminator is the **presence of `error`** and nothing else; both envelopes were
#    captured live, and the shape above was seen twice.
#
#    ⚠️ Observed on the vendor's **test** number, which it serves as a simulation. Whether
#    a live failure to connect answers in the same shape is not established — which is why
#    both shapes are parsed rather than the observed one.
#
# 🔴 **`getInfo`'s field set is not stable for one `ucaller_id`.** The same authorisation
#    read minutes later answered `repeatable: false` with `repeat_times` **absent from the
#    response**, the window having closed by a field disappearing rather than by a value
#    changing. Every optional field parses to `None`, always.
#
# 🔴 **The reference's type column is wrong twice**, and the wire is what a parser meets:
#    `cost` is a number (`0.00`) and not `bool`, `phone_info` is a list (`[]`) and not an
#    object.
#
# What is deliberately not here is `initRepeat`. Measured 22.09.2026: it answered `405` on
# both documented call forms, in the same breath as a `getInfo` reporting `repeatable:
# true` and `repeat_times: 2` — so it is not the window, not the HTTP method, not the
# expiry (`11`) and not the allowance (`12`). The spec forbids calling it while it answers
# that way, and `VENDOR_METHODS` is the value that makes the exclusion readable.
# =========================================================================================

import hashlib
import logging
import re
import uuid
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.ucaller.ru/v1.0"

# What this adapter may ask the vendor. `initRepeat` is absent for the reason above, and
# `checkPhone` because this gateway already resolves operators through voxlink and would
# be paying 0,04 ₽ for a second opinion.
VENDOR_METHODS = frozenset({"initCall", "getInfo", "getBalance", "getService"})

# `call_status`, as the reference names it and both captures confirm.
PENDING = -1        # "информация проверяется (от 1 сек до 1 минуты)"
NOT_CONNECTED = 0   # the call could not be placed to this subscriber
PLACED = 1          # the call was made — which is not the same as a code having arrived

# How an answer ended. The same five words the Telegram adapter uses, because the ladder
# reads them the same way and two vocabularies for one decision is how a rung ends up
# classified differently by whichever adapter happens to answer.
ACCEPTED = "accepted"            # the vendor answered, and an authorisation exists
DECLINED = "declined"            # the vendor refused *this subscriber* or their number
REFUSED = "refused"              # the vendor refused *us*: credential, funds, cabinet
UNCLASSIFIED = "unclassified"    # a refusal we cannot place; advance, and say so out loud
UNANSWERED = "unanswered"        # no readable answer — possibly placed, possibly charged

# The vendor's numeric error codes, split by **who the refusal is about**, because that is
# the only thing the ladder does differently with them. A refusal of us stops the rung
# working for everybody within the same minute and withholds the modem rung behind it; a
# refusal about a subscriber is one person's decline and the ladder simply advances.
#
# Everything not listed stays `UNCLASSIFIED` — the ladder advances as it would past a
# decline **and** the operator is told — because choosing silently between the two is
# choosing which way to be invisibly wrong. `5` (failed to initialise), `10` (no such id),
# `11`/`12`/`13` (the free repeat, which we do not call), `405` and `500` are there
# deliberately: none of them is a statement about the subscriber, and none of them is a
# standing refusal of this gateway either.
ABOUT_US = frozenset({
    0,      # this IP is blocked
    1,      # the request is malformed — ours to fix, and it will be malformed every time
    2,      # a required parameter is missing or wrong — likewise
    4,      # the service is switched off in the cabinet
    401,    # authentication failed
    429,    # too many requests per second from this IP
    1001,   # the account is blocked
    1002,   # insufficient funds
    1003,   # this IP may not call this service's API
    1004,   # the service is archived
    1005,   # the cabinet requires this phone number to be verified
})
ABOUT_THE_SUBSCRIBER = frozenset({
    3,      # bad phone number
    9,      # this country is forbidden by the cabinet's geography settings
    18,     # this number's own 4-per-minute or 30-per-day ceiling
    19,     # "подождите 15 секунд" — this number again
    20,     # voice authorisation is unavailable for this country
})

# The vendor's range for the digits a call ends with: 0001–9999, stated by the reference
# while explaining why `code` is a string ("если 0001 вернуть в формате number он
# обрежется до 1"). `0000` is four digits and outside it, which is exactly the value a
# guard written as `\d{4}` lets through.
_CODE = re.compile(r"^\d{4}$")

# The namespace the attempt's idempotency key is derived in. A constant rather than a
# random salt: the key has to be the same after a restart, or it deduplicates nothing.
_KEY_NAMESPACE = b"sms-gate/ucaller/attempt/"


@dataclass(frozen=True)
class Placed:
    """What `initCall` answered. An authorisation the vendor allocated an id for.

    `status` is kept rather than collapsed, because it is not the refusal discriminator
    and it is not nothing: `false` here is the vendor saying, in the same answer that
    allocates the id, that it does not expect this call to connect.

    `phone` is the vendor's **masked** spelling of the number ("мы храним только хеш
    номера и маску"), kept as said rather than replaced with ours so that nothing is
    tempted to compare it to the number we sent.
    """

    ucaller_id: int | None
    code: str | None
    phone: str | None
    status: bool
    exists: bool | None = None          # only when `unique` was passed
    unique_request_id: str | None = None


@dataclass(frozen=True)
class Info:
    """What `getInfo` answered about one authorisation.

    Every field but the id is optional, and that is measured rather than defensive: the
    same `ucaller_id` read twice minutes apart returned two different field sets.
    """

    ucaller_id: int | None
    call_status: int | None = None
    code: str | None = None
    cost: float | None = None
    balance_before: float | None = None
    country_code: str | None = None
    init_time: int | None = None
    is_repeated: bool | None = None
    repeatable: bool | None = None
    repeat_times: int | None = None
    phone: str | None = None
    phone_info: tuple = ()

    @property
    def balance_after(self) -> float | None:
        """The account's balance once this operation is charged, or `None`.

        🔴 `getInfo`'s `balance` is documented as "Состояние баланса до списания этой
        операции" — the balance **before** the charge. Read as the current balance it is
        high by exactly `cost`, and a floor held against it fires one verification late.
        The subtraction is here rather than at the reader so that there is one place
        where the vendor's word and the account's balance are told apart.

        `None` where either half is missing: arithmetic on an absent field would produce
        a number indistinguishable from a reading.
        """
        if self.balance_before is None or self.cost is None:
            return None
        return self.balance_before - self.cost


@dataclass(frozen=True)
class Call:
    """What an `initCall` ended as."""

    kind: str
    placed: Placed | None = None
    error: str = ""
    error_code: int | None = None


@dataclass(frozen=True)
class Fetched:
    """What a `getInfo` ended as."""

    kind: str
    info: Info | None = None
    error: str = ""
    error_code: int | None = None


@dataclass(frozen=True)
class Balance:
    """What `getBalance` answered: the balance **remaining**, unlike `getInfo`'s."""

    kind: str
    balance: float | None = None
    tariff: str | None = None
    error: str = ""
    error_code: int | None = None


# --- numbers, codes and keys -------------------------------------------------------------

def wire_number(phone: str) -> int:
    """The number as the vendor wants to receive it: E.164 digits, no `+`, **as a JSON
    number**.

    🔴 The same digits as a string earn `code 1` ("Invalid request") on a POST body — SG-29,
    measured 25.09.2026 on the test number, one field changed at a time. The GET samples of
    1.3 could not show it: a query string has no types.
    """
    return int(re.sub(r"\D", "", phone))


def validate_code(code: str) -> str:
    """The digits the incoming call will end with, refused here rather than at the vendor.

    A round trip to find out is a round trip that can be billed, and a code outside the
    vendor's range is a verification this rung can never carry.
    """
    if not _CODE.match(code or "") or code == "0000":
        raise ValueError(
            "the vendor calls from a number ending in four digits, 0001 to 9999")
    return code


def idempotency_key(rung_id: int) -> str:
    """The `unique` this attempt carries — "идемпотетность предотвращает повторное
    списание средств".

    **Unique to the attempt, derived from it rather than drawn.** Two properties, and
    neither survives the obvious implementation:

    - a key drawn afresh deduplicates nothing, because the retry it exists to catch is
      exactly the case where the first key was never recorded — a timeout, a restart
      mid-flight. Derived from the rung row's id, the retry carries the key the lost call
      carried;
    - a key unique to the **verification** cannot do both jobs at once: deduplicating our
      retry by it would also deduplicate a legitimate repeat, which is a second attempt
      and a second row.

    The vendor asks for a UUID v4, so the derivation ends by stamping the version and
    variant bits: what it wants is the shape, and the shape is what it gets, with the
    uniqueness coming from the attempt rather than from a random draw.
    """
    digest = bytearray(hashlib.sha256(_KEY_NAMESPACE + str(rung_id).encode()).digest()[:16])
    digest[6] = (digest[6] & 0x0F) | 0x40
    digest[8] = (digest[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(digest)))


def classify(error_code: int | None) -> str:
    """Who a refusal is about. Unknown is `UNCLASSIFIED`, never a decline."""
    if error_code in ABOUT_US:
        return REFUSED
    if error_code in ABOUT_THE_SUBSCRIBER:
        return DECLINED
    return UNCLASSIFIED


def resolved(info: Info | None) -> bool:
    """Whether the vendor has said what became of the call.

    A missing `call_status` answers **no**, deliberately: an absent field is not `0` and
    not `1`, and reading it as either would report an outcome the vendor never gave.
    """
    return info is not None and info.call_status in (NOT_CONNECTED, PLACED)


# --- parsing -----------------------------------------------------------------------------

def parse_placed(body: dict) -> Placed:
    return Placed(
        ucaller_id=_as_int(body.get("ucaller_id")),
        code=str(body["code"]) if body.get("code") is not None else None,
        phone=body.get("phone"),
        status=bool(body.get("status")),
        exists=body.get("exists") if "exists" in body else None,
        unique_request_id=body.get("unique_request_id"),
    )


def parse_info(body: dict) -> Info:
    phone_info = body.get("phone_info")
    return Info(
        ucaller_id=_as_int(body.get("ucaller_id")),
        call_status=_as_int(body.get("call_status")),
        code=str(body["code"]) if body.get("code") is not None else None,
        cost=_as_float(body.get("cost")),
        balance_before=_as_float(body.get("balance")),
        country_code=body.get("country_code"),
        init_time=_as_int(body.get("init_time")),
        is_repeated=body.get("is_repeated") if "is_repeated" in body else None,
        repeatable=body.get("repeatable") if "repeatable" in body else None,
        repeat_times=_as_int(body.get("repeat_times")),
        phone=body.get("phone"),
        phone_info=tuple(phone_info) if isinstance(phone_info, list) else (),
    )


def _as_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _as_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


# --- the three calls -----------------------------------------------------------------------

async def init_call(
    phone: str, *, code: str, unique: str, bearer: str, timeout: float = 10.0,
    client: httpx.AsyncClient | None = None, client_label: str = "",
) -> Call:
    """Place the authorisation. Never raises for anything the vendor did, because the
    ladder's next step differs per failure and an exception would make them one.

    A bad `code` **does** raise: it is ours, it is wrong before the wire, and a rung asked
    to carry a code outside the vendor's range has to answer that it cannot rather than
    pay a round trip to be told.
    """
    validate_code(code)
    body = {"phone": wire_number(phone), "code": code, "unique": unique}
    if client_label:
        body["client"] = client_label
    try:
        refused, payload, error, error_code = await _call(
            "initCall", body, bearer=bearer, timeout=timeout, client=client)
    except _Unreadable as e:
        # Possibly placed and possibly charged. Deliberately not a decline: an
        # authorisation we never saw the id of is money that can be neither followed up
        # nor refunded, and it needs a count with a name to look for.
        logger.warning("ucaller: initCall gave no readable answer (%s)", e)
        return Call(kind=UNANSWERED, error=str(e))
    if refused:
        logger.info("ucaller: initCall refused (%s, code %s)", error, error_code)
        return Call(kind=classify(error_code), error=error, error_code=error_code)
    return Call(kind=ACCEPTED, placed=parse_placed(payload))


async def get_info(
    uid: int, *, bearer: str, timeout: float = 10.0,
    client: httpx.AsyncClient | None = None,
) -> Fetched:
    """Ask what became of one authorisation."""
    try:
        refused, payload, error, error_code = await _call(
            "getInfo", {"uid": uid}, bearer=bearer, timeout=timeout, client=client)
    except _Unreadable as e:
        logger.info("ucaller: getInfo gave no readable answer (%s)", e)
        return Fetched(kind=UNANSWERED, error=str(e))
    if refused:
        logger.info("ucaller: getInfo refused (%s, code %s)", error, error_code)
        return Fetched(kind=classify(error_code), error=error, error_code=error_code)
    return Fetched(kind=ACCEPTED, info=parse_info(payload))


async def get_balance(
    *, bearer: str, timeout: float = 10.0, client: httpx.AsyncClient | None = None,
) -> Balance:
    """The account's remaining balance.

    [unbacked as free · the reference documents no `cost` field on this method, unlike
    `checkPhone` — which is an inference from an absence rather than a statement. The one
    live call made on 22.09.2026 left the balance unchanged, which is weak evidence and
    the strongest available while every test authorisation costs zero.]
    """
    try:
        refused, payload, error, error_code = await _call(
            "getBalance", {}, bearer=bearer, timeout=timeout, client=client)
    except _Unreadable as e:
        return Balance(kind=UNANSWERED, error=str(e))
    if refused:
        return Balance(kind=classify(error_code), error=error, error_code=error_code)
    return Balance(kind=ACCEPTED, balance=_as_float(payload.get("rub_balance")),
                   tariff=payload.get("tariff"))


# --- the wire ------------------------------------------------------------------------------

class _Unreadable(Exception):
    """No answer, or one that cannot be read as the vendor's envelope."""


async def _call(
    method: str, body: dict, *, bearer: str, timeout: float,
    client: httpx.AsyncClient | None,
) -> tuple[bool, dict, str, int | None]:
    """One vendor call, returning `(refused, payload, error, error_code)`.

    🔴 **`refused` is the presence of `error`, never the value of `status`.** Both shapes
    of `status: false` were captured live within one evening and they mean opposite
    things — one is a refusal, the other an allocated authorisation carrying our own code.

    Bodies are never logged: an `initCall` body holds the verification code, and the code
    appears in no log line anywhere in this gateway.
    """
    if method not in VENDOR_METHODS:
        raise ValueError(f"{method} is not a method this adapter makes")

    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=timeout)
    try:
        response = await client.post(
            f"{BASE_URL}/{method}", json=body,
            headers={"Authorization": f"Bearer {bearer}",
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
    if not isinstance(envelope, dict) or "status" not in envelope:
        raise _Unreadable(
            f"{method}: HTTP {response.status_code}, not the vendor's envelope")

    error = envelope.get("error")
    if error:
        # The documented envelope: a string `error` beside a **numeric** `code`. Read the
        # number only here, where it is one — under the other envelope that same key
        # carries our verification code as a string.
        return True, {}, str(error), _as_int(envelope.get("code"))
    return False, envelope, "", None
