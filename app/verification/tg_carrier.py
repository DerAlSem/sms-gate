"""The Telegram Gateway rung, as the ladder calls it.

The adapter below this knows the wire; this knows the money. Three orderings are the
whole of it, and all three are unforgiving:

1. **The rung is refused before it is bought, never after.** The vendor's own floor is a
   `ttl` of thirty seconds, and inflating a shorter one to reach it would hand the vendor
   a message that outlives the verification it belongs to — while the automatic refund on
   non-delivery is tied to that same `ttl`. A verification with too little life left is
   therefore not bought at all, and that is **not** a decline: a decline is a statement
   about the subscriber, and a rung that appears to decline everyone is a rung that will
   be taken out of the rule for the wrong reason.

2. **The charge is recorded before the send is attempted.** A confirmed `checkSendAbility`
   is a fee already incurred. If the process dies between the vendor's confirmation and
   our record, the fee exists and belongs to nothing — and the only symptom is a balance
   that drifts. The row the ladder wrote on its way in is updated here with the
   `request_id` and the cost, and only then is the message sent.

3. **A send that fails after the fee does not advance the ladder.** The rung carried and
   then failed, which is a different thing from declining to carry, and buying the same
   code at the second vendor while the first fee is unrefundable until its `ttl` expires
   is the one mistake this ladder exists to avoid.

What the vendor says about our credentials is loud, and says *which* vendor: with two paid
rungs, "the vendor is out of credit" is the question the operator has to answer before
they can act, and answering it by reading a log is the difference between a two-minute
top-up and an outage.
"""

from __future__ import annotations

import logging

from app.db import queries
from app.verification import ladder, tg_gateway

logger = logging.getLogger(__name__)

VENDOR = "Telegram Gateway"

# How an ability check's kind maps onto what the ladder does next. `ABLE` is absent on
# purpose: it is the only one that goes on to spend, and it is handled in code rather than
# in a table so that the send cannot be reached by a lookup that fell through.
_OUTCOME = {
    tg_gateway.DECLINED: ladder.DECLINED,
    tg_gateway.REFUSED: ladder.REFUSED,
    tg_gateway.UNCLASSIFIED: ladder.UNCLASSIFIED,
    tg_gateway.UNANSWERED: ladder.UNANSWERED,
}

# The two kinds nobody would otherwise find out about. A refusal of *us* is a credential
# or a balance and stops the rung working for everyone; an unplaceable refusal read as a
# decline would advance every verification to the dearer rung and tell nobody.
_LOUD = frozenset({tg_gateway.REFUSED, tg_gateway.UNCLASSIFIED})


def carrier(
    verification_id: int, *, app_id: str, token: str, callback_url: str = "",
    sender_username: str = "",
):
    """A carrier the ladder can call for this verification.

    The code is read from the store at the moment of sending rather than handed in, so
    that a verification which ended while the vendor was being asked cannot have its code
    sent afterwards — the store nulls the code the moment a verification stops being
    confirmable.
    """
    async def carry(phone: str, *, seconds_left: float, rung_id: int) -> ladder.Attempt:
        ttl = await queries.verification_seconds_left(verification_id)
        if ttl < tg_gateway.TTL_MIN:
            logger.info("verification %d has %ds left, below the vendor's %ds floor; "
                        "the Telegram rung is not bought for it",
                        verification_id, ttl, tg_gateway.TTL_MIN)
            return ladder.Attempt(
                outcome=ladder.INCAPABLE,
                reason=f"only {ttl}s of this verification's life remain, below the "
                       f"vendor's {tg_gateway.TTL_MIN}s floor")

        ability = await tg_gateway.check_send_ability(
            phone, token=token, timeout=max(0.1, seconds_left))

        if ability.kind in _LOUD:
            _alert(ability)
        if ability.kind != tg_gateway.ABLE:
            return ladder.Attempt(
                outcome=_OUTCOME.get(ability.kind, ladder.UNANSWERED),
                reason=ability.error)

        # Confirmed: one fee is now incurred, and exactly one send is owed for it.
        cost = ability.status.request_cost if ability.status else None
        await queries.set_rung_outcome(
            rung_id, outcome=ladder.ATTEMPTING, vendor_ref=ability.request_id, cost=cost,
            reason="the ability check confirmed and was charged")

        row = await queries.get_verification(verification_id, app_id)
        code = row["code"] if row is not None else None
        if not code:
            # The verification ended under us between the check and the send. The fee is
            # spent and stays recorded; nothing is sent, because the code that would have
            # travelled no longer exists.
            logger.warning("verification %d ended between the ability check and the "
                           "send; the fee stands and nothing was sent", verification_id)
            return ladder.Attempt(
                outcome=ladder.FAILED, vendor_ref=ability.request_id, cost=cost,
                reason="the verification ended before its code could be sent")

        sent = await tg_gateway.send_verification_message(
            phone, code=code, ttl=ttl, token=token, request_id=ability.request_id,
            callback_url=callback_url, sender_username=sender_username,
            timeout=max(0.1, seconds_left))

        if not sent.ok:
            logger.warning("verification %d: the Telegram send refused after a charged "
                           "ability check (%s)", verification_id, sent.error)
            return ladder.Attempt(outcome=ladder.FAILED, vendor_ref=ability.request_id,
                                  cost=cost, reason=sent.error)

        return ladder.Attempt(outcome=ladder.CARRIED, vendor_ref=ability.request_id,
                              cost=cost)

    return carry


def _alert(ability) -> None:
    from app.alerting import notify

    if ability.kind == tg_gateway.REFUSED:
        text = (f"{VENDOR} refused this gateway rather than the subscriber "
                f"({ability.error}) — the rung is not working for anyone until it is "
                f"fixed, and the ladder is spending on the rung below it")
    else:
        text = (f"{VENDOR} refused with an error this gateway cannot place "
                f"({ability.error}); the ladder advanced as it would past a decline")
    notify("routing", text, dedup_extra=f"tg_gateway:{ability.error}")
