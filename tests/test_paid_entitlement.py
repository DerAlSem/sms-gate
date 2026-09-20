"""Who is allowed to spend, held against the application and off until someone says so.

Tasks 4.45 and 4.46. The entitlement answers a different question from the routing rule,
and the difference is the reason it is not a field of the rule: the rule answers what
reaches a subscriber and is keyed on the operator, this answers who may pay for it. The
two change at different times and for different reasons.

**Off by default is the whole guarantee, and it is a guarantee about existing installs.**
Three of the four applications on this gateway send no codes at all; a default of on would
mean the first mistake in any of them is billed rather than logged. So the migration that
adds the column leaves every row that already exists switched off — a default written only
for rows created afterwards would be a guarantee empty on exactly the installs that have
the defect.

**A refusal here is not a vendor failure and not a reroute.** Nothing is contacted, no
rung is recorded, and nothing goes out over the modem instead: for a МегаФон subscriber
the modem is the route that has been refusing, so a silent fallback would read to the
application as a delivery and behave to the person as a silence.
"""

import asyncio

import pytest

from app.db import queries
from app.db.connection import close_db, get_db, init_db
from app.db.migrate import run_migrations
from app.verification import gates, ladder
from app.verification.routes import FLASH_CALL, TG_GATEWAY

PHONE = "+79851600019"


def _run(body):
    async def go():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("app1", "token-app1")
        return await body()

    try:
        return asyncio.run(go())
    finally:
        asyncio.run(close_db())


# --- the default, and the two controls that make it mean something --------------------

def test_a_newly_issued_token_is_refused_because_the_entitlement_defaults_to_off():
    """Task 4.46, and the positive control for 4.45: an application created a moment ago
    by the ordinary route has no entitlement, and is refused for that reason."""
    async def body():
        await queries.create_app("fresh", "token-fresh")
        refusal = await gates.entitlement_gate("fresh")()
        assert refusal, "a brand new token must not be able to spend"
        assert "entitlement" in refusal

    _run(body)


def test_an_entitled_application_is_not_refused():
    """The other control. Without it the gate could be refusing everyone."""
    async def body():
        await queries.set_app_may_spend("app1", True)
        assert await gates.entitlement_gate("app1")() == ""

    _run(body)


def test_every_way_of_refusing_names_the_entitlement_and_the_application():
    """All three refusing branches, asserted together rather than one of them.

    Written this way because a mutation run found it: the reason is composed in three
    places, and a test that reads only one of them is green while the other two have
    stopped saying what they refuse. An operator meets whichever branch fired.
    """
    async def body():
        await queries.create_app("inactive", "token-inactive")
        await queries.set_app_may_spend("inactive", True)
        await queries.set_app_active("inactive", False)

        # the entitlement is off | the application is deactivated | there is no such row
        for app_id in ("app1", "inactive", "nobody"):
            refusal = await gates.entitlement_gate(app_id)()
            assert refusal, f"{app_id} must be refused"
            assert "entitlement" in refusal, \
                f"the refusal of {app_id} must name what refused it: {refusal!r}"
            assert app_id in refusal, \
                f"the refusal of {app_id} must name the application: {refusal!r}"

    _run(body)


def test_an_application_that_does_not_exist_is_refused_rather_than_allowed():
    """The absent row and the row switched off are the same answer. A lookup that
    answered "no opinion" for an unknown id would let a deleted application keep
    spending — so the query itself is asserted here, not only the gate above it."""
    async def body():
        assert await queries.app_may_spend("nobody") is False
        assert await gates.entitlement_gate("nobody")()

    _run(body)


def test_an_inactive_application_cannot_spend_even_when_entitled():
    """`is_active` is the older switch and still means what it meant. An application
    deactivated by an operator must not go on buying verifications because a second
    switch says it may."""
    async def body():
        await queries.set_app_may_spend("app1", True)
        await queries.set_app_active("app1", False)
        assert await gates.entitlement_gate("app1")()

    _run(body)


# --- it is changeable without a restart, by the same means as the rule ----------------

