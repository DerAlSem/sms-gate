"""The door that walks the ladder: tasks 4.56 and 4.38.

Until this existed, `POST /verifications/{id}/route` accepted `tg_gateway`, recorded the
rung as `selected`, and then handled only `call_in` (shorten the window) and `sms_in` (hand
the code back). `ladder.walk` — and through it `tg_carrier`, the half that actually sends —
had no caller anywhere in `app/`. The person was told to expect a Telegram message, no
message was sent, and five minutes later the verification expired with a null reason: a
route offered that then quietly fails, which is the one thing this capability's own norm
forbids by name.

Four of these fail on the implementation that is natural to write:

- one that claims the consumer's choice in the `route` column **before** walking, which
  leaves the verification naming a rung that did not carry it. The norm is already guarded
  one layer down (`test_the_verification_names_the_rung_that_carried_it_not_the_first_tried`)
  and the door is how it comes back;
- one that bounds each rung separately, or that hardcodes the bound instead of reading the
  setting, which doubles the time the application was promised on a slow day;
- one that treats a gate's refusal as "nothing to do", which leaves a verification pending
  with a route claimed and nothing placed — 4.56 again, one door further in;
- one that walks a ladder for `call_in` or `sms_in`, where the **subscriber** is the one who
  acts and there is nothing for the gateway to place.
"""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from app.db import queries
from app.db.connection import close_db, init_db
from app.db.migrate import run_migrations
from app.settings_store import store
from app.verification import tg_gateway
from app.verification.routes import CALL_IN, FLASH_CALL, SMS_IN, TG_GATEWAY, Proof

PHONE = "+79261234888"
AUTH = {"Authorization": "Bearer token-app1"}
TOKEN = "gateway-token"


class FakeModem:
    caller_id_held = True
    link_in_service = True

    def health_snapshot(self):
        return {"modem_detected": True}


def _holds():
    async def proof():
        return Proof(holds=True)
    return proof


@pytest.fixture
def app():
    """The public router on a bare app, as the other door tests build it.

    The operator row is written rather than looked up: the rule is keyed on the operator,
    and which ladder this number gets is the thing every test here is about.
    """
    from fastapi import FastAPI

    from app.api.router import router

    async def setup():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("app1", "token-app1")
        await store.load()
        await store.set_many({"gateway_msisdn": "+79990001122",
                              "tg_gateway_token": TOKEN})
        # МегаФон is the operator the shipped rule routes to the paid ladder.
        await queries.save_number_operator(PHONE, "МегаФон", "Москва")
        # The entitlement ships off, and every paid rung is refused without it. Granted
        # here so that the tests about the ladder are about the ladder; the one test
        # about the entitlement revokes it again.
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
    """The Gateway adapter, answering from a script instead of the wire.

    Patched at the adapter's two methods rather than at its transport, because what these
    tests are about is the door reaching the vendor at all — and a transport-level fake
    would pass just as well against a door that never called one.
    """
    calls = {"checked": [], "sent": []}
    plan = {"ability": tg_gateway.ABLE, "send_ok": True, "delay": 0.0}

    async def check_send_ability(phone, *, token, timeout=10.0, client=None):
        calls["checked"].append((phone, token, timeout))
        if plan["delay"]:
            await asyncio.sleep(plan["delay"])
        if plan["ability"] != tg_gateway.ABLE:
            return tg_gateway.Ability(kind=plan["ability"], error="not on Telegram")
        return tg_gateway.Ability(
            kind=tg_gateway.ABLE, request_id="req-1",
            status=tg_gateway.RequestStatus(
                request_id="req-1", phone_number=phone.lstrip("+"),
                request_cost=0.01, remaining_balance=99.0))

    async def send_verification_message(phone, *, code, ttl, token, request_id=None,
                                        callback_url="", payload="", sender_username="",
                                        timeout=10.0, client=None):
        calls["sent"].append({"phone": phone, "code": code, "ttl": ttl,
                              "request_id": request_id, "timeout": timeout})
        if not plan["send_ok"]:
            return tg_gateway.Sent(ok=False, error="MESSAGE_SEND_FAILED")
        return tg_gateway.Sent(ok=True)

    monkeypatch.setattr(tg_gateway, "check_send_ability", check_send_ability)
    monkeypatch.setattr(tg_gateway, "send_verification_message",
                        send_verification_message)
    return calls, plan


