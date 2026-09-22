"""What the two rungs this change bears actually have to prove.

9.2 and 9.3 in one file, and both are stated as pairs on purpose. "The rung is absent when
IMS is unmet" passes just as well against a gateway that offers nothing at all; the
positive control is what makes it an assertion about IMS.
"""

import asyncio
import json

from app.db import queries
from app.db.connection import close_db, init_db
from app.db.migrate import run_migrations
from app.settings_store import store
from app.verification.probes import build_probes
from app.verification import rule
from app.verification.routes import (
    CALL_IN, FLASH_CALL, SMS_IN, SMS_OUT, TG_GATEWAY, Proof,
)

PHONE = "+79261234888"


class FakeModem:
    """The modem as the probes see it — and the two directions are separate.

    `linked` sets both, which is what every test that does not care about the split
    wants; `transmit` and `receive` override one side each, which is what the pair of
    rungs that hold on opposite directions needs.
    """

    def __init__(self, *, caller_id=True, linked=True, transmit=None, receive=None):
        self.caller_id_held = caller_id
        self.link_in_service = linked
        self.can_transmit = linked if transmit is None else transmit
        self.can_receive = linked if receive is None else receive


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
    """The credentials default here and nowhere else: a test about `call_in` should not
    have to name the two vendors, while a *builder* of the live ladder must name them —
    which is why `build_probes` itself has no default for either."""
    kw.setdefault("tg_token", "")
    kw.setdefault("ucaller_bearer", "")
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
    """And a link that can **receive**, which is not the same link as `sms_out` needs.

    The third case is the load-bearing one: with the sender port gone and the reader
    alive, asking the person to text us is the right offer, and a probe written on the
    conjunction would withdraw it. Written the other way round — both rungs on
    `link_in_service` — `sms_in` is never offered at all, because it sits last in the
    order and `sms_out` proving drops it.
    """
    async def body():
        down = await _probe(SMS_IN, modem=FakeModem(linked=False))(PHONE)
        up = await _probe(SMS_IN, modem=FakeModem(linked=True))(PHONE)
        send_only_down = await _probe(
            SMS_IN, modem=FakeModem(transmit=False, receive=True))(PHONE)
        return down.holds, up.holds, send_only_down.holds

    assert _run(body) == (False, True, True)


# --- the modem rung, and the rule as part of its precondition ---------------------------
#
# Task 4.17c, the owner's decision of 21.09.2026: the consumer may choose `sms_out`. Two
# conditions had to be settled before the probe could be registered at all, and each of
# them is a way the rung would have been offered **wrongly** rather than not offered.

def test_the_modem_rung_needs_a_link_that_can_transmit():
    """And transmitting is not receiving. The second case is the pair of the `sms_in`
    guard above: one modem state, two rungs, opposite answers."""
    async def body():
        up = await _probe(SMS_OUT, modem=FakeModem(linked=True))(PHONE)
        receive_only = await _probe(
            SMS_OUT, modem=FakeModem(transmit=False, receive=True))(PHONE)
        return up.holds, receive_only.holds

    assert _run(body) == (True, False)


def test_the_modem_rung_is_not_offered_where_the_rule_sends_the_operator_elsewhere():
    """🔴 The one that matters, and the failure it prevents is this change's whole subject.

    An offered rung is a rung the consumer may pick, and a rung the consumer picks is
    honoured even where the rule does not name it — the owner's decision of 21.09.2026,
    "carried alone". So offering the modem for an operator the rule diverts away from it
    would put the code out over the route that operator has been rejecting, reached
    through the **offer** rather than through the ladder: a delivery to the application
    and a silence to the person.

    The positive control is the same number, the same modem and the same probe, with the
    one entry rewritten — which is the control shape this change settled on after twice
    finding a guard standing over a place nothing could reach.
    """
    operator = "МегаФон"

    async def body():
        await queries.save_number_operator(PHONE, operator, None)
        diverted = json.dumps(
            [{"operator": operator, "routes": [TG_GATEWAY]},
             {"operator": rule.DEFAULT, "routes": [SMS_OUT]},
             {"operator": rule.UNKNOWN, "routes": [SMS_OUT]}], ensure_ascii=False)
        await store.set_many({rule.KEY: diverted})
        away = await _probe(SMS_OUT)(PHONE)

        named = json.dumps(
            [{"operator": operator, "routes": [TG_GATEWAY, SMS_OUT]},
             {"operator": rule.DEFAULT, "routes": [SMS_OUT]},
             {"operator": rule.UNKNOWN, "routes": [SMS_OUT]}], ensure_ascii=False)
        await store.set_many({rule.KEY: named})
        toward = await _probe(SMS_OUT)(PHONE)
        return away, toward

    away, toward = _run(body)
    assert away.holds is False, \
        "the modem was offered for an operator the rule routes away from it"
    assert operator in away.reason, away.reason
    assert toward.holds is True, \
        "the positive control: the same operator, named to the modem, must be offerable"


