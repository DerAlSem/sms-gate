"""The gateway's own number is normalised, or refused, at the moment it is saved: task 4.64.

Found by the critic circle of 22.09.2026. `RouteOffer.number` exists precisely so that a
consumer can build a `tel:` link on it without reading our English prose — that is the
decision of 22.09.2026 and the whole argument for the field. A number stored exactly as it
was typed therefore puts the gateway's own data entry onto the application's screen.

A national spelling is how a person ordinarily writes a number, and it is not wrong
anywhere else in this estate: every other door normalises on the way in. This one did not,
and the failure it produces is **mute** — the subscriber dials an address that reaches
nothing, the window closes, and the verification reports itself `expired`, which is
indistinguishable from a person who simply never called.

Checked at the save rather than at the use, for the reason already settled in this change
for `tg_gateway_callback_base`: otherwise the refusal arrives hours later, from somewhere
else, and names the wrong thing.

Both directions are guarded, and each is the other's control:

- a national spelling is **accepted and rewritten**, not refused — a validator that refused
  it would break the ordinary way an operator types a number;
- something that is not a number at all is **refused at the save** — without this the first
  half is satisfied by a validator that does nothing;
- blank still saves, because blank is the honest state of an unconfigured estate and the
  shipped default: a validator that refused it would make the estate unsavable.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.db import queries
from app.db.connection import close_db, init_db
from app.db.migrate import run_migrations
from app.settings_store import SPEC_BY_KEY, store
from app.verification.routes import CALL_IN, Proof, SMS_IN

E164 = "+79851600019"
NATIONAL = "8 (985) 160-00-19"
PHONE = "+79261234888"
AUTH = {"Authorization": "Bearer token-app1"}


def _run(body):
    async def go():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("app1", "token-app1")
        await store.load()
        return await body()

    try:
        return asyncio.run(go())
    finally:
        asyncio.run(close_db())


# --- at the setting itself ------------------------------------------------------------

def test_a_national_spelling_is_stored_in_the_form_an_application_can_dial():
    async def body():
        await store.set_many({"gateway_msisdn": NATIONAL})
        assert store.gateway_msisdn == E164, (
            f"the gateway's own number was stored as {store.gateway_msisdn!r}, which is "
            f"what an application would put in a tel: link")

    _run(body)


def test_something_that_is_not_a_number_is_refused_at_the_save():
    """The control on the test above: without this, a validator that does nothing at all
    satisfies it, because a normaliser that returns its input also 'accepts' a national
    spelling."""
    async def body():
        with pytest.raises(ValueError):
            await store.set_many({"gateway_msisdn": "call us"})
        assert store.gateway_msisdn == "", "a refused save reached the cache anyway"

    _run(body)


def test_blank_still_saves_because_blank_is_the_shipped_state():
    """Blank means neither inbound rung is offered, which is the honest answer for an
    estate that has not configured a number. A validator refusing it would make the
    shipped default unsavable."""
    async def body():
        await store.set_many({"gateway_msisdn": E164})
        await store.set_many({"gateway_msisdn": ""})
        assert store.gateway_msisdn == ""

    _run(body)


def test_the_setting_carries_a_type_rather_than_a_note():
    """The precedent is `tg_gateway_callback_base` in this same change: the check belongs
    to the setting's **type**, so a second door that saves settings cannot be a door that
    forgot it."""
    assert SPEC_BY_KEY["gateway_msisdn"].type == "msisdn"


# --- and through the door, which is where the harm was ---------------------------------

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
def client():
    from fastapi import FastAPI

    from app.api.router import router

    async def setup():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("app1", "token-app1")
        await store.load()
        await store.set_many({"gateway_msisdn": NATIONAL})

    asyncio.run(setup())
    application = FastAPI()
    application.include_router(router)
    application.state.modem = FakeModem()
    application.state.ims_proof = _holds()
    try:
        yield TestClient(application)
    finally:
        asyncio.run(close_db())


def test_the_number_handed_to_an_application_is_the_dialable_one(client):
    """🔴 The harm itself. The field is what a consumer builds a `tel:` on, so a national
    spelling reaching it is a subscriber dialling nothing — and reported as `expired`."""
    r = client.post("/verifications", json={"phone": PHONE}, headers=AUTH)
    assert r.status_code == 200, r.text
    offers = {o["route"]: o for o in r.json()["routes"]}
    asking = {route for route in offers if route in {CALL_IN, SMS_IN}}
    assert asking, "neither inbound rung was offered; this asserts nothing as written"
    for route in asking:
        assert offers[route]["number"] == E164, (
            f"{route} handed the application {offers[route]['number']!r}")
        assert offers[route]["number"] in offers[route]["instruction"], (
            f"{route}'s field and its sentence name different numbers")
