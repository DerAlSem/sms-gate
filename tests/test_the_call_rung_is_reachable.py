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
from app.db.connection import close_db, init_db
from app.db.migrate import run_migrations
from app.settings_store import store
from app.verification import tg_gateway, ucaller
from app.verification.routes import FLASH_CALL, Proof, TG_GATEWAY

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