@pytest.fixture
def alerts(monkeypatch):
    import app.alerting as alerting
    seen = []
    monkeypatch.setattr(alerting, "notify",
                        lambda kind, text, **kw: seen.append((kind, text)))
    return seen


def _open(client, phone=PHONE):
    r = client.post("/verifications", json={"phone": phone}, headers=AUTH)
    assert r.status_code == 200, r.text
    return r.json()


def _select(client, vid, route=TG_GATEWAY):
    return client.post(f"/verifications/{vid}/route", json={"route": route},
                       headers=AUTH)


def _row(vid, app_id="app1"):
    async def go():
        return await queries.get_verification(vid, app_id)
    return asyncio.run(go())


def _rungs(vid):
    async def go():
        return [(r["route"], r["outcome"]) for r in
                await queries.verification_rungs(vid)]
    return asyncio.run(go())


# --- 4.56 — the rung that could be selected and was never placed ----------------------

def test_selecting_the_telegram_rung_actually_sends_the_code(client, vendor):
    """Task 4.56. The defect in its purest form: a 200, an instruction to watch Telegram,
    and no message."""
    calls, _ = vendor
    body = _open(client)
    assert TG_GATEWAY in [o["route"] for o in body["routes"]], \
        "the rung must be offered for the rest of this file to be about anything"

    r = _select(client, body["id"])
    assert r.status_code == 200, r.text

    assert len(calls["checked"]) == 1, "the vendor was never asked whether it could send"
    assert len(calls["sent"]) == 1, "the code was never handed to the vendor"
    assert calls["sent"][0]["code"] == _stored_code(body["id"]), \
        "the vendor was handed something other than this verification's code"
    assert _rungs(body["id"])[-1] == (TG_GATEWAY, "carried")


def _stored_code(vid):
    """The code as the store holds it, read before anything can null it."""
    async def go():
        db = await __import__("app.db.connection", fromlist=["get_db"]).get_db()
        async with db.execute("SELECT code FROM verifications WHERE id = ?", (vid,)) as c:
            return (await c.fetchone())[0]
    return asyncio.run(go())


def test_the_answer_names_the_rung_that_carried_not_the_one_selected(
        client, vendor, monkeypatch):
    """The norm is `route-sends-by-operator`'s own: "the method named in the response is
    the rung that actually accepted the verification, not the first rung attempted".

    🔴 This is the test that fails on the door which claims the consumer's choice in the
    `route` column and *then* walks. `select_route` only writes where `route IS NULL`, so
    the claim wins and the verification ends up naming a rung that declined — while the
    ladder one layer down has been guarding the opposite since 4.32.

    uCaller does not exist yet (task 4.17, blocked on 1.1), so the second rung's carrier is
    a stub standing in its place. What is under test is the door's bookkeeping, not the
    vendor: the carrier map the door builds for itself is guarded by the two tests below.
    """
    calls, plan = vendor
    plan["ability"] = tg_gateway.DECLINED

    from app.verification import ladder, placement

    real = placement.carriers_for

    def with_a_second_rung(verification_id, *, app_id, **rest):
        built = real(verification_id, app_id=app_id, **rest)

        async def carry(phone, *, seconds_left, rung_id):
            return ladder.Attempt(outcome=ladder.CARRIED, vendor_ref="ucaller-1",
                                  cost=0.8)

        return {**built, FLASH_CALL: carry}

    monkeypatch.setattr(placement, "carriers_for", with_a_second_rung)

    body = _open(client)
    r = _select(client, body["id"])
    assert r.status_code == 200, r.text

    assert r.json()["route"] == FLASH_CALL, \
        "the answer named the rung the consumer picked, not the one that carried"
    assert _row(body["id"])["route"] == FLASH_CALL, \
        "the verification names a rung that declined it"
    assert _rungs(body["id"]) == [(TG_GATEWAY, "declined"), (FLASH_CALL, "carried")]


