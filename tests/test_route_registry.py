"""A route is offered only while its precondition is proven, and the proof has an age.

This is the load-bearing norm of the change, and it is normative because the routes it
adds fail **silently**. An incoming call reaches this modem only while IMS is registered;
if IMS goes off — a reset, a firmware reload, a change at the carrier — `RING` simply stops
arriving. No error, no rejected request, no log line. Every call verification would hang
until it expired and then report "expired", which is indistinguishable from "the person
never called".

So the remedy is not a better handler: a route that cannot prove its precondition is not
offered, the ladder starts one rung lower, and the person verifies another way without ever
learning there was a problem.

Every guard here comes in a pair. A negative assertion on its own — "the rung is absent" —
passes just as well against a registry that offers nothing at all, and has therefore
executed nothing.
"""

import asyncio

import pytest

from app.verification.routes import Proof, Registry, unavailable

PHONE = "+79261234888"


def _probe(holds, *, reason="", measured_at=None, delay=0.0):
    async def probe(phone):
        if delay:
            await asyncio.sleep(delay)
        return Proof(holds=holds, reason=reason, measured_at=measured_at)

    return probe


# Both rungs this change adds need a number for the subscriber to reach, so every
# registry below has one unless the test is about its absence.
GATEWAY = "+79990001122"


def _registry(probes, order=("call_in", "sms_in"), **kw):
    kw.setdefault("gateway_number", GATEWAY)
    return Registry(probes=probes, order=list(order), **kw)


def _offer(registry, phone=PHONE, **kw):
    return asyncio.run(registry.offer(phone, **kw))


# --- the pair: proven and unproven ------------------------------------------------------

def test_a_rung_whose_precondition_holds_is_offered():
    """The positive control, and the reason every negative guard below means anything.

    Two unpaid rungs, deliberately: `sms_in` is a last resort by its own rule further
    down, and a ladder built out of it here would be testing two things at once."""
    reg = _registry({"call_in": _probe(True), "flash_call": _probe(True)},
                    order=("call_in", "flash_call"))
    assert [o.route for o in _offer(reg)] == ["call_in", "flash_call"]


def test_a_rung_whose_precondition_fails_is_absent_and_a_lower_one_is_offered():
    """The silent-death case: IMS is not registered, so `RING` would never arrive. The
    ladder starts one rung lower rather than offering a route that would hang."""
    reg = _registry({"call_in": _probe(False, reason="ims not registered"),
                     "sms_in": _probe(True)})
    assert [o.route for o in _offer(reg)] == ["sms_in"]


def test_a_precondition_that_cannot_be_read_counts_as_unavailable():
    """The failing direction on purpose. An unread precondition is not a satisfied one —
    treating it as satisfied is exactly how the first rung dies quietly."""
    async def raising(phone):
        raise RuntimeError("the modem said nothing")

    reg = _registry({"call_in": raising, "sms_in": _probe(True)})
    assert [o.route for o in _offer(reg)] == ["sms_in"]


# --- the proof has an age ---------------------------------------------------------------

def test_a_proof_older_than_the_maximum_is_refused_exactly_as_a_failed_one():
    """Without a bound, "current evidence" is not defined and the norm decides nothing: a
    reading taken once at boot would satisfy it forever, which is the failure it exists to
    prevent."""
    import time
    stale = time.time() - 3600
    reg = _registry({"call_in": _probe(True, measured_at=stale), "sms_in": _probe(True)},
                    max_proof_age=60.0)
    assert [o.route for o in _offer(reg)] == ["sms_in"]


def test_a_proof_inside_the_maximum_is_accepted():
    """Its positive control: the age rule must not be a rule that refuses everything."""
    import time
    fresh = time.time() - 5
    reg = _registry({"call_in": _probe(True, measured_at=fresh),
                     "flash_call": _probe(True)},
                    order=("call_in", "flash_call"), max_proof_age=60.0)
    assert [o.route for o in _offer(reg)] == ["call_in", "flash_call"]


