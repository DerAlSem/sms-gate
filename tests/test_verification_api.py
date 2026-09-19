"""The doors: create, select, check, poll.

The shape is the owner's decision of 18.09.2026 and it is what this change exists to add.
Creating a verification **proves** routes; it does not place anything. The consumer picks
one, and only then does the gateway begin carrying it. A list to choose from is not a
licence to hop: the gateway never moves a verification to another route by itself, because
a person told to watch Telegram whose verification silently becomes an SMS is looking at
the wrong screen while the right one already shows the code.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.db import queries
from app.db.connection import close_db, init_db
from app.db.migrate import run_migrations
from app.settings_store import store
from app.verification.routes import CALL_IN, SMS_IN, Proof

PHONE = "+79261234888"
AUTH = {"Authorization": "Bearer token-app1"}


class FakeModem:
    caller_id_held = True
    link_in_service = True

    def health_snapshot(self):
        return {"modem_detected": True}


def _holds():
    async def proof():
        return Proof(holds=True)
    return proof


def _fails():
    async def proof():
        return Proof(holds=False, reason="ims not registered")
    return proof


@pytest.fixture
def app():
    """The public router on a bare app, as the other door tests build it.

    Deliberately not `app.main:app`: its lifespan opens serial ports and starts the modem
    loops, and none of that is what a door is being asked about here.
    """
    from fastapi import FastAPI

    from app.api.router import router

    async def setup():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("app1", "token-app1")
        await queries.create_app("app2", "token-app2")
        await store.load()
        await store.set_many({"gateway_msisdn": "+79990001122"})

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


def _create(client, phone=PHONE, headers=None, **extra):
    return client.post("/verifications", json={"phone": phone, **extra},
                       headers=headers or AUTH)


# --- creation proves, and places nothing ------------------------------------------------

def test_creation_answers_with_an_id_and_the_routes_that_can_carry_it(client):
    r = _create(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body["id"], int)
    assert [o["route"] for o in body["routes"]] == [CALL_IN]


def test_the_answer_says_what_the_person_must_do_and_names_no_estate(client):
    body = _create(client).json()
    instruction = body["routes"][0]["instruction"]
    assert "+79990001122" in instruction
    for word in ("SIM", "modem", "ttyUSB", "vendor", "Quectel"):
        assert word.lower() not in instruction.lower()


def test_nothing_is_placed_before_a_selection(client):
    """No call placed, no message composed, no vendor charged — and the row says so by
    holding no route at all."""
    vid = _create(client).json()["id"]

    async def row():
        return dict(await queries.get_verification(vid, "app1"))

    assert asyncio.run(row())["route"] is None


def test_the_creation_answer_never_carries_the_code(client):
    """A code returned to an application lets that application confirm a verification
    without the code ever reaching the person. Which is the whole guarantee, gone."""
    body = _create(client).json()
    assert "code" not in body


def test_an_application_that_supplies_its_own_code_is_refused(client):
    """The party that answers "is this code correct" must be the party that knows what to
    compare against; splitting the secret from its matcher is what makes short codes
    unsafe."""
    r = _create(client, code="1234")
    assert r.status_code == 422
    assert "code" in r.text


def test_a_blocked_number_is_refused_without_opening_anything(client):
    async def block():
        await queries.block_phone(PHONE)

    asyncio.run(block())
    r = _create(client)
    assert r.status_code == 422
    assert "blacklist" in r.text.lower()


def test_no_route_proving_itself_is_refused_in_the_same_answer(app, client):
    """6.7 — rather than opening a verification whose only possible outcome is to expire."""
    app.state.ims_proof = _fails()
    app.state.modem = type("Down", (), {"caller_id_held": True,
                                        "link_in_service": False})()
    r = _create(client)
    assert r.status_code == 422
    assert "no_route_available" in r.text

    async def count():
        db = await __import__("app.db.connection", fromlist=["x"]).get_db()
        async with db.execute("SELECT COUNT(*) FROM verifications") as cur:
            return (await cur.fetchone())[0]

    assert asyncio.run(count()) == 0, "a verification was opened that can only expire"


# --- selection --------------------------------------------------------------------------

def test_the_consumer_picks_a_route_and_the_gateway_carries_it_by_that_one(client):
    vid = _create(client).json()["id"]
    r = client.post(f"/verifications/{vid}/route", json={"route": CALL_IN}, headers=AUTH)
    assert r.status_code == 200, r.text
    assert r.json()["route"] == CALL_IN

    async def row():
        return dict(await queries.get_verification(vid, "app1"))

    assert asyncio.run(row())["route"] == CALL_IN


def test_a_route_that_was_never_offered_is_refused_with_that_reason(client):
    vid = _create(client).json()["id"]
    r = client.post(f"/verifications/{vid}/route", json={"route": "flash_call"},
                    headers=AUTH)
    assert r.status_code == 422
    assert "not_offered" in r.text


def test_a_route_whose_precondition_has_since_lapsed_is_refused(app, client):
    """Refused with that reason rather than attempted: the proof decays after the offer,
    and the gap between offer and selection is where it decays."""
    vid = _create(client).json()["id"]
    app.state.ims_proof = _fails()
    r = client.post(f"/verifications/{vid}/route", json={"route": CALL_IN}, headers=AUTH)
    assert r.status_code == 422
    assert "not_offered" in r.text


def test_a_second_selection_is_refused_rather_than_hopping(client):
    """The gateway never moves a verification to another route by itself, and it does not
    let the door do it either — one route at a time."""
    vid = _create(client).json()["id"]
    client.post(f"/verifications/{vid}/route", json={"route": CALL_IN}, headers=AUTH)
    r = client.post(f"/verifications/{vid}/route", json={"route": CALL_IN}, headers=AUTH)
    assert r.status_code == 422
    assert "already_selected" in r.text


# --- ownership ---------------------------------------------------------------------------

def test_another_application_cannot_see_or_spend_a_verification(client):
    """Indistinguishable from a missing one, and no attempt spent: one token walking
    another's verifications does worse than read them."""
    vid = _create(client).json()["id"]
    other = {"Authorization": "Bearer token-app2"}
    assert client.get(f"/verifications/{vid}", headers=other).status_code == 404
    assert client.post(f"/verifications/{vid}/check", json={"code": "0000"},
                       headers=other).status_code == 404

    async def attempts():
        return dict(await queries.get_verification(vid, "app1"))["attempts"]

    assert asyncio.run(attempts()) == 0