def test_a_declined_subscriber_with_no_second_carrier_fails_loudly_and_names_both_rungs(
        client, vendor, alerts):
    """The production shape today: the rule names `flash_call` second and nothing carries
    it, so the ladder advances past it loudly (4.50) and the verification fails with a
    reason naming both rungs rather than expiring with a null one."""
    calls, plan = vendor
    plan["ability"] = tg_gateway.DECLINED

    body = _open(client)
    r = _select(client, body["id"])

    row = _row(body["id"])
    assert row["status"] == "failed", "the verification was left to expire instead"
    assert TG_GATEWAY in row["reason"] and FLASH_CALL in row["reason"], \
        f"the reason names neither rung: {row['reason']!r}"
    assert _rungs(body["id"]) == [(TG_GATEWAY, "declined"), (FLASH_CALL, "absent")]
    assert any(kind == "routing" and FLASH_CALL in text for kind, text in alerts), \
        "a rung the rule names and nothing carries was skipped silently"
    assert r.json()["status"] == "failed", \
        "the door answered pending for a verification that had already failed"
    # And the cause travels in the same answer. The whole reason the ladder settles inside
    # this one response is that the consumer does not have to poll to find out what to put
    # on the screen — a `failed` with no cause makes them poll anyway.
    answered = r.json()["reason"] or ""
    assert TG_GATEWAY in answered and FLASH_CALL in answered, \
        f"the answer said the verification failed and not why: {answered!r}"
    assert len(calls["sent"]) == 0


# --- 4.38 — one bound over the whole ladder, and it is a setting ----------------------

def test_one_bound_covers_the_whole_ladder_and_comes_from_the_setting(
        client, vendor, monkeypatch):
    """Task 4.38. A slow first rung must not double the time the application waits, and
    the bound is configuration rather than a constant of the door.

    Guarded by moving the setting and watching the door follow: a hardcoded bound passes
    every assertion about the second rung being reached.
    """
    calls, plan = vendor
    plan["ability"] = tg_gateway.DECLINED
    plan["delay"] = 0.35

    from app.verification import ladder, placement

    real = placement.carriers_for
    seconds_left_seen = []

    def with_a_second_rung(verification_id, *, app_id, **rest):
        async def carry(phone, *, seconds_left, rung_id):
            seconds_left_seen.append(seconds_left)
            return ladder.Attempt(outcome=ladder.CARRIED)

        return {**real(verification_id, app_id=app_id, **rest), FLASH_CALL: carry}

    monkeypatch.setattr(placement, "carriers_for", with_a_second_rung)

    async def set_bound(value):
        await store.set_many({"verification_ladder_bound": value})

    asyncio.run(set_bound(1.0))
    started = time.monotonic()
    r = _select(client, _open(client)["id"])
    spent = time.monotonic() - started
    assert r.status_code == 200, r.text
    assert spent < 1.0 + 0.5, \
        f"the whole ladder took {spent:.2f}s against a bound of 1.0s"
    assert seconds_left_seen, "the second rung was never reached"
    assert seconds_left_seen[0] < 1.0 - 0.3, (
        "the second rung was handed a fresh bound rather than what the first rung left "
        f"of the one bound: {seconds_left_seen[0]:.2f}s")

    # And the bound is the setting's, not the door's. A wider one leaves the second rung
    # more of it; a hardcoded bound cannot tell the two runs apart.
    #
    # A second number rather than a second verification on the first: the per-number gate
    # holds fifteen seconds between two paid attempts, and it is right to. It needs its own
    # operator row — without one the rule answers through its `?` entry, which names no
    # paid rung, and the ladder would be one rung long with nothing to measure.
    other = "+79261234889"

    async def resolve_the_second_number():
        await queries.save_number_operator(other, "МегаФон", "Москва")
    asyncio.run(resolve_the_second_number())

    asyncio.run(set_bound(4.0))
    seconds_left_seen.clear()
    r = _select(client, _open(client, phone=other)["id"])
    assert r.status_code == 200, r.text
    assert seconds_left_seen and seconds_left_seen[0] > 1.0, \
        "the bound did not follow the setting"