# --- bounded as a whole, not probe by probe ---------------------------------------------

def test_a_slow_probe_is_unproven_and_does_not_extend_the_promise():
    """Bounded as a whole rather than probe by probe: otherwise a slow day at one vendor
    spends the budget the whole answer was promised in. The abandoned probe counts as
    unproven, because a bound that expired is the commonest way for a precondition to go
    unread."""
    reg = _registry({"call_in": _probe(True, delay=5.0), "sms_in": _probe(True)},
                    probe_timeout=0.05)

    async def timed():
        loop = asyncio.get_event_loop()
        start = loop.time()
        offers = await reg.offer(PHONE)
        return [o.route for o in offers], loop.time() - start

    routes, spent = asyncio.run(timed())
    assert routes == ["sms_in"]
    assert spent < 1.0, f"the answer waited on an abandoned probe: {spent:.2f}s"


def test_two_slow_probes_still_answer_within_the_one_bound():
    """The whole point of bounding the set: two slow probes are not two budgets."""
    reg = _registry({"call_in": _probe(True, delay=5.0), "sms_in": _probe(True, delay=5.0)},
                    probe_timeout=0.05)

    async def timed():
        loop = asyncio.get_event_loop()
        start = loop.time()
        offers = await reg.offer(PHONE)
        return offers, loop.time() - start

    offers, spent = asyncio.run(timed())
    assert offers == []
    assert spent < 1.0, f"two probes spent two budgets: {spent:.2f}s"


def test_an_abandoned_probe_is_counted_rather_than_shrugged_at():
    """A gateway that answers slowly instead of refusing turns the cheap rung off
    silently: every verification still completes, by a dearer route, and the only visible
    symptom is the bill."""
    reg = _registry({"call_in": _probe(True, delay=5.0), "sms_in": _probe(True)},
                    probe_timeout=0.05)
    asyncio.run(reg.offer(PHONE))
    assert reg.abandoned_probes == 1


# --- order and membership are configuration ---------------------------------------------

def test_the_configured_order_is_the_order_offered():
    probes = {"call_in": _probe(True), "sms_in": _probe(True)}
    assert [o.route for o in _offer(_registry(probes, order=("sms_in", "call_in")))] == [
        "sms_in", "call_in"]


def test_a_route_removed_from_the_configuration_is_never_offered():
    """Whatever its precondition would have said."""
    probes = {"call_in": _probe(True), "sms_in": _probe(True)}
    assert [o.route for o in _offer(_registry(probes, order=("sms_in",)))] == ["sms_in"]


def test_a_configured_route_with_no_probe_is_unavailable_rather_than_assumed():
    """Configuration naming a rung nothing can prove is the same position as a rung whose
    proof failed — and the same answer, because "configured" was never evidence."""
    reg = _registry({"sms_in": _probe(True)}, order=("flash_call", "sms_in"))
    assert [o.route for o in _offer(reg)] == ["sms_in"]


def test_reordering_cannot_smuggle_an_unproven_rung_into_the_answer():
    """9.5 — changing the order changes nothing about what a route proves."""
    probes = {"call_in": _probe(False, reason="ims not registered"), "sms_in": _probe(True)}
    for order in (("call_in", "sms_in"), ("sms_in", "call_in")):
        assert [o.route for o in _offer(_registry(probes, order=order))] == ["sms_in"]


# --- what the answer says ---------------------------------------------------------------

def test_an_offer_says_what_the_person_must_do_and_names_no_estate():
    """The bar on disclosure is on identity, not on address: a route that requires the
    person to address the gateway carries what they need to do that, and nothing else."""
    reg = _registry({"call_in": _probe(True)}, order=("call_in",),
                    gateway_number="+79990001122")
    offer = _offer(reg)[0]
    assert "+79990001122" in offer.instruction
    for word in ("SIM", "modem", "ttyUSB", "vendor"):
        assert word.lower() not in offer.instruction.lower()


