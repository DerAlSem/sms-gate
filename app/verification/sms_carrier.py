"""The modem rung, as the ladder calls it — the one rung this change routes *away from*.

It is here for the reason `tg_carrier` is: `ladder.walk` takes its carriers from whoever
calls it and builds none, so a rung with no carrier is a rung the ladder meets as
`ABSENT`, alerts about, and advances past — to the dearer one. Until this existed that is
exactly what `sms_out` was, in a ladder whose whole subject is when to leave the modem.

Three things are decided here rather than anywhere else.

**The message belongs to the verification, and it is written that way before it is
queued.** The link is not bookkeeping: it is what stops this message's status being
pushed to the application as a message status, and it is what lets the verification take
this message's failure as its own (task 4.27). Written at creation rather than after the
send, because the send is where a message first acquires a status worth pushing.

**An application with no template is `INCAPABLE`, never `DECLINED`.** The gateway
composes no wording of its own — the owner's decision of 18.09.2026 — so an application
with no entry has nothing for a code to arrive in. That is a statement about the
application, not about the subscriber, and a rung that appears to decline everybody is a
rung taken out of the rule for the wrong reason.

**The code is read at the moment of sending rather than handed in.** Same reason as the
paid rung: a verification that ended while the ladder was walking has had its code
destroyed, and a code composed from a value captured earlier would go out to a person
whose verification is already over.

Nothing here is charged and nothing here is bounded by `seconds_left`: composing a row
and putting it on the sender's queue is local work, and the queue is where the modem's
own patience begins. What the rung answers is whether the code was **accepted for
sending**, which is what `CARRIED` means on every other rung too.
"""

from __future__ import annotations

import logging

from app.db import queries
from app.verification import ladder, template
from app.verification.routes import SMS_OUT

logger = logging.getLogger(__name__)


def carrier(verification_id: int, *, app_id: str, modem, operator: str | None):
    """A carrier the ladder can call for this verification.

    `modem` is the sender this gateway already owns, handed in rather than reached for,
    so that a caller with no modem builds no rung instead of building one that fails at
    the queue. `operator` is handed in for the same reason `ladder.walk` requires it: it
    was resolved to read the rule at all, and re-resolving it here would put the person
    at the barrier behind a lookup that has already been paid for once.
    """
    async def carry(phone: str, *, seconds_left: float, rung_id: int) -> ladder.Attempt:
        # `for_app` answers None for both "this application has no entry" and "the
        # stored templates cannot be read", and it alerts on the second itself. Both are
        # the same answer here — there is no wording to put a code in — and the rung must
        # not compose around either.
        wording = template.for_app(app_id)
        if not wording:
            logger.info("verification %d: no verification template is available for %s, "
                        "so the modem rung has nothing for a code to arrive in",
                        verification_id, app_id)
            return ladder.Attempt(
                outcome=ladder.INCAPABLE, route=SMS_OUT,
                reason=f"no verification template is available for {app_id}, and this "
                       f"gateway composes no wording of its own")

        row = await queries.get_verification(verification_id, app_id)
        code = row["code"] if row is not None else None
        if not code:
            # The verification ended under the ladder. Nothing is sent, because the code
            # that would have travelled no longer exists.
            logger.warning("verification %d ended before the modem rung could compose "
                           "its code; nothing was sent", verification_id)
            return ladder.Attempt(
                outcome=ladder.FAILED, route=SMS_OUT,
                reason="the verification ended before its code could be composed")

        text = template.compose(wording, code)
        message_id = await queries.create_message(
            app_id, phone, text, verification_id=verification_id)
        # What the rule answered for this item, recorded at the moment it is true — the
        # sender writes this for its own traffic, and it does not decide the route of a
        # message the ladder placed.
        await queries.record_message_routing(
            message_id, route=SMS_OUT, operator=operator)
        await modem.enqueue(message_id, phone, text, app_id)
        logger.info("verification %d: the modem rung queued message %d",
                    verification_id, message_id)
        # The rung's own reference to what it created. Not a vendor's — there is no
        # vendor on this rung and no cost — but the rung row is where "what did this
        # person's login do" is read from, and a modem rung with nothing in it would be
        # the one rung whose row cannot be followed to anything.
        return ladder.Attempt(outcome=ladder.CARRIED, route=SMS_OUT,
                              vendor_ref=str(message_id))

    return carry
