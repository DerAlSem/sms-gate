# tests/test_the_call_rung_is_reachable.py
"""The `flash_call` rung, from the door rather than from the carrier.

Task 4.17a shipped the Telegram adapter with a line saying "implemented is not reachable",
and four days later task 4.56 found what that costs: a rung a consumer could select, be
told to expect, and never be sent. This file is the same question asked of the call rung
**before** it can be answered the same way — every test here drives a real HTTP request
through the real registry, the real rule, the real placement and into the adapter, which
is the only layer faked.

Three properties, and each is a way the rung could ship looking finished:

- **it is offered when the credential is held, and only then.** A blank credential is not
  a rung that fails at the vendor, it is a rung that is not offered;
- **selecting it places a call.** The registry, `placement.PLACED_HERE`, `carriers_for`
  and the carrier all have to agree, and each of them could be the one that quietly does
  not;
- **the ladder crosses to it.** A МегаФон subscriber the Gateway declines is what the
  whole change exists for, and until this passed, the second rung was a name in a rule.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.db import queries
from app.db.connection import close_db, get_db, init_db
from app.db.migrate import run_migrations
from app.settings_store import store
from app.verification import tg_gateway, ucaller
from app.verification.routes import (
    CALL_IN, FLASH_CALL, Proof, SMS_IN, SMS_OUT, TG_GATEWAY,
)

PHONE = "+79261234888"
AUTH = {"Authorization": "Bearer token-app1"}
TOKEN = "gateway-token"


class FakeModem:
    caller_id_held = True
    link_in_service = True
    can_transmit = True
    can_receive = True

    def health_snapshot(self):
        return {"modem_detected": True}


def _holds():
    async def proof():
        return Proof(holds=True)
    return proof


@pytest.fixture
def app():
    from fastapi import FastAPI

    from app.api.router import router

    async def setup():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("app1", "token-app1")
        await store.load()
        await store.set_many({"gateway_msisdn": "+79990001122",
                              "tg_gateway_token": TOKEN,
                              "ucaller_key": "SECRET",
                              "ucaller_service_id": "747277"})
        await queries.save_number_operator(PHONE, "МегаФон", "Москва")
        await queries.set_app_may_spend("app1", True)

    asyncio.run(setup())
    application = FastAPI()
    application.include_router(router)
    application.state.modem = FakeModem()
    application.state.ims_proof = _holds()
    try:
        yield application
    finally:
        asyncio.run(close_db())


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def vendor(monkeypatch):
    """Both vendors, answering from a script instead of the wire.

    Patched at the adapters' methods rather than at their transports, because what these
    tests are about is the door reaching a vendor at all — and a transport-level fake
    would pass just as well against a door that never called one.
    """
    calls = {"initCall": [], "getInfo": [], "checked": []}
    plan = {"tg": tg_gateway.DECLINED, "call_status": ucaller.PLACED, "code": None}

    async def check_send_ability(phone, *, token, timeout=10.0, client=None):
        calls["checked"].append(phone)
        if plan["tg"] != tg_gateway.ABLE:
            return tg_gateway.Ability(kind=plan["tg"], error="PHONE_NUMBER_NOT_AVAILABLE")
        return tg_gateway.Ability(
            kind=tg_gateway.ABLE, request_id="req-1",
            status=tg_gateway.RequestStatus(request_id="req-1",
                                            phone_number=phone.lstrip("+")))

    async def send_verification_message(phone, *, code, ttl, token, request_id=None,
                                        callback_url="", payload="", sender_username="",
                                        timeout=10.0, client=None):
        return tg_gateway.Sent(ok=True)

    async def init_call(phone, *, code, unique, bearer, timeout=10.0, client=None,
                        client_label=""):
        calls["initCall"].append({"phone": phone, "code": code, "unique": unique,
                                  "bearer": bearer})
        return ucaller.Call(kind=ucaller.ACCEPTED, placed=ucaller.Placed(
            ucaller_id=57251313, code=plan["code"] or code, phone="7926***888",
            status=True))

    async def get_info(uid, *, bearer, timeout=10.0, client=None):
        calls["getInfo"].append(uid)
        return ucaller.Fetched(kind=ucaller.ACCEPTED, info=ucaller.Info(
            ucaller_id=uid, call_status=plan["call_status"], code=plan["code"],
            cost=0.8, balance_before=100.8))

    monkeypatch.setattr(tg_gateway, "check_send_ability", check_send_ability)
    monkeypatch.setattr(tg_gateway, "send_verification_message",
                        send_verification_message)
    monkeypatch.setattr(ucaller, "init_call", init_call)
    monkeypatch.setattr(ucaller, "get_info", get_info)
    return calls, plan


def _open(client, phone=PHONE):
    r = client.post("/verifications", json={"phone": phone}, headers=AUTH)
    assert r.status_code == 200, r.text
    return r.json()


def _select(client, vid, route=FLASH_CALL):
    return client.post(f"/verifications/{vid}/route", json={"route": route}, headers=AUTH)


def _row(vid):
    async def go():
        return await queries.get_verification(vid, "app1")
    return asyncio.run(go())


def _rungs(vid):
    async def go():
        return [(r["route"], r["outcome"], r["vendor_ref"]) for r in
                await queries.verification_rungs(vid)]
    return asyncio.run(go())


# --- offered, and only on a credential ---------------------------------------------------

def test_the_call_rung_is_offered_once_the_credential_is_held(client):
    offered = {o["route"] for o in _open(client)["routes"]}
    assert FLASH_CALL in offered, (
        "the credential is held, the adapter is built, and the rung is still not offered")


def test_the_call_rung_names_what_the_person_must_do(client):
    """A rung with no instruction is an offer that names a route and tells the person
    nothing — the defect the Telegram rung shipped with."""
    instruction = next(o["instruction"] for o in _open(client)["routes"]
                       if o["route"] == FLASH_CALL)
    assert instruction.strip(), "the call rung is offered with an empty instruction"
    assert "four" in instruction.lower()


def test_a_blank_credential_withdraws_the_offer_rather_than_failing_at_the_vendor(client):
    asyncio.run(store.set_many({"ucaller_key": ""}))
    offered = {o["route"] for o in _open(client)["routes"]}
    assert FLASH_CALL not in offered


# --- selected, and actually placed ----------------------------------------------------------

def test_selecting_the_call_rung_actually_places_a_call(client, vendor):
    """4.56 asked of this rung before it could be answered the same way."""
    calls, _ = vendor
    vid = _open(client)["id"]
    r = _select(client, vid)
    assert r.status_code == 200, r.text
    assert calls["initCall"], "the rung was selected and no call was placed"
    assert calls["initCall"][0]["phone"] == PHONE
    assert calls["initCall"][0]["bearer"] == "SECRET.747277"
    assert _row(vid)["route"] == FLASH_CALL


def test_the_code_that_travels_is_the_verifications_own(client, vendor):
    calls, _ = vendor
    vid = _open(client)["id"]
    _select(client, vid)
    assert calls["initCall"][0]["code"] == _row(vid)["code"]


def test_a_placed_call_leaves_the_verification_awaiting_a_code(client, vendor):
    vid = _open(client)["id"]
    _select(client, vid)
    row = _row(vid)
    assert row["status"] == "pending", "a placed call was read as a confirmed code"
    assert ("flash_call", "carried", "57251313") in _rungs(vid)


def test_a_call_that_could_not_be_connected_ends_the_verification_with_that_reason(
        client, vendor):
    _, plan = vendor
    plan["call_status"] = ucaller.NOT_CONNECTED
    vid = _open(client)["id"]
    _select(client, vid)
    row = _row(vid)
    assert row["status"] == "failed"
    assert "connect" in (row["reason"] or "")


# --- the ladder crossing -------------------------------------------------------------------

def test_a_megafon_subscriber_the_gateway_declines_is_called_instead(client, vendor):
    """The whole change in one request: the cheap rung declines the subscriber, and the
    call rung behind it in the rule carries the same code. Two vendor identifiers and one
    code, which is the only thing that makes this a ladder rather than two routes that
    happen to be configured together."""
    calls, _ = vendor
    vid = _open(client)["id"]
    r = _select(client, vid, route=TG_GATEWAY)
    assert r.status_code == 200, r.text

    assert calls["checked"], "the Telegram rung was never asked"
    assert calls["initCall"], "the ladder stopped at the declining rung"
    walked = [(route, outcome) for route, outcome, _ in _rungs(vid)]
    assert walked == [(TG_GATEWAY, "declined"), (FLASH_CALL, "carried")], walked
    assert _row(vid)["route"] == FLASH_CALL, (
        "the verification names the rung that declined it rather than the one that called")


# --- the vendor's per-number window, held from the door ------------------------------------

def _age_the_paid_rungs(phone, *, seconds):
    """Push this number's paid rung rows that far into the past.

    The database's own clock, because the gate compares ages the database computed — and
    a test that reached for this process's would be making the two-clock mistake the
    query above it avoids.
    """
    async def go():
        db = await get_db()
        await db.execute(
            "UPDATE verification_rungs "
            "   SET started_at = datetime('now', ? || ' seconds') "
            " WHERE verification_id IN (SELECT id FROM verifications WHERE phone = ?)",
            (f"{-int(seconds):+d}", phone))
        await db.commit()
    asyncio.run(go())


def test_a_second_request_inside_the_vendors_window_is_refused_with_the_wait_named(
        client, vendor):
    """Task 4.12, and its second half could not be asked until this rung existed.

    The gate itself is guarded in `tests/test_per_number_limits.py`, against the ladder
    driven by a fake carrier. What that could not ask is the half the task actually names:
    **no vendor call is placed.** Until 22.09.2026 no call could be placed by anything, so
    a guard on the absence of one passed against a gateway that had no way to place one
    either. Here the door is real, the registry, the rule and the placement are real, and
    the thing counted is `ucaller.init_call` — the method that spends the money and starts
    the vendor's ten-hour block.
    """
    calls, _ = vendor
    assert _select(client, _open(client)["id"]).status_code == 200
    assert len(calls["initCall"]) == 1, "the first request placed no call"

    r = _select(client, _open(client)["id"])
    assert r.status_code == 422, r.text
    detail = str(r.json()["detail"])
    assert "too_soon" in detail and "wait" in detail, (
        f"the refusal does not name the wait: {detail}")
    assert len(calls["initCall"]) == 1, (
        "a second call was placed for this number inside the vendor's window — which is "
        "the ten hours of not being able to log in at all that this gate exists to spare")


def test_the_refused_second_request_records_no_rung_and_does_not_hang(client, vendor):
    """A refusal of ours is not something a vendor did, and the door still owes the
    verification an ending: it claimed the route before walking."""
    _select(client, _open(client)["id"])

    second = _open(client)["id"]
    assert _select(client, second).status_code == 422
    assert _rungs(second) == [], \
        "a refusal of ours was recorded as something a vendor did"
    row = _row(second)
    assert row["status"] == "failed", \
        "a route was claimed, nothing was placed, and the verification was left pending"
    assert "too_soon" in (row["reason"] or ""), row["reason"]


def test_the_window_holds_the_whole_ladder_rather_than_the_call_rung_alone(client, vendor):
    """Telegram publishes no rate limits, and that is the absence of a statement rather
    than a statement of absence — so a second request selecting the Telegram rung is
    refused on the same window, and neither vendor is contacted. Selecting the cheap rung
    is the reachable way to spend on the dear one: the ladder descends to `flash_call`
    when the Gateway declines."""
    calls, _ = vendor
    _select(client, _open(client)["id"])
    asked_before = len(calls["checked"])

    r = _select(client, _open(client)["id"], route=TG_GATEWAY)
    assert r.status_code == 422, r.text
    assert "too_soon" in str(r.json()["detail"])
    assert len(calls["checked"]) == asked_before, \
        "the Telegram rung was contacted inside a window counted over both paid rungs"
    assert len(calls["initCall"]) == 1, \
        "the ladder descended past the gate and called the dear rung"


def test_a_request_after_the_window_has_passed_is_called(client, vendor):
    """The positive control, and it is the load-bearing half: without it the guards above
    pass against a door that refuses every second request for ever, which is a gateway
    that verifies each number once."""
    calls, _ = vendor
    _select(client, _open(client)["id"])
    _age_the_paid_rungs(PHONE, seconds=20)

    r = _select(client, _open(client)["id"])
    assert r.status_code == 200, r.text
    assert len(calls["initCall"]) == 2, \
        "the gap had passed and the second call was still not placed"


# --- a number the gateway has decided not to touch ------------------------------------

def _block(phone=PHONE):
    async def go():
        await queries.block_phone(phone)
    asyncio.run(go())


def test_a_number_blocked_after_the_verification_opened_reaches_no_vendor(client, vendor):
    """🔴 The window is real and it is five minutes wide.

    `POST /verifications` refuses a blocked number before it opens anything, and that is
    guarded. What it cannot cover is the number blocked *afterwards* — by a delivery report
    crossing `blacklist_threshold` on another message, or by an operator's hand — because
    the verification is already open and the selection door never asks again. Inside that
    window the ladder places a **paid call** to a number this gateway has decided not to
    contact at all, and the money is gone before anybody notices.

    Asserted on the vendor not being reached rather than on the answer: the whole point is
    that nothing is placed.
    """
    calls, _ = vendor
    vid = _open(client)["id"]
    _block()

    r = _select(client, vid)
    assert r.status_code == 422, r.text
    assert "blacklist" in str(r.json()["detail"]).lower(), r.text
    assert calls["initCall"] == [], (
        "a paid call was placed to a number the gateway holds blocked")
    assert _rungs(vid) == [], \
        "a refusal of ours was recorded as something a vendor did"
    assert _row(vid)["status"] == "failed", \
        "a route was claimed, nothing was placed, and the verification was left pending"


def test_the_block_is_asked_on_the_cheap_rung_too_and_not_only_on_the_call(client, vendor):
    """The gate belongs to the ladder, not to the rung that happens to cost the most. A
    blocked number selecting Telegram must not reach that vendor either — a confirmed
    `checkSendAbility` is billed, so this rung spends too."""
    calls, _ = vendor
    vid = _open(client)["id"]
    _block()

    r = _select(client, vid, route=TG_GATEWAY)
    assert r.status_code == 422, r.text
    assert calls["checked"] == [], "a blocked number was offered to the Telegram vendor"
    assert calls["initCall"] == []


def test_an_unblocked_number_on_the_same_door_is_still_called(client, vendor):
    """The positive control. Without it the two guards above pass against a door that
    refuses every selection — a gateway that verifies nobody."""
    calls, _ = vendor
    vid = _open(client)["id"]
    r = _select(client, vid)
    assert r.status_code == 200, r.text
    assert len(calls["initCall"]) == 1


def test_the_block_is_a_gate_of_the_ladder_rather_than_a_check_at_one_door(client):
    """🔴 The guards above pass just as well against a check written into
    `select_verification_route`, and that is the defect this one exists to catch.

    A check at a door is a census of doors, and a census is never complete: it goes stale in
    silence the moment somebody adds the next way into the paid ladder. The invariant belongs
    on the boundary instead — `gates.for_paid_ladder` is the list every walk must pass, and
    it exists precisely so that a door added later cannot be a door that forgot one.

    So this asks the question without naming which gate answers it: assemble the real list,
    run it against a blocked number, and require that **something** in it refuses. Move the
    check out to the door and this goes red while the door-level guards stay green.
    """
    from app.verification import gates

    async def go():
        await queries.block_phone(PHONE)
        refusals = [await gate() for gate in gates.for_paid_ladder("app1", PHONE, [FLASH_CALL])]
        return [r for r in refusals if r]

    refused = asyncio.run(go())
    assert refused, (
        "no gate of the paid ladder refuses a blocked number; the block is being asked at "
        "a door rather than on the boundary, and the next door will not ask it")
    assert any("blacklist" in r.lower() for r in refused), refused


# --- the number is normalised before the operator is looked up ------------------------

def test_a_number_written_unnormalised_is_normalised_before_the_operator_is_read(client):
    """The half of the same requirement that had no guard at this door.

    The validator is there — `VerificationCreateRequest.phone` runs the same
    `validate_and_normalize` the send's schema runs — and `tests/test_phone.py` guards the
    function itself. What nothing asked is the consequence the requirement actually argues
    for: **the operator table is keyed on the normalised number.** An unnormalised one
    resolves to no operator at all, takes the rule's unknown-operator entry, and for a
    МегаФон subscriber that entry is the modem — the one route this whole change exists to
    route away from. The number would be perfectly valid, the request would succeed, and the
    code would go out over the route that has been failing.

    So this drives the national form through the real door and asks what came of it, rather
    than asking whether a validator is present.
    """
    national = "8" + PHONE[2:]          # 89261234888 for +79261234888
    assert national != PHONE

    body = _open(client, phone=national)
    row = _row(body["id"])
    assert row["phone"] == PHONE, (
        f"the verification was opened on {row['phone']!r} rather than on the normalised "
        f"number; the operator table is keyed on the normalised form")

    offered = {o["route"] for o in body["routes"]}
    assert FLASH_CALL in offered, (
        "the operator did not resolve, so the rule answered through its unknown entry and "
        "the paid rung this subscriber needs was never offered")


def test_the_two_spellings_are_offered_the_same_ladder(client):
    """The positive control, and it is the one with teeth: it fails on a door that refuses
    or mangles the national form outright, where the guard above would also fail but for the
    wrong reason."""
    national = "8" + PHONE[2:]
    assert ({o["route"] for o in _open(client, phone=national)["routes"]}
            == {o["route"] for o in _open(client)["routes"]})


# --- the number the person must reach, as data (task 3.4) ------------------------------

MSISDN = "+79990001122"


def test_the_rungs_that_ask_the_person_to_reach_us_hand_over_the_number_as_data(client):
    """🔴 Task 3.4, the owner's decision of 22.09.2026.

    `instruction` is English and it is not ours to translate — `docs/i18n.md` covers the
    admin console and nothing else, and there is no gettext anywhere in `app/verification`.
    So an application whose person reads Russian had two options and both were bad: show
    them English, or recover the digits from our prose with a regular expression. The second
    is the worse one, because it makes our wording an **unwritten part of the contract** that
    breaks the day somebody improves a sentence.

    The remedy is a field. The estate holds the number as configuration and can hand it over
    as data, leaving the wording to the application that owns the screen.
    """
    offers = {o["route"]: o for o in _open(client)["routes"]}
    asking = {r for r in offers if r in {CALL_IN, SMS_IN}}
    assert asking, "neither inbound rung was offered; this asserts nothing as written"

    for route in asking:
        assert offers[route]["number"] == MSISDN, (
            f"{route} tells the person to reach a number and hands the application none")
        assert offers[route]["number"] in offers[route]["instruction"], (
            f"{route}'s field and its sentence name different numbers")


def test_the_rungs_where_the_gateway_acts_hand_over_no_number(client):
    """The failing direction, and it is not tidiness. On these rungs the gateway is the one
    that acts; an address handed back invites an application to tell somebody to call it,
    and the person would be dialling a number that is expecting nothing."""
    offers = {o["route"]: o for o in _open(client)["routes"]}
    acting = {r for r in offers if r in {SMS_OUT, TG_GATEWAY, FLASH_CALL}}
    assert acting, "no rung the gateway acts on was offered; this asserts nothing"
    for route in acting:
        assert offers[route]["number"] is None, (
            f"{route} handed back an address on a rung where the gateway acts")


def test_the_sentence_is_unchanged_by_the_field_existing(client):
    """A consumer reading only `instruction` sees exactly what it saw before."""
    offers = {o["route"]: o for o in _open(client)["routes"]}
    assert offers[FLASH_CALL]["instruction"].startswith("Wait for a call")
    if CALL_IN in offers:
        assert offers[CALL_IN]["instruction"].startswith(f"Call {MSISDN} from")


def test_the_field_is_additive_and_not_merely_new():
    """🔴 Back-compat as a property of the schema, not as a sentence in a commit message.

    Additive means a caller that predates the field still constructs the model. Written
    against `RouteOffer` directly because that is where the promise lives: the door always
    passes the field, so every guard driven through HTTP is green whether the default exists
    or not — and the promise would be broken with the whole suite still passing."""
    from app.api.schemas import RouteOffer

    offer = RouteOffer(route=FLASH_CALL, instruction="Wait for a call")
    assert offer.number is None, \
        "the field has no default, so a consumer that predates it can no longer build one"
