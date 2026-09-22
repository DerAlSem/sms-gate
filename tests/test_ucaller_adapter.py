# tests/test_ucaller_adapter.py
"""The uCaller adapter, against the samples captured live on 22.09.2026.

Every test that can stand on a capture stands on one. The files in
`openspec/changes/route-sends-by-operator/captures/uc-1.3-*.json` are what the vendor
actually answered on its own test numbers, and the three things they say that the
reference does not are the three this suite exists to hold:

- **`status: false` is not the error envelope.** An unreachable subscriber comes back as
  `{"status":false,"ucaller_id":…,"phone":"7900***0002","code":"1234"}` — no `error`, no
  numeric code, and **our own verification code as a string under the same `code` key the
  error envelope uses for its number**. A parser written from the reference as "not
  `status` → read `code` as the error" returns the verification code as an error code;
  one written as "not `status` → nothing was created" throws away an authorisation that
  exists, is queryable and costs money on a real number. The discriminator is the
  presence of `error`, and both envelopes were seen live;
- **`getInfo`'s field set is not stable for one `ucaller_id`.** Read again minutes later,
  the same authorisation answered `repeatable: false` with **no `repeat_times` at all**.
  A reader that takes `repeat_times` because `repeatable` was once `true` breaks on an
  ordinary expiry rather than on a vendor fault;
- **`cost` is a number** (`0.00`), not the `bool` the reference's type column says, and
  `phone_info` is a **list** (`[]`), not the object it says.

`call_status: -1` is the one shape no capture holds — both outcomes arrived already
resolved — so the tests for it stand on the reference and say so in their names.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path

import httpx
import pytest

from app.verification import ucaller as uc

CAPTURES = (Path(__file__).resolve().parent.parent
            / "openspec" / "changes" / "route-sends-by-operator" / "captures")


def capture(name: str) -> dict:
    return json.loads((CAPTURES / f"{name}.json").read_text())


def transport(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def answering(payload, *, status_code: int = 200, seen: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status_code, json=payload)
    return handler


def call(phone="+79000000001", *, code="1234", unique="k", handler=None, seen=None,
         payload=None):
    async def go():
        async with transport(handler or answering(payload, seen=seen)) as client:
            return await uc.init_call(phone, code=code, unique=unique,
                                      bearer="SECRET.1692", client=client)
    return asyncio.run(go())


def info(uid=57251313, *, handler=None, seen=None, payload=None):
    async def go():
        async with transport(handler or answering(payload, seen=seen)) as client:
            return await uc.get_info(uid, bearer="SECRET.1692", client=client)
    return asyncio.run(go())


# --- the captured wire, parsed ---------------------------------------------------------

def test_the_captured_successful_initcall_parses():
    """`uc-1.3-initCall-reachable.json`, the vendor's always-succeeds test number."""
    answer = call(payload=capture("uc-1.3-initCall-reachable"))
    assert answer.kind == uc.ACCEPTED
    assert answer.placed is not None
    assert answer.placed.ucaller_id == 57251313
    assert answer.placed.code == "1234"
    assert answer.placed.phone == "7900***0001"
    assert answer.placed.status is True


def test_status_false_without_an_error_is_an_authorisation_rather_than_a_refusal():
    """🔴 The finding that cost a capture. `uc-1.3-initCall-unreachable.json` carries
    `status: false` and the whole successful payload: an allocated id, the masked number
    and our code. Discarding it loses an authorisation that exists and is billable."""
    answer = call(payload=capture("uc-1.3-initCall-unreachable"))
    assert answer.kind == uc.ACCEPTED, "the vendor's `status` was read as the refusal"
    assert answer.placed is not None
    assert answer.placed.ucaller_id == 57251317
    assert answer.placed.status is False, (
        "what the vendor said is kept: it is not the discriminator, and it is not nothing")
    assert answer.error == "" and answer.error_code is None


def test_our_own_code_is_never_read_as_an_error_code():
    """The same answer, read the way the reference alone would have it read: `code` is
    `"1234"` — the digits we asked the vendor to call from, not a vendor error number."""
    answer = call(payload=capture("uc-1.3-initCall-unreachable"))
    assert answer.placed is not None and answer.placed.code == "1234"
    assert answer.error_code is None


