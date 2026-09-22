"""The gates that stand between a verification and money.

The ladder guarantees only that these run **before the first rung is contacted**; what
each of them decides is its own. They answer with the reason they refuse, or with the
empty string, because a refusal here is not an exception and emphatically not a vendor
failure: nothing was placed, nothing was charged, and nothing is owed a retry.

Three questions live here, and keeping them apart is the point:

**Has this gateway decided not to contact this number at all?** The blacklist, which is the
one state that shuts every route to a person at once. It is asked here rather than only at
the door that opens a verification, because a number can be blocked **while a verification is
already open** — by a delivery report crossing the threshold on another message, or by an
operator's hand — and the selection door never asks again. That window is as wide as the
verification's own deadline, and inside it the ladder places a paid call to somebody this
gateway has decided not to write to.

**May this application spend at all?** An entitlement recorded against the application,
off until an operator says otherwise. It is deliberately *not* part of the routing rule:
the rule answers what reaches a subscriber and stays keyed on the operator alone, while
this answers who is allowed to pay for it, and the two change at different times. Three
of the four applications on this gateway send no codes at all, so a default of on would
mean the first mistake in any of them is billed rather than logged.

**Has the gateway spent enough for now?** A ceiling on paid items per rolling hour and
per rolling day, counted across every number, every application and **both paid routes
together**. The vendor's own limits do not provide this — they are per number, and a loop
over five hundred numbers violates none of them while spending four hundred roubles. Nor
does a balance floor, which reports money that has already gone.

Neither refusal may be carried over `sms_out` instead. For a МегаФон subscriber that is
the route that has been refusing, so the fallback would read to the application as a
delivery and behave to the person as a silence.
"""

from __future__ import annotations

import logging

from app.db import queries
from app.settings_store import store
from app.verification import limits, routes

logger = logging.getLogger(__name__)


def blacklist_gate(phone: str):
    """A gate that refuses a number this gateway holds blocked.

    Placed **in the gate list** rather than at the selection door, and that is the whole of
    the design: the invariant belongs on the boundary where state changes irreversibly —
    the moment before anything is contacted — and not on a census of the doors that reach
    it. A census is never complete and goes stale in silence, while `for_paid_ladder` exists
    precisely so that a door added later cannot be a door that forgot one.

    First in the order, ahead of the entitlement, because it is the strongest of the three
    statements and the one about the person rather than about us: an application that may
    not spend is a configuration, a ceiling reached is a busy day, and a blocked number is a
    decision already taken not to contact this human being at all.

    It reads the same `bad_numbers` state the modem sender reads before a retry and the door
    reads before opening a verification — one fact, asked wherever spending is about to
    happen, rather than three copies of it.
    """
    async def gate() -> str:
        if await queries.is_phone_blocked(phone):
            logger.info("%s is held blocked and a paid rung was about to be walked for it",
                        phone)
            return (f"blacklist: {phone} is held blocked by this gateway and no route "
                    f"carries traffic to it")
        return ""

    return gate


def entitlement_gate(app_id: str):
    """A gate that refuses an application not entitled to spend on a paid route."""
    async def gate() -> str:
        row = await queries.get_app(app_id)
        if row is None:
            logger.info("a paid verification was asked for by %s, which is not an "
                        "application this gateway knows", app_id)
            return (f"entitlement: {app_id} is not an application of this gateway and "
                    f"holds no entitlement to spend")
        if not row["is_active"]:
            # The older switch, and still the stronger one. An application an operator
            # has deactivated must not go on buying verifications because a second switch
            # was left on from before.
            logger.info("%s is not active and may not spend", app_id)
            return f"entitlement: {app_id} is not active and may not spend"
        if not row["may_spend"]:
            logger.info("%s holds no entitlement to spend on a paid route", app_id)
            return (f"entitlement: {app_id} does not hold the entitlement to spend on a "
                    f"paid route")
        return ""

    return gate


