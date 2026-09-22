"""The ladder's driver: who calls the rungs, in what order, and what it refuses to buy.

The vendor half of the paid ladder was built and proved against the live Gateway before
this existed, and until it existed nothing in the service called either of the vendor's
methods: a rung with no driver is code, not a way out.

The driver owns four things, and each of them is a norm the rungs themselves cannot hold:

**The order is the rule's.** It is handed in rather than read here, because who reads the
rule differs by door, but it is never decided here. An implementation that tries Telegram
first because this module says so satisfies "Telegram first" and defeats the requirement
that makes it changeable during an outage.

**Every gate runs before the first rung is contacted.** `checkSendAbility` is billed when
it confirms, and the fee has no refund path of its own: the vendor's refund is tied to
non-delivery within a `ttl`, and a `ttl` only starts when a message is sent. So a gate
evaluated after a confirmed check refuses something already bought. `gates` is a required
parameter for the same reason — a gate list with a default is a caller that spends money
by forgetting, and the forgetting is invisible at the call site.

**One bound covers the ladder, not each rung.** Otherwise a slow day at the first vendor
doubles the time the application was promised, and the application is holding a person at
a barrier for all of it.

**A rung's silence is not a decline.** A check that never answered may have been confirmed
and charged at the vendor without our learning the `request_id` — a fee that can be
neither spent nor refunded. Counted as its own outcome, because without a count an
unexplained fall in the vendor's balance has no name to look for.

Every rung attempted is its own recorded row, written **before** the carrier is called.
That ordering is the money one: a crash between the vendor's confirmation and our record
would otherwise leave a fee nobody can attribute, and the row is what the carrier updates
the moment a charge is incurred.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Sequence

from app.db import queries
from app.verification import refusals, rule
from app.verification.routes import SMS_OUT

logger = logging.getLogger(__name__)

# What became of one rung. The first is written before the carrier is called; the rest are
# what a carrier answers.
ATTEMPTING = "attempting"    # the row exists, the vendor has not been asked yet
CARRIED = "carried"          # this rung took the verification; the ladder stops
DECLINED = "declined"        # the rung cannot reach this subscriber; nothing charged
REFUSED = "refused"          # the vendor refused *us* — not a decline against the rung
UNCLASSIFIED = "unclassified"  # a refusal we cannot place; advance, and say so out loud
UNANSWERED = "unanswered"    # no answer inside the bound — possibly charged
ABSENT = "absent"            # nothing is configured to carry this rung at all
INCAPABLE = "incapable"      # this rung cannot carry *this* item; not a decline
WITHHELD = "withheld"        # not attempted: a vendor refused *us* and this is the modem
FAILED = "failed"            # it carried and then failed — the ladder does not advance
UNRESOLVED = "unresolved"    # it placed the call and the vendor has not said what became of it

# Three classes, not two, and the third is the expensive one. The ladder advances only
# when a rung **declines to carry** — never when it carried and then failed. A rung that
# accepted has already been paid for on the paid path, and advancing past it would buy the
# same code at the second vendor while the first one's fee cannot be refunded until its
# `ttl` runs out.
_ADVANCING = frozenset({DECLINED, REFUSED, UNCLASSIFIED, UNANSWERED, ABSENT, INCAPABLE})

# The rung took it, was paid for it, and has not yet said what became of it. Its own class
# because neither of the other two fits and both are wrong in an expensive direction.
# Advancing would buy the same code at the second vendor while the first call is already
# placed; failing would tell the application the code is not coming while a phone is about
# to ring. uCaller's `call_status` is `-1` — "информация проверяется (от 1 сек до 1
# минуты)" — for longer than this ladder's whole patience, and a person is standing in
# front of a synchronous request for all of it, so this is the ordinary case on that rung
# rather than the exotic one.
_TAKEN_AND_PENDING = frozenset({UNRESOLVED})

# The routes on which **this gateway transmits over the modem**. `call_in` and `sms_in`
# use the same modem and are deliberately absent: the subscriber originates those, and
# offering someone "text us the code" is not transmitting to them.
_MODEM_ROUTES = frozenset({SMS_OUT})

# The outcomes that leave the verification in flight rather than failing it when they are
# the last thing that happened. A vendor that never answered may yet deliver what it never
# told us it took, and failing it here would tell the application the code is not coming
# while the code is on its way.
_IN_FLIGHT = frozenset({UNANSWERED})


@dataclass(frozen=True)
class Attempt:
    """What one rung did, as the carrier reports it."""

    outcome: str
    reason: str = ""
    vendor_ref: str | None = None
    cost: float | None = None
    route: str = ""


@dataclass(frozen=True)
class Walk:
    """What became of the whole ladder."""

    carried_by: str | None = None
    reason: str = ""
    refused_by: str = ""
    attempts: tuple[Attempt, ...] = field(default=())


# A carrier is given the number, what is left of the ladder's bound, and the id of the row
# already written for this attempt — the row it updates the moment a charge is incurred.
Carrier = Callable[..., Awaitable[Attempt]]

# A gate answers with the reason it refuses, or the empty string. Its own alerting and its
# own counting are its business; what this module guarantees is only that it ran first.
Gate = Callable[[], Awaitable[str]]


async def walk(
    verification_id: int,
    *,
    app_id: str,
    operator: str | None,
    phone: str,
    rungs: Sequence[str],
    gates: Sequence[Gate],
    carriers: dict[str, Carrier],
    bound: float,
) -> Walk:
    """Walk this verification down its rungs and stop at the first that carries it.

    `operator` is required rather than defaulted, and for the reason `gates` is: the
    caller resolved it in order to read the rule at all, and a default would file every
    refusal under "could not be resolved" — silently, and in the one number the rule is
    reviewed by.
    """
    if rule.refuses(list(rungs)):
        # Counted, not just returned. A rule set during an outage outlives the outage,
        # and this is the number that says what it is costing while it does.
        await refusals.record(operator=operator, app_id=app_id, route=rule.REFUSE)
        return Walk(refused_by="rule",
                    reason="the routing rule offers no way out for this number")

    for gate in gates:
        refusal = await gate()
        if refusal:
            # Nothing is contacted and no rung is recorded: there was no attempt, and a
            # row saying otherwise would put a refusal of ours into the count of what the
            # vendors did.
            logger.info("verification %d: refused before any rung, by %s",
                        verification_id, refusal)
            return Walk(refused_by=refusal)

    deadline = time.monotonic() + bound
    attempts: list[Attempt] = []

    for route in rungs:
        seconds_left = deadline - time.monotonic()
        if seconds_left <= 0:
            logger.info("verification %d: the ladder's bound was spent before %s",
                        verification_id, route)
            break

        if route in _MODEM_ROUTES and any(a.outcome == REFUSED for a in attempts):
            # Decided by the owner, 20.09.2026. A vendor refusing *us* — a rotated token,
            # an empty account — is gateway-wide: it will refuse every verification until
            # somebody fixes it, and it refuses them all within the same minute. Carrying
            # them over the modem then turns one vendor's outage into a flood of traffic
            # on the route this capability exists to route *away* from, and for a МегаФон
            # subscriber that route has been refusing — so it would read to the
            # application as a delivery and behave to the person as a silence.
            #
            # A rung the **subscriber** declined is the opposite case and still advances
            # here: that is a statement about one person, not about the gateway.
            #
            # Not alerted again: the refusal that caused this already woke the operator
            # with the vendor named, and a second alert on one event is the noise that
            # buries the first. Recorded rather than skipped, because a rung that
            # vanishes from the row list is a verification whose failure has no reason.
            logger.warning("verification %d: %s was refused by its vendor, so the modem "
                           "rung %s is withheld rather than carrying this verification",
                           verification_id, _refused_by(attempts), route)
            await queries.record_verification_rung(
                verification_id, route=route, outcome=WITHHELD)
            attempts.append(Attempt(
                outcome=WITHHELD, route=route,
                reason="a vendor refused this gateway; the modem does not carry the "
                       "traffic of a vendor outage"))
            continue

        rung_id = await queries.record_verification_rung(
            verification_id, route=route, outcome=ATTEMPTING)

        attempt = await _attempt(route, phone, seconds_left=seconds_left,
                                 rung_id=rung_id, carriers=carriers)
        attempts.append(attempt)
        await queries.set_rung_outcome(
            rung_id, outcome=attempt.outcome, reason=attempt.reason or None,
            vendor_ref=attempt.vendor_ref, cost=attempt.cost)

        if attempt.outcome == CARRIED:
            # `set_carrying_route` rather than `select_route`, and the difference is the
            # whole of this norm: the caller may have claimed the consumer's pick before
            # spending anything — that claim is what stops two selections from both
            # walking — and the rung that carried is then a fact rather than a second
            # choice. `select_route` writes only where the route is still null and would
            # leave the verification naming a rung that declined it.
            outcome = await queries.set_carrying_route(verification_id, app_id, route=route)
            if outcome != "carried":
                # The verification ended or was routed under us while the vendor was
                # being asked. Said out loud rather than swallowed: on a paid rung this
                # is money spent on a verification nobody is waiting for any more.
                logger.warning("verification %d was carried by %s but could not be "
                               "marked as such (%s)", verification_id, route, outcome)
            return Walk(carried_by=route, attempts=tuple(attempts))

        if attempt.outcome in _TAKEN_AND_PENDING:
            # The rung placed it and the answer has not come. The verification keeps its
            # route and its own deadline; what is **not** written is an outcome, because
            # the one thing known here is that nothing is known. Whoever learns the
            # outcome afterwards learns it from the vendor by the reference recorded on
            # this rung's row.
            reason = (f"{route} placed this verification and the vendor had not reported "
                      f"its outcome within the ladder's bound")
            logger.info("verification %d: %s", verification_id, reason)
            return Walk(carried_by=None, reason=reason, attempts=tuple(attempts))

        if attempt.outcome not in _ADVANCING:
            # It carried and then failed. The ladder stops here by the norm above, and
            # the verification fails with the rung that failed named in the reason.
            reason = f"{route} accepted this verification and then failed"
            if attempt.reason:
                reason = f"{reason}: {attempt.reason}"
            await queries.fail_verification(verification_id, reason=reason)
            return Walk(reason=reason, attempts=tuple(attempts))

    if attempts and attempts[-1].outcome in _IN_FLIGHT:
        return Walk(attempts=tuple(attempts),
                    reason="the last rung has not answered yet")

    reason = _why_nothing_carried(attempts)
    await queries.fail_verification(verification_id, reason=reason)
    return Walk(reason=reason, attempts=tuple(attempts))


async def _attempt(
    route: str, phone: str, *, seconds_left: float, rung_id: int,
    carriers: dict[str, Carrier],
) -> Attempt:
    """One rung, or the named absence of one.

    A rung named in the rule that nothing can carry is the one configuration gap that
    costs money rather than traffic: the ladder advances to the dearer rung, every
    verification still succeeds, and the only symptom is the bill. So it is loud, and
    loud on stock settings — `notify_routing_errors` defaults on.
    """
    carrier = carriers.get(route)
    if carrier is None:
        from app.alerting import notify
        logger.warning("verification rung %s is named by the rule and nothing can "
                       "carry it; the ladder is advancing past it", route)
        notify("routing",
               f"the route {route} is named by the routing rule and nothing is "
               f"configured to carry it — the ladder is advancing to the next rung, "
               f"which is the dearer one", dedup_extra=f"absent:{route}")
        return Attempt(outcome=ABSENT, route=route,
                       reason="no carrier is configured for this route")
    try:
        attempt = await carrier(phone, seconds_left=seconds_left, rung_id=rung_id)
    except Exception as e:
        # A carrier that raised told us nothing about what it spent. Deliberately not a
        # decline, for the reason a timeout is not one.
        logger.exception("verification rung %s raised", route)
        return Attempt(outcome=UNANSWERED, route=route, reason=str(e))
    return Attempt(outcome=attempt.outcome, reason=attempt.reason,
                   vendor_ref=attempt.vendor_ref, cost=attempt.cost, route=route)


def _refused_by(attempts: Sequence[Attempt]) -> str:
    """Which rung's vendor refused us, for the line that says why the modem was withheld."""
    return ", ".join(a.route or "?" for a in attempts if a.outcome == REFUSED) or "a rung"


def _why_nothing_carried(attempts: Sequence[Attempt]) -> str:
    """A reason naming the rungs, because "expired" is the one thing that did not happen."""
    if not attempts:
        return "no rung of the ladder could be attempted"
    return "no rung carried this verification: " + ", ".join(
        f"{a.route or '?'} {a.outcome}" for a in attempts)
