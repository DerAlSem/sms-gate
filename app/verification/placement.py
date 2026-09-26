"""What the gateway does once the consumer has chosen a rung the gateway itself places.

`ladder.walk` takes its order, its gates, its carriers and its bound from whoever calls it,
and decides none of them — because who reads the rule differs by door. This is that
assembly, and it exists as one function rather than inline at the door for the reason
`gates.for_paid_ladder` exists: a door added later must not be able to be a door that
forgot one. Until it was written, `walk` had no production caller at all, and a consumer
could select the Telegram rung, be told to expect a message, and never be sent one.

Four decisions live here, and each of them is a norm rather than a detail.

**The ladder is the rule's, starting at the rung the consumer chose.** The rule answers
what reaches this operator's subscribers and the order in which to try it; the consumer
answers where to start. Rungs *ahead* of the chosen one were offered and not taken, or
were never offered, and walking them would place a route nobody picked. Rungs *behind* it
are the ladder continuing, which is what a ladder is for — and because the ladder settles
inside the one answer, the consumer is never told to watch Telegram and then moved.

**A rung the rule does not name for this operator is still carried, alone.** The owner's
decision of 21.09.2026. The offer already said this rung can prove it will work for this
number, and the rule is a statement about an operator's traffic rather than about a
verification the consumer picked a route for by hand. So it is honoured — and the rule
contributes nothing but the continuation, which here is empty.

**Every gate runs inside `walk`, before the first rung is contacted.** Not here, and not
before the claim: `checkSendAbility` is billed when it confirms and the fee has no refund
path of its own, so a gate evaluated afterwards refuses something already bought. Handing
`walk` an empty gate list and running them here would be the forgetting that
`gates.for_paid_ladder` exists to make impossible.

**A gate's refusal still owes the verification an ending.** `walk` deliberately records no
rung and fails nothing when a gate refuses — there was no attempt, and a row saying
otherwise would put a refusal of *ours* into the count of what the vendors did. But the
caller claimed the route before walking, so a verification left pending after a refusal is
a route claimed with nothing placed: the very defect this module was written to remove,
one door further in.
"""

from __future__ import annotations

import logging

from app.db import queries
from app.settings_store import store
from app.verification import (
    flash_carrier, gates, ladder, rule, sms_carrier, tg_callback, tg_carrier,
    tg_user_carrier, ucaller,
)
from app.verification.routes import FLASH_CALL, SMS_OUT, TG_GATEWAY, TG_USER

logger = logging.getLogger(__name__)

# The rungs on which **this gateway** acts. `call_in` and `sms_in` are deliberately
# absent: on those the subscriber is the one who acts, and there is nothing to place.
#
# 🔴 **`sms_out` was absent here until 21.09.2026, on the reading that the modem sender
# picks its own work up and a ladder placing it would place it twice.** That reading
# described a mechanism nothing had built: `enqueue` had four call sites and not one of
# them belonged to a verification, so an `sms_out`-borne code was never composed at all,
# and `ladder.walk` met the rung as one nothing carries — alerted, advanced past, to the
# dearer one. The ladder was already the other reading in code: `_MODEM_ROUTES` and the
# withholding rule of 20.09.2026 are a branch about the modem rung standing **inside** a
# ladder, and under the old reading they were unreachable. So the modem is placed here
# like every other rung the gateway acts on, and nothing else places it.
#
# `tg_user` joined on 25.09.2026 (SG-32): the gateway writes from an application's own
# Telegram account, so it is a rung the gateway acts on like the others.
PLACED_HERE = frozenset({TG_GATEWAY, FLASH_CALL, SMS_OUT, TG_USER})

# Who refused, when the refusal is the rule itself rather than a gate. It travels the same
# channel a gate's refusal travels — `Walk.refused_by`, a 422 at the door and an ending on
# the verification — because to a consumer the two are the same event: nothing was placed,
# nothing was charged, and this is not a vendor failing.
_THE_RULE = "the routing rule"


def places_here(route: str) -> bool:
    """Whether selecting this rung is something the gateway has to go and do.

    An unknown route answers no, which is the failing direction: a route named in the rule
    before anything can place it must not be walked into a carrier that does not exist.
    """
    return route in PLACED_HERE