# --- poll ---------------------------------------------------------------------------------

def test_the_poll_names_the_method_that_confirmed(client):
    """An application whose stakes do not tolerate the weakest of these must be able to
    see what it got, and must not have to assume the strongest."""
    vid = _create(client).json()["id"]
    client.post(f"/verifications/{vid}/route", json={"route": CALL_IN}, headers=AUTH)

    async def confirm():
        return await queries.confirm_by_inbound_call(PHONE, method=CALL_IN)

    assert asyncio.run(confirm()) == vid
    body = client.get(f"/verifications/{vid}", headers=AUTH).json()
    assert body["status"] == "confirmed"
    assert body["method"] == CALL_IN
    assert "code" not in body


# --- the one exception, and it follows the rung rather than the application -------------

def test_the_code_comes_back_only_when_the_person_is_the_one_who_must_type_it(app, client):
    """On `sms_in` the person reads the code from the screen in front of them and texts it
    from the number being verified, so the owning application must be able to display it —
    it has no other way. The exception follows the rung, not the application.

    🔴 It is handed over **on selection**, not on creation, and the spec's own words say
    "creation response". They predate this change's own decision to let the consumer pick
    the rung afterwards: at creation no rung is chosen, and handing the code to an
    application that then picks `call_in` would give away the secret for nothing.
    """
    # Nothing cheaper proves itself, so the paid rung is on the ladder — which is the
    # only state in which it can be selected at all.
    app.state.ims_proof = _fails()
    vid = _create(client).json()["id"]
    r = client.post(f"/verifications/{vid}/route", json={"route": SMS_IN}, headers=AUTH)
    assert r.status_code == 200, r.text
    assert r.json()["code"].isdigit() and len(r.json()["code"]) == 4