def test_the_second_unreachable_capture_has_the_same_shape():
    """`uc-1.3-initCall-unreachable-2.json`. Two observations, so the shape is the
    vendor's and not one answer's accident — only the id differs."""
    answer = call(payload=capture("uc-1.3-initCall-unreachable-2"))
    assert answer.kind == uc.ACCEPTED
    assert answer.placed is not None and answer.placed.ucaller_id == 57251394


def test_the_documented_error_envelope_is_a_refusal():
    """`uc-1.3-initRepeat-405.json` — `error` plus a **numeric** `code`, captured live."""
    answer = call(payload=capture("uc-1.3-initRepeat-405"))
    assert answer.kind != uc.ACCEPTED
    assert answer.placed is None
    assert answer.error == "Method Not Allowed"
    assert answer.error_code == 405


def test_the_two_envelopes_are_told_apart_by_error_and_not_by_status():
    """Both shapes were captured live, both carry `status: false`, and they mean opposite
    things. A parser that branches on `status` is wrong for one of the two, always."""
    refusal = capture("uc-1.3-initRepeat-405")
    authorisation = capture("uc-1.3-initCall-unreachable")
    assert refusal["status"] is authorisation["status"] is False
    assert call(payload=refusal).kind != uc.ACCEPTED
    assert call(payload=authorisation).kind == uc.ACCEPTED


def test_the_captured_getinfo_reports_the_call_was_placed():
    fetched = info(payload=capture("uc-1.3-getInfo-reachable"))
    assert fetched.kind == uc.ACCEPTED
    assert fetched.info is not None
    assert fetched.info.call_status == uc.PLACED
    assert fetched.info.code == "1234"
    assert fetched.info.cost == 0.0
    assert fetched.info.balance_before == 1000.0, (
        "named `balance` here, it would be read as the account's balance — and it is the "
        "balance before this operation is charged")
    assert fetched.info.ucaller_id == 57251313


def test_the_captured_getinfo_reports_the_call_could_not_be_connected():
    fetched = info(payload=capture("uc-1.3-getInfo-unreachable"))
    assert fetched.info is not None
    assert fetched.info.call_status == uc.NOT_CONNECTED
    assert fetched.info.repeatable is True and fetched.info.repeat_times == 2


def test_the_repeat_fields_may_vanish_between_two_readings_of_one_authorisation():
    """🔴 `uc-1.3-getInfo-unreachable-later.json`: the same `ucaller_id` minutes later,
    `repeatable` `true`→`false` and `repeat_times` **gone from the answer**. Both fields
    are optional always, or the parser breaks on an ordinary expiry."""
    first = info(payload=capture("uc-1.3-getInfo-unreachable")).info
    later = info(payload=capture("uc-1.3-getInfo-unreachable-later")).info
    assert first is not None and later is not None
    assert first.ucaller_id == later.ucaller_id == 57251317
    assert first.repeat_times == 2
    assert later.repeatable is False
    assert later.repeat_times is None, "an absent field was invented as a value"


def test_cost_is_a_number_and_phone_info_is_an_empty_list():
    """The reference's type column says `bool` for `cost` and `object` for `phone_info`.
    The wire says otherwise, twice, and the wire is what a parser meets."""
    fetched = info(payload=capture("uc-1.3-getInfo-window-open"))
    assert fetched.info is not None
    assert isinstance(fetched.info.cost, float)
    assert fetched.info.phone_info == ()
    assert fetched.info.country_code == "RU"


def test_the_balance_getinfo_reports_is_the_one_before_this_operation():
    """Stated by the reference and carried as its own field name, because read as the
    current balance it is high by exactly `cost` — and a floor held against it fires one
    verification late."""
    fetched = info(payload=capture("uc-1.3-getInfo-unreachable"))
    assert fetched.info is not None
    assert fetched.info.balance_before == 1000.0
    assert fetched.info.balance_after == 1000.0 - 0.0


def test_the_balance_after_is_none_when_the_vendor_did_not_say_what_it_cost():
    """Arithmetic on a missing half would produce a number that looks like a reading."""
    fetched = info(payload={"status": True, "ucaller_id": 1, "balance": 500.0})
    assert fetched.info is not None
    assert fetched.info.balance_before == 500.0
    assert fetched.info.balance_after is None