def carriers_for(
    verification_id: int, *, app_id: str, modem, operator: str | None,
) -> dict[str, ladder.Carrier]:
    """The carriers that exist for this verification, right now.

    A rung whose credential is blank is **absent from this map** rather than present and
    failing at the vendor: that is the difference between a configuration gap the ladder
    advances past loudly and a fee spent to discover it. In practice the registry refuses
    such a rung at the offer before it ever reaches here — the probe holds on the token —
    and this is the second half of the same guarantee, for the case where the token goes
    away between the offer and the selection.

    `flash_call` was absent here until 22.09.2026 for want of an account and an adapter,
    and is now present on exactly the same terms as the Telegram rung: present when the
    credential is held, absent when it is blank. Absent still means the ladder advances
    past it loudly on stock settings, which is the one configuration gap that costs money
    rather than traffic.

    **`modem` and `operator` have no defaults**, for the reason `callback_url` lost its
    one on 21.09.2026: a caller that forgets the modem builds a map with no modem rung in
    it, and the ladder then says out loud that nothing carries `sms_out` — loud, and
    wrong. A parameter every caller has to decide has no right to a default.
    """
    carriers: dict[str, ladder.Carrier] = {}
    if modem is not None:
        # No credential to hold and no vendor to be out of credit with: what this rung
        # needs is the sender, and a gateway with no modem has no `sms_out`.
        carriers[SMS_OUT] = sms_carrier.carrier(
            verification_id, app_id=app_id, modem=modem, operator=operator)
    token = store.tg_gateway_token
    if token:
        callback_url = tg_callback.url_for(store.tg_gateway_callback_base)
        if not callback_url:
            # Not a refusal: the rung carries, the person gets their code, and a
            # verification with no report still ends on its own deadline. What is lost is
            # everything the vendor would have told us afterwards — `expired` failing the
            # verification with that reason, and the refund being recorded rather than
            # assumed — so it is said here, once per assembly, rather than on every send
            # or not at all.
            logger.warning(
                "tg_gateway_callback_base is blank, so the Telegram Gateway is not told "
                "where to report: this verification's message will be sent and nothing "
                "about its delivery, expiry or refund will ever come back")
        carriers[TG_GATEWAY] = tg_carrier.carrier(
            verification_id, app_id=app_id, token=token, callback_url=callback_url,
            sender_username=store.tg_gateway_sender_username)
    bearer = ucaller.configured_bearer()
    if bearer:
        # No callback and no reporting address to forget: this vendor tells us what became
        # of a call only when we ask, which is why the carrier waits and why waiting is
        # bounded there rather than here.
        carriers[FLASH_CALL] = flash_carrier.carrier(
            verification_id, app_id=app_id, bearer=bearer)
    unwired = tg_user_carrier.unwired_reason(app_id)
    if unwired is None:
        carriers[TG_USER] = tg_user_carrier.carrier(verification_id, app_id=app_id)
    elif unwired:
        # Absent rather than present and refusing, which is task 3.6's invariant on the
        # messengers branch: the carrier claims the account's allowance before it asks
        # Telegram anything, so a rung wired without its keys or its session would spend
        # a live account's hourly quota to say `unavailable`. An application with no
        # account at all is the ordinary case and says nothing.
        logger.warning("tg_user route is configured but not wired: %s", unwired)
    return carriers


def ladder_from(route: str, operator: str | None) -> list[str]:
    """The rungs to walk: the rule's answer for this operator, from `route` onwards.

    Read per call, because a change to the rule must take effect without a restart.
    """
    named = rule.route_for(operator)
    if route in named:
        return named[named.index(route):]
    # The rule does not name this rung for this operator. Honoured alone, by the owner's
    # decision of 21.09.2026, and alone is the whole of it: there is no continuation to
    # borrow from an entry that does not mention where we started.
    logger.info("verification rung %s is not named by the routing rule for %s (%s); it "
                "is carried alone", route, operator or "an unresolved operator",
                ", ".join(named) or "no rungs")
    return [route]


async def place(
    verification_id: int, *, app_id: str, operator: str | None, phone: str, route: str,
    modem,
) -> ladder.Walk:
    """Walk the ladder for a rung the consumer selected, and leave nothing in flight.

    The route is expected to be claimed already: the claim is what makes two simultaneous
    selections unable to both buy the same code, and it has to happen before any money is
    spent rather than after.
    """
    # One reading, handed to both: the gates that are asked follow the rungs of the walk,
    # so computing the ladder twice would let the two answers drift apart.
    try:
        rungs = ladder_from(route, operator)
    except rule.UnreadableRule as exc:
        # Refused, never read as an empty rule — the reading the other two readers of this
        # rule refuse in the same words (`app/modem/manager.py`, `app/verification/
        # probes.py`). Read as empty, a diverted operator's traffic goes straight back to
        # the route that is rejecting it, and here that route is one somebody pays for.
        #
        # Carrying the selected rung alone is not the answer either, tempting as it is:
        # "carried alone" is what the norm says about a rung **the rule does not name**,
        # and an unreadable rule has not said that or anything else. The alert was raised
        # by `route_for` itself, once per read; what is owed here is the refusal — and the
        # ending below, because the route is claimed by now and a selection left pending
        # with nothing placed is exactly what this requirement forbids in its first line.
        walk = ladder.Walk(
            refused_by=_THE_RULE,
            reason=f"the stored routing rule cannot be read, so the ladder this "
                   f"selection walks cannot be named: {exc}",
        )
    else:
        walk = await ladder.walk(
            verification_id,
            app_id=app_id,
            operator=operator,
            phone=phone,
            rungs=rungs,
            gates=gates.for_paid_ladder(app_id, phone, rungs),
            carriers=carriers_for(verification_id, app_id=app_id, modem=modem,
                                  operator=operator),
            bound=store.verification_ladder_bound,
        )
    if walk.refused_by and walk.carried_by is None:
        # Nothing was placed and nothing will be. Ended here rather than left to the clock,
        # because "expired" told to a consumer whose request was refused before any vendor
        # was contacted reports the one thing that did not happen.
        reason = walk.reason or f"refused before any rung, by {walk.refused_by}"
        await queries.fail_verification(verification_id, reason=reason)
        logger.info("verification %d: %s was selected and refused by %s; nothing was "
                    "placed", verification_id, route, walk.refused_by)
    return walk