def ceiling_gate():
    """A gate that refuses once this gateway has spent enough for the hour or the day.

    Counted over the rungs of **both** paid routes together, because the ladder advances
    from one to the other by design: a ceiling held per vendor would let a run of
    verifications spend twice the intended amount without either half of it reaching its
    own limit. What is being bounded is the bill, and the bill is one.

    Loud on the first refusal within the alert dedup window, and loud on stock settings —
    a ceiling that refuses silently presents as a gateway that has simply stopped
    verifying anyone.
    """
    async def gate() -> str:
        hour_ceiling = store.verification_paid_per_hour
        in_the_hour = await queries.paid_attempts_since(3600)
        if in_the_hour >= hour_ceiling:
            return _refuse("hour", in_the_hour, hour_ceiling)

        day_hours = store.verification_day_window_hours
        day_ceiling = store.verification_paid_per_day
        in_the_day = await queries.paid_attempts_since(day_hours * 3600)
        if in_the_day >= day_ceiling:
            return _refuse(f"{day_hours}h", in_the_day, day_ceiling)

        return ""

    return gate


def _refuse(window: str, seen: int, ceiling: int) -> str:
    """One refusal by the ceiling: said in the log, said to the operator, and returned.

    The alert names the window rather than only the fact, because the two windows mean
    different things to whoever is woken by it: an hourly ceiling reached is almost always
    a loop, and a daily one is almost always a busy day that has outgrown its setting.
    """
    from app.alerting import notify

    text = (f"the spend ceiling refused a paid verification: {seen} paid rungs have been "
            f"attempted in the last {window}, at or above the configured ceiling of "
            f"{ceiling}. Nothing was placed and nothing was charged; verifications on "
            f"the paid ladder are being refused until the window rolls past them")
    logger.warning("the spend ceiling refused: %d paid rungs in the last %s, ceiling %d",
                   seen, window, ceiling)
    notify("routing", text, dedup_extra=f"spend_ceiling:{window}")
    return (f"spend_ceiling: {seen} paid rungs attempted in the last {window}, at or "
            f"above the ceiling of {ceiling}")


def for_paid_ladder(app_id: str, phone: str, rungs):
    """Every gate a walk down the ladder has to pass, in the order they are run.

    🔴 `rungs` decides which of them are asked, and it has no default. Three of these four
    are questions about money, and a walk with no paid rung in it spends none: asking them
    there refuses a *free* send in the name of money that was never going to move. That is
    not a corner — `may_spend` ships off for every application and the shipped rule sends
    every operator it does not name to `sms_out` alone, so on stock settings the money
    gates stand in front of the free route and nothing else, and the reason the caller is
    given names a paid route the walk never contained. Found by the critic circle of
    22.09.2026, by both critics independently (task 4.61).

    The blacklist is asked whatever the rungs are: it is the one that is not about degree
    or price at all — a number held blocked is not being carried by anything, free or
    paid, for any application.

    Assembled here rather than at each door, so that a door added later cannot be a door
    that forgot one. The order is cheapest-question-first and it decides only which reason
    a refused caller is given: entitlement is a fact about the application and never
    changes under load; the ceiling is about this gateway as a whole; the per-number
    limits are about this one subscriber. The blacklist comes before all of them because it
    is the one that is not about degree at all — a number held blocked is not being carried
    by anything, at any price, for any application. All four read the database and none of
    them contacts a vendor.

    ⚠️ A list with a default would be a caller that spends money by forgetting, and the
    forgetting is invisible at the call site — which is why `ladder.walk` takes `gates`
    as a required parameter and why this exists to fill it.
    """
    if not any(r in routes.PAID_ROUTES for r in rungs):
        return (blacklist_gate(phone),)
    return (blacklist_gate(phone), entitlement_gate(app_id), ceiling_gate(),
            limits.per_number_gate(phone))