def test_the_same_application_on_another_rung_is_not_given_the_code(client):
    """The exception is a route's, not an application's. A code returned on a rung the
    gateway itself carries lets the application confirm without the person ever being
    reached, which is the whole guarantee gone."""
    vid = _create(client).json()["id"]
    r = client.post(f"/verifications/{vid}/route", json={"route": CALL_IN}, headers=AUTH)
    assert r.status_code == 200, r.text
    assert r.json().get("code") is None


# --- 7.3 — the call rung's own window ----------------------------------------------------

def test_choosing_the_call_rung_shortens_the_window_to_its_own(client):
    """The rung's residual risk scales with the window: an attacker can open a
    verification on a victim's number and, inside it, give the victim a reason to call.
    A person is easy to persuade to dial a number and nearly impossible to persuade to
    text four specific digits, which is the one asymmetry between this rung and the
    inbound-message one and the reason the window is worth shortening here and nowhere
    else."""
    async def shorten():
        await store.set_many({"verification_call_in_ttl_seconds": 60})

    asyncio.run(shorten())
    vid = _create(client).json()["id"]
    before = client.get(f"/verifications/{vid}", headers=AUTH).json()["expires_at"]
    client.post(f"/verifications/{vid}/route", json={"route": CALL_IN}, headers=AUTH)
    after = client.get(f"/verifications/{vid}", headers=AUTH).json()["expires_at"]
    assert after < before, f"the window was not shortened: {before} -> {after}"


def test_a_rung_window_longer_than_the_ladders_does_not_lengthen_a_verification(client):
    """Configurable separately, and never longer than the ladder's. A configuration that
    says otherwise is clamped rather than obeyed: the capability's deadline is the one
    the application was told."""
    async def lengthen():
        await store.set_many({"verification_call_in_ttl_seconds": 86400})

    asyncio.run(lengthen())
    vid = _create(client).json()["id"]
    before = client.get(f"/verifications/{vid}", headers=AUTH).json()["expires_at"]
    client.post(f"/verifications/{vid}/route", json={"route": CALL_IN}, headers=AUTH)
    after = client.get(f"/verifications/{vid}", headers=AUTH).json()["expires_at"]
    assert after == before, f"a rung lengthened a verification: {before} -> {after}"


def test_the_selected_rung_is_recorded_as_a_rung_attempted(client):
    """7.1 — per rung, not per verification, because a ladder has more than one and a
    column on the verification would answer "what did this cost" by overwriting half."""
    vid = _create(client).json()["id"]
    client.post(f"/verifications/{vid}/route", json={"route": CALL_IN}, headers=AUTH)

    async def rungs():
        from app.db.connection import get_db
        db = await get_db()
        async with db.execute(
            "SELECT verification_id, route, outcome FROM verification_rungs"
        ) as cur:
            return [tuple(r) for r in await cur.fetchall()]

    assert asyncio.run(rungs()) == [(vid, CALL_IN, "selected")]


# --- a rung that failed ends it, and the answer says what is left -----------------------

def _fail(vid, reason="route_unavailable"):
    async def go():
        return await queries.fail_verification(vid, reason=reason)
    return asyncio.run(go())


def test_a_failed_rung_ends_the_verification_and_the_answer_carries_what_is_left(client):
    """6.5 — moving on is the consumer's act, and an act needs something to act on.

    The gateway does not hop. What it owes instead is the remaining ladder, named in the
    same answer as the reason, so that selecting again is something the consumer can do
    rather than something it must rediscover by opening a verification and reading the
    list it gets back.
    """
    vid = _create(client).json()["id"]
    client.post(f"/verifications/{vid}/route", json={"route": CALL_IN}, headers=AUTH)
    assert _fail(vid) is True

    body = client.get(f"/verifications/{vid}", headers=AUTH).json()
    assert body["status"] == "failed"
    assert body["reason"] == "route_unavailable"
    assert [o["route"] for o in body["routes"]] == [SMS_IN]


