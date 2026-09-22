"""A walk whose rungs are all free is not asked the money questions: task 4.61.

Found by the critic circle of 22.09.2026 — by both critics independently, which is what
moved it to the front. `placement.place` hands `gates.for_paid_ladder` to **every** walk,
and `PLACED_HERE` includes `sms_out`. Three of those four gates are about money, so a walk
consisting of one free modem rung is asked whether the application may spend, whether this
gateway has spent too much this hour, and what this number has spent today.

On stock settings that is not a corner, it is the ordinary path: `may_spend` ships `0` for
every application, and the shipped rule sends every operator it does not name to
`["sms_out"]` alone. So on the day this ships, a verification for an МТС subscriber is
refused `422` "does not hold the entitlement to spend on a paid route" — having spent
nothing, and having had nothing to spend.

The suite was green on this. The door test switches `may_spend` on for the whole file, and
the modem-rung test never reaches the door: it calls `carriers_for` and `walk` directly,
which is the one path where the gate list is supplied by hand. Neither could see it.

Every test here has its control, because a guard that only ever asserts an absence is a
guard that passes when the mechanism is dead:

- the free walk is not refused — controlled by the paid walk still being refused;
- the blacklist is still asked on the free walk — controlled by an unblocked number on the
  same door getting through.
"""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app.db import queries
from app.db.connection import close_db, init_db
from app.db.migrate import run_migrations
from app.settings_store import store
from app.verification.routes import FLASH_CALL, SMS_OUT, Proof

MTS = "+79161234777"        # the shipped rule does not name МТС: ladder is ["sms_out"]
MEGAFON = "+79261234888"    # named, and its ladder is paid
AUTH = {"Authorization": "Bearer token-app1"}


class FakeModem:
    caller_id_held = True
    link_in_service = True
    can_transmit = True
    can_receive = True

    def __init__(self):
        self.sent = []

    def health_snapshot(self):
        return {"modem_detected": True}

    async def enqueue(self, message_id, phone, text, app_id):
        self.sent.append((message_id, phone, text, app_id))


def _holds():
    async def proof():
        return Proof(holds=True)
    return proof


@pytest.fixture
def app():
    """The public router with the entitlement **left as it ships** — that is the point."""
    from fastapi import FastAPI

    from app.api.router import router

    async def setup():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("app1", "token-app1")
        await store.load()
        await store.set_many({"gateway_msisdn": "+79990001122",
                              "tg_gateway_token": "gateway-token"})
        await queries.save_number_operator(MTS, "МТС", "Москва")
        await queries.save_number_operator(MEGAFON, "МегаФон", "Москва")
        # No `set_app_may_spend`. Stock settings are the subject.

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


def _open(client, phone):
    r = client.post("/verifications", json={"phone": phone}, headers=AUTH)
    assert r.status_code == 200, r.text
    return r.json()


def _select(client, vid, route):
    return client.post(f"/verifications/{vid}/route", json={"route": route},
                       headers=AUTH)


def test_a_free_walk_is_not_refused_for_want_of_an_entitlement_to_spend(client):
    """The failing one. An МТС number, no entitlement, one free rung."""
    opened = _open(client, MTS)
    offered = {o["route"] for o in opened["routes"]}
    assert SMS_OUT in offered, f"the free rung was not even offered: {offered}"

    r = _select(client, opened["id"], SMS_OUT)

    assert r.status_code == 200, (
        "a walk with no paid rung in it was refused a money question: " + r.text)
    body = r.text
    assert "entitlement" not in body, body


def test_the_paid_walk_is_still_refused_without_the_entitlement(client):
    """The control. Without it the test above passes on a gate list that is empty."""
    opened = _open(client, MEGAFON)
    paid = {o["route"] for o in opened["routes"]} & {FLASH_CALL, "tg_gateway"}
    assert paid, "no paid rung was offered to the МегаФон number; the control is empty"

    r = _select(client, opened["id"], sorted(paid)[0])

    assert r.status_code == 422, r.text
    assert "entitlement" in r.text, r.text


def test_the_blacklist_is_still_asked_on_a_free_walk(client):
    """The one gate that is not about money stays unconditional — asked at the **gate**.

    Blocked *after* the verification is open, which is the whole point of 4.58: the door
    asked once at acceptance and never asks again, and the window is as wide as the
    verification's deadline. Blocking before the door would prove only that the door works.
    """
    opened = _open(client, MTS)

    async def block():
        await queries.block_phone(MTS)
    asyncio.run(block())

    r = _select(client, opened["id"], SMS_OUT)
    assert r.status_code == 422, r.text
    assert "block" in r.text.lower(), r.text


def test_an_unblocked_number_walks_the_same_free_rung(client):
    """The control: without it the test above passes on a gate list that refuses always."""
    opened = _open(client, MTS)
    r = _select(client, opened["id"], SMS_OUT)
    assert r.status_code == 200, r.text


def test_the_gate_list_follows_the_whole_ladder_and_not_the_rung_selected(client):
    """🔴 Driven through the door, because the door is where the list is assembled.

    A rule may put a free rung ahead of a paid one. Selecting the free rung does not make
    the walk free: `ladder.walk` falls through to the paid rung when the modem declines,
    and that rung spends. Assembling the gate list from the rung the consumer *named*,
    rather than from the ladder that remains, therefore reaches a vendor with no
    entitlement, no ceiling and no per-number limit — and the unit-level guard below does
    not see it, because it never goes through `placement.place`.
    """
    from app.verification import rule

    async def name_a_mixed_ladder():
        await store.set_many({rule.KEY: json.dumps(
            [{"operator": "МТС", "routes": [SMS_OUT, FLASH_CALL]}],
            ensure_ascii=False)})
    asyncio.run(name_a_mixed_ladder())

    opened = _open(client, MTS)
    r = _select(client, opened["id"], SMS_OUT)

    assert r.status_code == 422, (
        "a ladder that continues into a paid rung was not asked about money: " + r.text)
    assert "entitlement" in r.text, r.text


def test_a_ladder_free_only_at_the_top_is_still_asked_about_money():
    """🔴 The mutation only this guard catches: asking about the **first** rung.

    A rule may name a free rung ahead of a paid one. Deciding on `rungs[0]`, or on "the
    rung being selected", reads that ladder as free and lets it reach a vendor with no
    entitlement, no ceiling and no per-number limit — and every neighbouring guard stays
    green, because the door test holds the entitlement on and the modem test never
    assembles this list at all. The question is about the rungs that **remain**, not the
    one in front.
    """
    from app.verification import gates

    free_only = gates.for_paid_ladder("app1", MTS, [SMS_OUT])
    mixed = gates.for_paid_ladder("app1", MEGAFON, [SMS_OUT, FLASH_CALL])

    assert len(free_only) == 1, f"a free ladder was asked {len(free_only)} gates"
    assert len(mixed) > 1, (
        "a ladder with a paid rung behind a free one was asked only the blacklist")