def test_a_rung_the_person_cannot_be_told_how_to_reach_is_not_offered():
    """Both rungs this change adds need the subscriber to call or text a number, and the
    gateway does not hold its own number anywhere unless it is configured. Offering a rung
    whose instruction would be "call us, we cannot say where" is offering nothing."""
    reg = _registry({"call_in": _probe(True), "sms_in": _probe(True)}, gateway_number="")
    assert _offer(reg) == []


# --- the refusal ------------------------------------------------------------------------

def test_nothing_proving_itself_is_a_refusal_rather_than_an_empty_list():
    """6.7 — refuse in the same answer rather than opening a verification whose only
    possible outcome is to expire."""
    reg = _registry({"call_in": _probe(False), "sms_in": _probe(False)})
    offers = _offer(reg)
    assert offers == []
    assert unavailable(offers) is True


# --- the one rung the subscriber pays for -----------------------------------------------

def test_the_paid_rung_is_not_offered_where_a_cheaper_one_proved_itself():
    """`sms_in` is last on the ladder and it is the only route on which **the subscriber
    pays** — one message at their tariff — and the weakest of them on evidence. Both facts
    point the same way, so it exists to be reached when everything cheaper failed."""
    reg = _registry({"call_in": _probe(True), "sms_in": _probe(True)})
    assert [o.route for o in _offer(reg)] == ["call_in"]


def test_the_paid_rung_is_offered_when_nothing_cheaper_proved_itself():
    """Its positive control, and the whole reason the rung exists at all."""
    reg = _registry({"call_in": _probe(False, reason="ims not registered"),
                     "sms_in": _probe(True)})
    assert [o.route for o in _offer(reg)] == ["sms_in"]


def test_cheaper_means_earlier_in_the_configured_order_and_nothing_else():
    """The rule follows the ladder rather than a second opinion about price: put the paid
    rung first and it is what "cheaper" is measured against."""
    reg = _registry({"call_in": _probe(True), "sms_in": _probe(True)},
                    order=("sms_in", "call_in"))
    assert [o.route for o in _offer(reg)] == ["sms_in", "call_in"]


# --- a rung set aside, and the ladder's own rules reading the membership -----------------

def test_a_rung_set_aside_leaves_the_dearer_one_standing():
    """The trap `without` exists to avoid, and the reason it is a parameter.

    Filtering the *answer* would give nothing here: `offer` drops `sms_in` because
    `call_in` proved itself, and removing `call_in` afterwards empties the list — telling
    a consumer whose call rung just failed that nothing is left, while the rung that
    exists for exactly that moment was dropped for being dearer than a rung no longer on
    the ladder.
    """
    reg = _registry({"call_in": _probe(True), "sms_in": _probe(True)})
    assert [o.route for o in _offer(reg)] == ["call_in"]
    assert [o.route for o in _offer(reg, without={"call_in"})] == ["sms_in"]


def test_a_rung_set_aside_is_never_asked():
    """Not merely absent from the answer: a bounded probe set is the budget the whole
    answer is promised in, and spending it on a rung whose answer is not wanted is how a
    slow vendor turns a cheap rung off."""
    asked = []

    def counting(name, holds):
        async def probe(phone):
            asked.append(name)
            return Proof(holds=holds)
        return probe

    reg = _registry({"call_in": counting("call_in", True),
                     "sms_in": counting("sms_in", True)})
    _offer(reg, without={"call_in"})
    assert asked == ["sms_in"]


def test_setting_nothing_aside_is_the_ladder_unchanged():
    """The positive control: `without` empty must not be a third behaviour."""
    reg = _registry({"call_in": _probe(True), "sms_in": _probe(True)})
    assert [o.route for o in _offer(reg, without=set())] == \
           [o.route for o in _offer(reg)]