def test_the_captured_getbalance_parses():
    async def go():
        async with transport(answering(capture("uc-1.3-getBalance"))) as client:
            return await uc.get_balance(bearer="SECRET.1692", client=client)
    answer = asyncio.run(go())
    assert answer.kind == uc.ACCEPTED
    assert answer.balance == 1000.0
    assert answer.tariff == "uni"


# --- the code, and the vendor's range for it -------------------------------------------

def test_a_code_outside_the_vendors_range_never_reaches_the_wire():
    """0001–9999, stated by the reference in the course of explaining why `code` is a
    string. `0000` is inside four digits and outside the range, which is exactly the
    value a parser written to `\\d{4}` lets through."""
    seen: list = []
    for bad in ("0000", "123", "12345", "abcd", ""):
        with pytest.raises(ValueError):
            call(code=bad, payload=capture("uc-1.3-initCall-reachable"), seen=seen)
    assert seen == [], "a code the vendor cannot carry was paid for to find out"
    # the positive control, without which every line above passes by raising always
    assert call(code="0001", payload=capture("uc-1.3-initCall-reachable")).kind == \
        uc.ACCEPTED


def test_the_door_never_mints_a_code_the_call_rung_cannot_carry():
    """The guard above is the wire's; this is the producer's, and it is where the fix
    belongs. `_new_code` drew from 0000–9999, so one verification in ten thousand would
    have been unable to use the `flash_call` rung at all — and would have advanced to
    another rung silently, which is the one failure mode this change exists to remove."""
    from app.api.router import _new_code

    class _Zeroes:
        def __init__(self):
            self.asked = 0

        def randbelow(self, n):
            self.asked += 1
            return 0 if self.asked == 1 else 4321

    import app.api.router as router_module
    original = router_module.secrets
    router_module.secrets = _Zeroes()
    try:
        assert _new_code(set()) == "4321", "0000 was minted for a rung that cannot dial it"
    finally:
        router_module.secrets = original


# --- the request this adapter actually makes -------------------------------------------

def test_the_number_goes_to_the_vendor_as_digits_without_a_plus():
    seen: list = []
    call("+7 (900) 000-00-01", payload=capture("uc-1.3-initCall-reachable"), seen=seen)
    assert json.loads(seen[0].content)["phone"] == "79000000001"


def test_the_bearer_is_the_header_form_of_the_pair():
    seen: list = []
    call(payload=capture("uc-1.3-initCall-reachable"), seen=seen)
    assert seen[0].headers["Authorization"] == "Bearer SECRET.1692"


def test_the_idempotency_key_rides_on_every_initcall():
    """"идемпотетность предотвращает повторное списание средств" — the vendor's own
    words, and the only thing standing between a retried HTTP request and a second paid
    call."""
    seen: list = []
    call(unique="the-key", payload=capture("uc-1.3-initCall-reachable"), seen=seen)
    assert json.loads(seen[0].content)["unique"] == "the-key"


def test_the_idempotency_key_is_the_attempts_and_survives_a_restart():
    """Unique to the **attempt**, not to the verification: keyed by the verification, a
    deliberate repeat would be deduplicated along with our own retry. Derived rather than
    drawn, because a key drawn afresh on a retry deduplicates nothing — which is the
    whole of what it is for."""
    assert uc.idempotency_key(41) == uc.idempotency_key(41)
    assert uc.idempotency_key(41) != uc.idempotency_key(42)


def test_the_idempotency_key_is_shaped_like_the_uuid_v4_the_vendor_asks_for():
    key = uuid.UUID(uc.idempotency_key(41))
    assert key.version == 4
    assert key.variant == uuid.RFC_4122
    assert len(uc.idempotency_key(41)) <= 64


def test_only_the_methods_this_adapter_makes_can_be_called():
    """`initRepeat` is deliberately absent: it answered `405` on both documented call
    forms while the vendor itself reported the repeat window open, so the spec forbids
    calling it. Absent as a value a test can read, not as a habit."""
    assert "initRepeat" not in uc.VENDOR_METHODS
    assert {"initCall", "getInfo", "getBalance"} <= uc.VENDOR_METHODS

    async def go():
        async with transport(answering({"status": True})) as client:
            await uc._call("initRepeat", {}, bearer="B", timeout=1.0, client=client)
    with pytest.raises(ValueError):
        asyncio.run(go())