def test_an_unresolved_operator_takes_the_rules_unknown_entry():
    """A number with no row is not a number the rule cannot answer for.

    Read from the cache and never looked up: the application's answer does not wait for
    enrichment, and the `?` entry is what answers meanwhile — which is exactly what the
    sender does with the same number.
    """
    async def body():
        ships_to_the_modem = await _probe(SMS_OUT)(PHONE)
        await store.set_many({rule.KEY: json.dumps(
            [{"operator": rule.DEFAULT, "routes": [SMS_OUT]},
             {"operator": rule.UNKNOWN, "routes": [TG_GATEWAY]}], ensure_ascii=False)})
        unknown_elsewhere = await _probe(SMS_OUT)(PHONE)
        return ships_to_the_modem.holds, unknown_elsewhere.holds

    assert _run(body) == (True, False)


def test_an_unreadable_rule_does_not_offer_the_modem():
    """Never read as "no rule". Read that way it would send every diverted operator's
    traffic straight back to the route that is rejecting it — and the offer is where
    that decision would be taken invisibly."""
    async def body():
        # Inserted rather than saved: `set_many` validates, and this state is reached by
        # a hand-edited row or a type that changed under a stored value, not by the
        # console. An UPDATE that matched nothing would leave the shipped rule in force
        # and pass this test for the wrong reason.
        from app.db.connection import get_db
        db = await get_db()
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (rule.KEY, "{not json at all"))
        await db.commit()
        await store.load()
        assert store.get(rule.KEY) == "{not json at all"
        return await _probe(SMS_OUT)(PHONE)

    proof = _run(body)
    assert proof.holds is False
    assert "rule" in proof.reason.lower(), proof.reason


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


# --- 7.1 — and the credential has to survive the same trip ------------------------------
#
# The guard above was written for `tg_token` alone, and the rung it does not name is the
# one that broke. `ucaller_bearer` has the same blank default and the same two builders,
# and on 22.09.2026 the modem manager's builder was passing neither it nor anything in its
# place: live, at 22:06:30 and 22:07:30 MSK, the sweep read `no uCaller credential is held`
# against a credential that had been in `settings` since 21:01 and ended a verification
# whose call was already placed and already paid for.
#
# So the shape is the same shape, deliberately: whoever adds the next parameter to
# `build_probes` should find the pattern here rather than the omission.

def test_the_ladder_built_for_an_api_request_carries_the_configured_credential():
    from types import SimpleNamespace

    import app.api.router as router

    async def body():
        await store.set_many({"ucaller_key": "SECRET", "ucaller_service_id": "1692"})
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
            modem=FakeModem(), ims_proof=None)))
        registry = router._registry(request)
        return {offer.route for offer in await registry.offer(PHONE)}

    assert FLASH_CALL in _run(body)


def test_the_ladder_built_by_the_modem_manager_carries_the_configured_credential():
    """The half that was missing. The manager's ladder is not the door's second opinion —
    it is what the sweep re-proves an *open* verification against, so a rung this builder
    cannot offer is a verification this builder kills."""
    from app.modem.manager import ModemManager

    async def body():
        await store.set_many({"ucaller_key": "SECRET", "ucaller_service_id": "1692"})
        registry = ModemManager._verification_registry(FakeModem())
        return {offer.route for offer in await registry.offer(PHONE)}

    assert FLASH_CALL in _run(body)


def test_the_call_rung_is_absent_from_both_ladders_when_no_credential_is_configured():
    """The pair, on the same terms as the token's: without it both tests above pass
    against a gateway that offers the vendor's rung with no credential at all."""
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
    assert FLASH_CALL not in from_api
    assert FLASH_CALL not in from_modem


def test_a_ladder_built_without_the_credentials_fails_on_the_signature():
    """The half the behavioural pair above cannot cover: a *third* builder, written next
    year. The pair names the two that exist today, and a census of builders is exactly the
    thing that stops being true silently — so the two parameters whose absence revokes a
    rung carry no default, and a caller that omits one never reaches a probe."""
    import pytest

    with pytest.raises(TypeError, match="ucaller_bearer"):
        build_probes(FakeModem(), tg_token="")
    with pytest.raises(TypeError, match="tg_token"):
        build_probes(FakeModem(), ucaller_bearer="")