def test_the_bound_reaches_the_vendor_and_is_not_the_adapters_own_default(client, vendor):
    """🔴 The load-bearing half of 4.38, and the one that was unguarded.

    `ladder.walk` does **not** enforce the bound — there is no `wait_for` in it, and that is
    deliberate: cancelling a carrier between a confirmed `checkSendAbility` and the row that
    records its `request_id` would lose a fee nobody can attribute, which is the one mistake
    the whole module is ordered to avoid. What it does instead is hand each rung what is left
    of the one bound, and every carrier must put that on its own vendor call.

    So the guarantee rests on two lines in `tg_carrier`, and both vendor methods carry a
    **default** — 5 s on the check, 10 s on the send. A carrier that forgot to pass the bound
    would therefore not fail; it would quietly take fifteen seconds against a bound of one.
    Measured with a bound narrower than either default, so the defaults cannot pass for it.
    """
    calls, _ = vendor

    async def narrow():
        await store.set_many({"verification_ladder_bound": 2.0})
    asyncio.run(narrow())

    r = _select(client, _open(client)["id"])
    assert r.status_code == 200, r.text
    checked_timeout = calls["checked"][0][2]
    sent_timeout = calls["sent"][0]["timeout"]
    assert 0 < checked_timeout <= 2.0, (
        f"the ability check was given {checked_timeout}s against a bound of 2.0s — the "
        f"adapter's own default is 5.0s")
    assert 0 < sent_timeout <= 2.0, (
        f"the send was given {sent_timeout}s against a bound of 2.0s — the adapter's own "
        f"default is 10.0s")

    # The control: a wider bound reaches the vendor as a wider timeout. Without it, a
    # carrier hardcoding any small number would satisfy both assertions above.
    async def wide():
        await store.set_many({"verification_ladder_bound": 8.0})
        await queries.save_number_operator("+79261234889", "МегаФон", "Москва")
    asyncio.run(wide())
    calls["checked"].clear()
    r = _select(client, _open(client, phone="+79261234889")["id"])
    assert r.status_code == 200, r.text
    assert calls["checked"][0][2] > 2.0, \
        f"the timeout did not follow the bound: {calls['checked'][0][2]}s"


def test_the_answer_names_a_method_rather_than_pending(client, vendor):
    """Task 4.38's other half. The method is the only part of the answer the person acts
    on: an application that cannot say whether to watch Telegram or the phone has nothing
    to put on the screen."""
    r = _select(client, _open(client)["id"])
    assert r.status_code == 200, r.text
    assert r.json()["route"] == TG_GATEWAY
    assert r.json()["status"] == "pending"
    assert r.json()["reason"] is None
    assert r.json()["code"] is None, \
        "the code left over a rung the gateway carries; the application could confirm " \
        "without the person ever being reached"


# --- which rungs the ladder is made of ------------------------------------------------

def test_a_rung_the_rule_does_not_name_for_this_operator_is_carried_alone(
        client, vendor, alerts):
    """The owner's decision of 21.09.2026. The Gateway rung is offered on a held token to
    **any** number, and the shipped rule sends every operator but МегаФон to `sms_out` — so
    a consumer can pick Telegram for a subscriber the rule routes to the modem. The pick is
    honoured, and the rule contributes only the continuation, which here is none of it.

    The failing reading is the one that walks the rule's answer anyway: `sms_out` has no
    carrier at this door, so the person would be told to watch Telegram and the verification
    would fail on a rung nobody chose.
    """
    calls, _ = vendor

    async def an_operator_the_rule_sends_to_the_modem():
        await queries.save_number_operator(PHONE, "МТС", "Москва")
    asyncio.run(an_operator_the_rule_sends_to_the_modem())

    body = _open(client)
    r = _select(client, body["id"])
    assert r.status_code == 200, r.text
    assert r.json()["route"] == TG_GATEWAY
    assert len(calls["sent"]) == 1
    assert _rungs(body["id"]) == [(TG_GATEWAY, "carried")], \
        "a rung the consumer did not choose was attempted"
    assert not alerts, f"a rung nobody walked was alerted about: {alerts}"


def test_the_ladder_starts_at_the_chosen_rung_and_not_at_the_top_of_the_rule(
        client, vendor, alerts):
    """Rungs ahead of the chosen one were offered and not taken, or were never offered at
    all. Walking them would place a route nobody picked — and on this ladder both rungs
    ahead are paid ones, so it would place a route nobody picked *and bill for it*."""
    calls, _ = vendor

    async def the_dear_rung_first():
        import json
        await store.set_many({"operator_routes": json.dumps(
            [{"operator": "МегаФон", "routes": [FLASH_CALL, TG_GATEWAY]},
             {"operator": "*", "routes": ["sms_out"]},
             {"operator": "?", "routes": ["sms_out"]}], ensure_ascii=False)})
    asyncio.run(the_dear_rung_first())

    body = _open(client)
    r = _select(client, body["id"])
    assert r.status_code == 200, r.text
    assert _rungs(body["id"]) == [(TG_GATEWAY, "carried")], \
        "the ladder started at the top of the rule rather than at the chosen rung"
    assert not any(FLASH_CALL in text for _, text in alerts), \
        "a rung ahead of the consumer's choice was attempted and found absent"