# --- what a refusal means --------------------------------------------------------------

@pytest.mark.parametrize("code, kind", [
    (401, uc.REFUSED),    # the credential
    (1002, uc.REFUSED),   # insufficient funds
    (1003, uc.REFUSED),   # this IP may not call this service's API
    (4, uc.REFUSED),      # the service is switched off in the cabinet
    (3, uc.DECLINED),     # this number
    (9, uc.DECLINED),     # this country
    (18, uc.DECLINED),    # this number's own per-minute or per-day ceiling
    (500, uc.UNCLASSIFIED),
    (405, uc.UNCLASSIFIED),
    (None, uc.UNCLASSIFIED),
])
def test_a_vendor_error_is_classified_by_who_it_is_about(code, kind):
    """The distinction the ladder turns on: a refusal of **us** stops the rung working
    for everybody and withholds the modem, while a refusal about **this subscriber** is
    one person's decline and the ladder advances past it."""
    assert uc.classify(code) == kind


def test_an_unplaceable_refusal_is_its_own_answer_rather_than_a_decline():
    answer = call(payload={"status": False, "error": "something new", "code": 4242})
    assert answer.kind == uc.UNCLASSIFIED
    assert answer.error == "something new" and answer.error_code == 4242


def test_a_refusal_of_us_is_named_as_such():
    answer = call(payload={"status": False, "error": "Authentication failed", "code": 401})
    assert answer.kind == uc.REFUSED


# --- what an unreadable answer means ---------------------------------------------------

def test_a_non_json_body_is_unanswered_rather_than_a_refusal():
    """Every vendor error arrives over HTTP 200 with a JSON envelope. Anything else is a
    proxy, a captive portal or an outage — and reading it as a decline would advance the
    ladder past a rung that was never asked."""
    def handler(request):
        return httpx.Response(200, text="<html>go away</html>")
    answer = call(handler=handler)
    assert answer.kind == uc.UNANSWERED
    assert answer.placed is None


def test_an_envelope_without_status_is_unanswered():
    answer = call(payload={"hello": "world"})
    assert answer.kind == uc.UNANSWERED


def test_a_transport_failure_is_unanswered_rather_than_raised():
    """The ladder's next step differs per failure, and an exception makes them one."""
    def handler(request):
        raise httpx.ConnectError("no route to host")
    assert call(handler=handler).kind == uc.UNANSWERED


def test_getinfo_on_an_id_the_vendor_does_not_know_is_a_refusal_not_an_outcome():
    fetched = info(payload={"status": False, "error": "id not found", "code": 10})
    assert fetched.kind == uc.UNCLASSIFIED
    assert fetched.info is None


# --- the outcome the vendor reports ----------------------------------------------------

def test_an_unresolved_outcome_is_neither_a_placed_call_nor_a_failure():
    """[unbacked · reference: `-1` is "информация проверяется (от 1 сек до 1 минуты)".
    `call_status: -1` was not observed once — both captures arrived already resolved.]"""
    fetched = info(payload={"status": True, "ucaller_id": 1, "call_status": -1})
    assert fetched.info is not None
    assert fetched.info.call_status == uc.PENDING
    assert uc.resolved(fetched.info) is False

    for status in (0, 1):
        fetched = info(payload={"status": True, "ucaller_id": 1, "call_status": status})
        assert uc.resolved(fetched.info) is True


def test_a_getinfo_that_does_not_say_what_became_of_the_call_is_not_read_as_resolved():
    """The failing direction: a missing `call_status` is not `0` and not `1`."""
    fetched = info(payload={"status": True, "ucaller_id": 1})
    assert fetched.info is not None and fetched.info.call_status is None
    assert uc.resolved(fetched.info) is False


# --- the code appears in no log line ----------------------------------------------------

def test_no_line_this_adapter_logs_carries_the_code(caplog):
    """The same guarantee the rest of this gateway holds: the code is in no API response,
    no alert and no log line. A request body is the one place it would leak from here."""
    caplog.set_level(logging.DEBUG, logger="app.verification.ucaller")
    call(code="4242", payload={"status": False, "error": "Authentication failed",
                               "code": 401})
    call(code="4242", handler=lambda request: httpx.Response(200, text="not json"))
    assert "4242" not in caplog.text
