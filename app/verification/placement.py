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
from app.verification import gates, ladder, rule, tg_carrier
from app.verification.routes import TG_GATEWAY

logger = logging.getLogger(__name__)

# The rungs on which **this gateway** acts. `call_in` and `sms_in` are deliberately absent:
# on those the subscriber is the one who acts, and there is nothing to place. `sms_out` is
# absent for a different reason — the modem sender carries it, on its own queue, and a
# ladder that placed it here would place it twice.
PLACED_HERE = frozenset({TG_GATEWAY})


def places_here(route: str) -> bool:
    """Whether selecting this rung is something the gateway has to go and do.

    An unknown route answers no, which is the failing direction: a route named in the rule
    before anything can place it must not be walked into a carrier that does not exist.
    """
    return route in PLACED_HERE


def carriers_for(verification_id: int, *, app_id: str) -> dict[str, ladder.Carrier]:
    """The carriers that exist for this verification, right now.

    A rung whose credential is blank is **absent from this map** rather than present and
    failing at the vendor: that is the difference between a configuration gap the ladder
    advances past loudly and a fee spent to discover it. In practice the registry refuses
    such a rung at the offer before it ever reaches here — the probe holds on the token —
    and this is the second half of the same guarantee, for the case where the token goes
    away between the offer and the selection.

    `flash_call` is absent because uCaller has no account yet (task 1.1) and therefore no
    adapter (4.17). That is not a hole: a rung the rule names and nothing carries is not
    attempted, is alerted about on stock settings, and the ladder advances past it — which
    is the one configuration gap that costs money rather than traffic, and the reason it is
    loud.
    """
    carriers: dict[str, ladder.Carrier] = {}
    token = store.tg_gateway_token
    if token:
        carriers[TG_GATEWAY] = tg_carrier.carrier(
            verification_id, app_id=app_id, token=token)
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
) -> ladder.Walk:
    """Walk the ladder for a rung the consumer selected, and leave nothing in flight.

    The route is expected to be claimed already: the claim is what makes two simultaneous
    selections unable to both buy the same code, and it has to happen before any money is
    spent rather than after.
    """
    walk = await ladder.walk(
        verification_id,
        app_id=app_id,
        operator=operator,
        phone=phone,
        rungs=ladder_from(route, operator),
        gates=gates.for_paid_ladder(app_id, phone),
        carriers=carriers_for(verification_id, app_id=app_id),
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