def test_a_verification_that_ended_under_the_walk_is_not_repointed_at_the_rung(app):
    """`set_carrying_route` is the one sanctioned move of a verification from one route to
    another, and it refuses to move one that has stopped being open.

    Asserted directly because the branch is a race: the verification ends between the
    vendor's confirmation and our record. On a paid rung that is money spent on a
    verification nobody is waiting for any more, and the record saying it was carried would
    make the fee look like a delivery. The ladder's own warning line is what reports it, and
    it only ever fires if this refuses.
    """
    async def go():
        vid = await queries.create_verification("app1", PHONE, code="1234",
                                                ttl_seconds=300)
        await queries.select_route(vid, "app1", route=TG_GATEWAY)
        # The positive control first: while it is open, the rung that carried wins.
        moved = await queries.set_carrying_route(vid, "app1", route=FLASH_CALL)
        after_open = (await queries.get_verification(vid, "app1"))["route"]

        await queries.fail_verification(vid, reason="the modem went out of service")
        ended = await queries.set_carrying_route(vid, "app1", route=TG_GATEWAY)
        after_ended = (await queries.get_verification(vid, "app1"))["route"]
        return moved, after_open, ended, after_ended

    moved, after_open, ended, after_ended = asyncio.run(go())
    assert (moved, after_open) == ("carried", FLASH_CALL)
    assert ended == "ended", f"a finished verification was moved anyway ({ended})"
    assert after_ended == FLASH_CALL, \
        "a finished verification was re-pointed at the rung that carried it too late"


def test_a_rung_whose_credential_is_blank_is_absent_from_the_carrier_map(app):
    """The second half of 4.50's credential guarantee, asserted where it lives.

    The registry refuses such a rung at the offer — the probe holds on the token — so this
    branch is not reachable through the door, and a guard written only at the door would
    leave it unguarded. Absent from the map rather than present and failing at the vendor is
    the difference between a configuration gap the ladder advances past loudly and a fee
    spent to discover one.
    """
    from app.verification import placement

    async def with_token(value):
        await store.set_many({"tg_gateway_token": value})
        # No modem, so the map holds the paid rung and nothing else: this assertion is
        # about the credential, and a modem rung standing beside it would make the
        # "nothing was built" half read as a carrier that exists.
        return placement.carriers_for(1, app_id="app1", modem=None, operator=None)

    assert TG_GATEWAY in asyncio.run(with_token(TOKEN)), \
        "the positive control: a held token must produce a carrier"
    assert asyncio.run(with_token("")) == {}, \
        "a blank credential produced a carrier that could only fail at the vendor"


# --- the door's own bookkeeping must not read as money -------------------------------

def test_the_door_does_not_count_its_own_selection_as_a_paid_attempt(client, vendor):
    """🔴 Measured, not reasoned about: `paid_attempts_since` and
    `paid_attempts_for_number` count **every row on a paid route, whatever its outcome** —
    deliberately, because an ability check that never answered may have been charged
    without our learning its `request_id`.

    So the `selected` row the door writes for its own bookkeeping is money as far as both
    ceilings are concerned, and two rows for one attempt halve them for the single rung
    that actually spends. Worse, it is self-blocking: that row is a paid attempt aged
    zero seconds, `verification_min_gap_seconds` ships at fifteen, and a door that records
    it before walking refuses **every** Gateway selection with `too_soon` — which looks
    exactly like a gate doing its job.
    """
    calls, _ = vendor
    body = _open(client)
    r = _select(client, body["id"])
    assert r.status_code == 200, r.text

    async def counts():
        return (await queries.paid_attempts_since(3600),
                len(await queries.paid_attempts_for_number(PHONE, within_seconds=3600)))

    overall, per_number = asyncio.run(counts())
    assert overall == 1, \
        f"one Gateway attempt was counted {overall} times against the spend ceiling"
    assert per_number == 1, \
        f"one Gateway attempt was counted {per_number} times against this subscriber"
    assert "too_soon" not in r.text, \
        "the door's own selection row refused the selection that wrote it"


# --- the gates: refused before any rung, and nothing left pending ---------------------