def test_the_rung_that_failed_is_not_among_what_is_left_though_it_could_prove_itself(
        client):
    """The positive control, and the reason this guard is not the one above.

    `ims_proof` holds throughout this test, so `call_in` would prove itself if asked: its
    absence from the remaining ladder is because it is the rung that failed, not because
    it could not answer. Without this, a registry that simply stopped offering `call_in`
    would pass the guard above while saying something else entirely.
    """
    vid = _create(client).json()["id"]
    assert [o["route"] for o in _create(client).json()["routes"]] == [CALL_IN]

    client.post(f"/verifications/{vid}/route", json={"route": CALL_IN}, headers=AUTH)
    assert _fail(vid) is True

    body = client.get(f"/verifications/{vid}", headers=AUTH).json()
    assert CALL_IN not in [o["route"] for o in body["routes"]]


def test_what_is_left_says_what_the_person_must_do(client):
    """A route named without its instruction is not an offer — same contract as creation."""
    vid = _create(client).json()["id"]
    client.post(f"/verifications/{vid}/route", json={"route": CALL_IN}, headers=AUTH)
    _fail(vid)

    offer = client.get(f"/verifications/{vid}", headers=AUTH).json()["routes"][0]
    assert "+79990001122" in offer["instruction"]


def test_a_verification_still_being_carried_is_offered_nothing(client):
    """Because a list handed over while one rung is live reads as a licence to hop, and
    the whole of 6.5 is that it is not one."""
    vid = _create(client).json()["id"]
    client.post(f"/verifications/{vid}/route", json={"route": CALL_IN}, headers=AUTH)

    body = client.get(f"/verifications/{vid}", headers=AUTH).json()
    assert body["status"] == "pending"
    assert body["routes"] == []


def test_a_confirmed_verification_is_offered_nothing(client):
    """Nothing is left to do, and a ladder under a confirmation invites a second one."""
    vid = _create(client).json()["id"]
    client.post(f"/verifications/{vid}/route", json={"route": CALL_IN}, headers=AUTH)

    async def confirm():
        return await queries.confirm_by_inbound_call(PHONE, method=CALL_IN)

    assert asyncio.run(confirm()) == vid
    assert client.get(f"/verifications/{vid}", headers=AUTH).json()["routes"] == []


def test_selecting_again_on_a_verification_that_failed_is_refused_as_ended(client):
    """The owner's decision of 19.09.2026: failure is terminal, and a fresh verification
    is what carries the next attempt.

    Refused **as ended**, not as `already_selected`. That answer is about the route and
    would send a consumer looking for a way to release it; what actually happened is that
    the verification is over, and the list it now carries is for the next one.
    """
    vid = _create(client).json()["id"]
    client.post(f"/verifications/{vid}/route", json={"route": CALL_IN}, headers=AUTH)
    assert _fail(vid) is True

    r = client.post(f"/verifications/{vid}/route", json={"route": SMS_IN}, headers=AUTH)
    assert r.status_code == 422
    assert "verification_failed" in r.text
    assert "already_selected" not in r.text


def test_a_verification_still_open_is_still_refused_as_already_carried(client):
    """The positive control: the ending check must not swallow the hop refusal, which is
    the older and more load-bearing of the two."""
    vid = _create(client).json()["id"]
    client.post(f"/verifications/{vid}/route", json={"route": CALL_IN}, headers=AUTH)

    r = client.post(f"/verifications/{vid}/route", json={"route": SMS_IN}, headers=AUTH)
    assert r.status_code == 422
    assert "already_selected" in r.text
