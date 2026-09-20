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
from app.verification.routes import CALL_IN, SMS_IN, TG_GATEWAY, Proof

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


def _probe(name, modem=None, ims_proof=None, **kw):
    return build_probes(modem or FakeModem(), ims_proof=ims_proof, **kw)[name]


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


# --- the Telegram Gateway rung ----------------------------------------------------------
#
# Its probe is the odd one of the three, and the asymmetry is deliberate rather than an
# omission. `call_in` and `sms_in` can be proven for free, so they are. This rung cannot:
# the only question the vendor answers about a subscriber is `checkSendAbility`, and that
# one is **billed when it confirms**. A probe that asked it would buy the rung during the
# offer, before the gates that could still refuse the verification had run — which is
# exactly the order the ladder's norm forbids.
#
# So the probe proves what is free to prove — that a token is held — and the rung's real
# weakness, reachability on a failed-over uplink, is carried on the same seam as the voice
# route's IMS reading: a `Proof` measured elsewhere, aged by the registry. Until
# `carry-telegram-on-any-uplink` supplies it, an unsupplied reading leaves the rung
# offered and its adapter's own bound is what stops the ladder burning its patience there.

def test_the_telegram_rung_is_absent_when_no_token_is_held():
    async def body():
        return await _probe(TG_GATEWAY, tg_token="")(PHONE)

    proof = _run(body)
    assert proof.holds is False
    assert "token" in proof.reason


def test_the_telegram_rung_is_offered_when_a_token_is_held():
    """The positive control. Without it the test above passes against a gateway that
    offers this rung to nobody ever."""
    async def body():
        return await _probe(TG_GATEWAY, tg_token="AAExample:token")(PHONE)

    assert _run(body).holds is True


def test_a_reachability_reading_that_fails_withdraws_the_rung():
    async def body():
        return await _probe(TG_GATEWAY, tg_token="AAExample:token",
                            tg_reachability=_fails("the uplink cannot reach the vendor"))(PHONE)

    proof = _run(body)
    assert proof.holds is False
    assert "uplink" in proof.reason


def test_a_reachability_reading_carries_its_age_to_the_registry():
    """The registry, not the measurer, decides how stale a proof may be. Dropping
    `measured_at` here would make a reading taken once at boot good for ever."""
    async def measured():
        return Proof(holds=True, measured_at=1789713190.0)

    async def body():
        return await _probe(TG_GATEWAY, tg_token="AAExample:token",
                            tg_reachability=measured)(PHONE)

    assert _run(body).measured_at == 1789713190.0


def test_asking_the_telegram_rung_whether_it_could_carry_places_nothing(monkeypatch):
    """Placing nothing is part of the contract, and here it is also money. Any HTTP
    client the probe reached for would be the ability check being bought during an
    offer."""
    import app.verification.tg_gateway as adapter

    def explode(*a, **kw):
        raise AssertionError("the probe contacted the vendor")

    monkeypatch.setattr(adapter.httpx, "AsyncClient", explode)

    async def body():
        return await _probe(TG_GATEWAY, tg_token="AAExample:token")(PHONE)

    assert _run(body).holds is True


# --- the token has to survive the trip from the settings to the probe -------------------
#
# A guard on the *passing* of the parameter, not on the probe. `build_probes` leaves
# `tg_token` blank when a caller forgets it, which is the safe direction and therefore the
# silent one: production would simply never offer the rung, and nothing would say why.
# Both builders of the live ladder are covered, because there are two and a fix applied to
# one of them looks finished.

def test_the_ladder_built_for_an_api_request_carries_the_configured_token():
    from types import SimpleNamespace

    import app.api.router as router

    async def body():
        await store.set_many({"tg_gateway_token": "AAExample:token"})
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
            modem=FakeModem(), ims_proof=None)))
        registry = router._registry(request)
        return {offer.route for offer in await registry.offer(PHONE)}

    assert TG_GATEWAY in _run(body)


def test_the_ladder_built_by_the_modem_manager_carries_the_configured_token():
    from app.modem.manager import ModemManager

    async def body():
        await store.set_many({"tg_gateway_token": "AAExample:token"})
        registry = ModemManager._verification_registry(FakeModem())
        return {offer.route for offer in await registry.offer(PHONE)}

    assert TG_GATEWAY in _run(body)


def test_the_rung_is_absent_from_both_ladders_when_no_token_is_configured():
    """The pair. Without it both tests above pass against a gateway that offers this
    rung unconditionally, which is the opposite defect and the expensive one."""
    from types import SimpleNamespace

    import app.api.router as router
    from app.modem.manager import ModemManager

    async def body():
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
            modem=FakeModem(), ims_proof=None)))
        from_api = {o.route for o in await router._registry(request).offer(PHONE)}
        from_modem = {o.route for o in
                      await ModemManager._verification_registry(FakeModem()).offer(PHONE)}
        return from_api, from_modem

    from_api, from_modem = _run(body)
    assert TG_GATEWAY not in from_api
    assert TG_GATEWAY not in from_modem