def test_the_entitlement_takes_effect_without_a_restart():
    async def body():
        assert await gates.entitlement_gate("app1")()
        await queries.set_app_may_spend("app1", True)
        assert await gates.entitlement_gate("app1")() == ""
        await queries.set_app_may_spend("app1", False)
        assert await gates.entitlement_gate("app1")()

    _run(body)


# --- the migration: every row that already existed is switched off --------------------

def test_an_application_that_predates_the_column_is_switched_off_by_the_migration():
    """The back-compat half of the schema change, and the half that carries the norm.

    The table is built in its pre-change shape and populated first, exactly as a live
    install holds it; the guarantee is about those rows and not about the ones a fresh
    install creates.
    """
    async def go():
        await init_db(":memory:")
        db = await get_db()
        await db.execute("""
            CREATE TABLE apps (
                id          TEXT PRIMARY KEY,
                token       TEXT UNIQUE NOT NULL,
                description TEXT,
                is_active   BOOLEAN DEFAULT 1,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute(
            "INSERT INTO apps (id, token, is_active) VALUES ('legacy', 'tok-legacy', 1)")
        await db.commit()

        await run_migrations()

        assert await queries.app_may_spend("legacy") is False
        assert await gates.entitlement_gate("legacy")(), \
            "an application that predates the column must not be able to spend"

    try:
        asyncio.run(go())
    finally:
        asyncio.run(close_db())


def test_the_migration_keeps_an_entitlement_already_granted():
    """Idempotence, because `run_migrations` runs on every start. A migration that reset
    the column each boot would revoke an operator's decision silently."""
    async def body():
        await queries.set_app_may_spend("app1", True)
        await run_migrations()
        assert await queries.app_may_spend("app1") is True

    _run(body)


# --- and the refusal reaches no rung at all -------------------------------------------

def test_an_unentitled_application_contacts_no_vendor_and_records_no_rung():
    """Asserted on the vendor not being called rather than on the outcome: a gate whose
    refusal arrives after a confirmed ability check refuses something already bought."""
    async def body():
        asked = []

        async def carrier(phone, *, seconds_left, rung_id):
            asked.append(phone)
            return ladder.Attempt(outcome=ladder.CARRIED)

        vid = await queries.create_verification("app1", PHONE, code="4321",
                                                ttl_seconds=300)
        walk = await ladder.walk(
            vid, app_id="app1", operator="МегаФон", phone=PHONE, rungs=[TG_GATEWAY, FLASH_CALL],
            gates=(gates.entitlement_gate("app1"),),
            carriers={TG_GATEWAY: carrier, FLASH_CALL: carrier}, bound=5.0)

        assert asked == []
        assert "entitlement" in walk.refused_by
        assert await queries.verification_rungs(vid) == []

    _run(body)


def test_the_refusal_is_not_reported_as_a_vendor_failure_and_sends_nothing_by_modem():
    """Two things that must not happen, and neither of them is visible in the reason
    string: the walk must carry no vendor attempt to report, and nothing may be queued
    over the modem in its place."""
    async def body():
        async def carrier(phone, *, seconds_left, rung_id):
            raise AssertionError("no rung may be contacted")

        vid = await queries.create_verification("app1", PHONE, code="4321",
                                                ttl_seconds=300)
        walk = await ladder.walk(
            vid, app_id="app1", operator="МегаФон", phone=PHONE, rungs=[TG_GATEWAY, FLASH_CALL],
            gates=(gates.entitlement_gate("app1"),),
            carriers={TG_GATEWAY: carrier, FLASH_CALL: carrier}, bound=5.0)

        assert walk.attempts == ()
        assert walk.carried_by is None
        assert walk.reason == "", "a refusal of ours must carry no vendor's reason"

        db = await get_db()
        async with db.execute(
            "SELECT COUNT(*) FROM messages WHERE phone = ?", (PHONE,)
        ) as cursor:
            assert (await cursor.fetchone())[0] == 0, \
                "a refused verification must not fall back to the modem"

    _run(body)
