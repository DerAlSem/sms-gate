"""What the two rungs this change bears actually have to prove.

9.2 and 9.3 in one file, and both are stated as pairs on purpose. "The rung is absent when
IMS is unmet" passes just as well against a gateway that offers nothing at all; the
positive control is what makes it an assertion about IMS.
"""

import asyncio

from app.db import queries
from app.db.connection import close_db, init_db
from app.db.migrate import run_migrations
from app.settings_store import store
from app.verification.probes import build_probes
from app.verification.routes import CALL_IN, SMS_IN, Proof

PHONE = "+79261234888"


class FakeModem:
    def __init__(self, *, caller_id=True, linked=True):
        self.caller_id_held = caller_id
        self.link_in_service = linked


def _holds():
    async def proof():
        return Proof(holds=True)
    return proof


def _fails(reason="ims not registered"):
    async def proof():
        return Proof(holds=False, reason=reason)
    return proof


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


def _probe(name, modem=None, ims_proof=None):
    return build_probes(modem or FakeModem(), ims_proof=ims_proof)[name]


# --- 9.2 — the silent death, both ways --------------------------------------------------

def test_the_call_rung_is_absent_when_the_voice_route_is_not_registered():
    async def body():
        return await _probe(CALL_IN, ims_proof=_fails())(PHONE)

    assert _run(body).holds is False


def test_the_call_rung_is_present_when_the_voice_route_is_registered():
    """The positive control. Without it the guard above has executed nothing."""
    async def body():
        return await _probe(CALL_IN, ims_proof=_holds())(PHONE)

    assert _run(body).holds is True


def test_no_reading_of_the_voice_route_at_all_is_unavailable_rather_than_assumed():
    """The sibling change has not landed its reading yet. Absent evidence is the failing
    direction, not the passing one — which is the whole norm."""
    async def body():
        return await _probe(CALL_IN, ims_proof=None)(PHONE)

    proof = _run(body)
    assert proof.holds is False
    assert "voice route" in proof.reason


# --- 9.3 — the caller-ID record, both ways ----------------------------------------------

def test_the_call_rung_is_absent_when_the_caller_id_subscription_was_not_issued():
    async def body():
        modem = FakeModem(caller_id=False)
        return await _probe(CALL_IN, modem=modem, ims_proof=_holds())(PHONE)

    proof = _run(body)
    assert proof.holds is False
    assert "caller-ID" in proof.reason


def test_the_call_rung_is_present_when_the_subscription_is_held():
    async def body():
        modem = FakeModem(caller_id=True)
        return await _probe(CALL_IN, modem=modem, ims_proof=_holds())(PHONE)

    assert _run(body).holds is True


# --- 6.6 — one open window per number ---------------------------------------------------

def test_a_number_with_a_call_verification_already_open_is_not_offered_that_rung():
    """A call carries no code, so attribution rests entirely on the number and the window.
    Two windows on one number leave an arriving call belonging to neither."""
    async def body():
        vid = await queries.create_verification("app1", PHONE, code=None, ttl_seconds=300)
        await queries.select_route(vid, "app1", route=CALL_IN)
        return await _probe(CALL_IN, ims_proof=_holds())(PHONE)

    proof = _run(body)
    assert proof.holds is False
    assert "already" in proof.reason


def test_another_number_being_called_does_not_close_this_one():
    """Its positive control: the rule is per number, not a global lock on the rung."""
    async def body():
        vid = await queries.create_verification(
            "app1", "+79031680015", code=None, ttl_seconds=300)
        await queries.select_route(vid, "app1", route=CALL_IN)
        return await _probe(CALL_IN, ims_proof=_holds())(PHONE)

    assert _run(body).holds is True


def test_a_window_that_has_closed_frees_the_number_again():
    """Verification happens once at onboarding, but a person who gave up and came back
    must not be locked out by their own abandoned attempt."""
    async def body():
        vid = await queries.create_verification("app1", PHONE, code=None, ttl_seconds=-1)
        await queries.select_route(vid, "app1", route=CALL_IN)
        return await _probe(CALL_IN, ims_proof=_holds())(PHONE)

    assert _run(body).holds is True


# --- the receiving rung -----------------------------------------------------------------

def test_the_inbound_message_rung_needs_a_link_that_can_receive():
    async def body():
        down = await _probe(SMS_IN, modem=FakeModem(linked=False))(PHONE)
        up = await _probe(SMS_IN, modem=FakeModem(linked=True))(PHONE)
        return down.holds, up.holds

    assert _run(body) == (False, True)