def test_an_application_with_no_entitlement_is_refused_and_the_verification_does_not_hang(
        client, vendor, app):
    """`ladder.walk` returns a gate's refusal without failing the verification — there was
    no attempt, and a rung row would put a refusal of ours into the count of what the
    vendors did. The **door** therefore owes the verification an ending: it claimed the
    route, so a verification left pending with nothing placed is 4.56 one door further in.
    """
    calls, _ = vendor

    async def revoke():
        await queries.set_app_may_spend("app1", False)
    asyncio.run(revoke())

    body = _open(client)
    r = _select(client, body["id"])

    assert r.status_code == 422, r.text
    assert "entitlement" in str(r.json()["detail"]).lower()
    assert len(calls["checked"]) == 0, "a gate refusal reached the vendor anyway"
    row = _row(body["id"])
    assert row["status"] == "failed", \
        "the verification was left pending with a route claimed and nothing placed"
    assert "entitlement" in (row["reason"] or "").lower()
    assert _rungs(body["id"]) == [], \
        "a refusal of ours was recorded as something a vendor did"


# --- the rungs the subscriber acts on are untouched -----------------------------------

def test_the_inbound_rungs_place_nothing_and_are_unchanged(client, vendor):
    """The positive control against a door that walks a ladder for every selection. On
    `call_in` and `sms_in` the **subscriber** acts; there is nothing for the gateway to
    place, and contacting a vendor for one of them would be spending money on a rung
    nobody is paying for."""
    calls, _ = vendor

    body = _open(client)
    r = _select(client, body["id"], route=CALL_IN)
    assert r.status_code == 200, r.text
    assert r.json()["route"] == CALL_IN
    assert r.json()["status"] == "pending"
    assert r.json()["code"] is None
    assert len(calls["checked"]) == 0 and len(calls["sent"]) == 0
    assert _rungs(body["id"]) == [(CALL_IN, "selected")]


def test_the_texted_rung_still_hands_the_code_back(client, vendor):
    """The one exception to the code never leaving the matcher is a **route**, and the
    door that now walks ladders must not have taken it away."""
    calls, _ = vendor

    async def only_the_texted_rung():
        # `call_in` and the Gateway out of the way, so `sms_in` is what remains.
        await store.set_many({"verification_route_order": SMS_IN})
    asyncio.run(only_the_texted_rung())

    body = _open(client)
    assert [o["route"] for o in body["routes"]] == [SMS_IN]
    r = _select(client, body["id"], route=SMS_IN)
    assert r.status_code == 200, r.text
    assert r.json()["code"] == _stored_code(body["id"])
    assert len(calls["checked"]) == 0


# --- the offer decays, and the door re-proves it --------------------------------------

def test_a_token_withdrawn_between_the_offer_and_the_selection_places_nothing(
        client, vendor):
    """Task 4.50's credential half, as it is actually reachable through the door: the
    offer is re-proved on selection, so a rung whose credential has gone is refused with
    that reason rather than attempted with an absent carrier.

    Worth stating because the obvious reading of 4.50 is the other mechanism — the
    carrier being missing from the map — and that one is not reachable here: the probe
    refuses first. The absent-carrier path is guarded one layer down, in
    `test_a_rung_with_nothing_to_carry_it_is_not_attempted_alerts_and_the_ladder_advances`.
    """
    calls, _ = vendor
    body = _open(client)

    async def withdraw():
        await store.set_many({"tg_gateway_token": ""})
    asyncio.run(withdraw())

    r = _select(client, body["id"])
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "route_not_offered"
    assert len(calls["checked"]) == 0
    assert _row(body["id"])["route"] is None, \
        "a refused selection claimed the route anyway"


# --- what the person is told ----------------------------------------------------------

def test_the_telegram_rung_says_what_the_person_must_do(client):
    """The capability requires the answer to describe what the person must do — "expect a
    message in Telegram" — for every rung it offers. The Gateway rung shipped with an
    empty instruction, which is an offer that names a route and says nothing."""
    body = _open(client)
    offer = [o for o in body["routes"] if o["route"] == TG_GATEWAY]
    assert offer, "the rung is not offered; this test is about what it says"
    assert offer[0]["instruction"].strip(), \
        "the Gateway rung is offered with an empty instruction"
    assert "Telegram" in offer[0]["instruction"]
