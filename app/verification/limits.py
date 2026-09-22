"""The per-number limits, held here so the vendor never has to discover them.

uCaller allows four authorisations per number per minute with at least fifteen seconds
between them and thirty per number per day. A number that exceeds them is blocked at the
vendor **for ten hours** — which is the whole argument for this file. Being told to wait
fifteen seconds costs a person fifteen seconds; being blocked at the vendor costs them a
working day in which they cannot log in at all, by any route, and nothing we do
afterwards shortens it.

Three decisions, each of which is a norm rather than a convenience:

**The limits bound the ladder, not the call rung.** Telegram's reference publishes no
rate limits at all, and that is the absence of a statement rather than a statement of
absence. A rung whose block conditions are unpublished is the one to be more careful
with, not less — so a Telegram attempt counts towards the same ceilings.

**The window rolls.** This database stores naive UTC and the vendor is Russian, so a
calendar day read in the wrong zone resets three hours early — and in those three hours
the gateway confidently places the call that costs the subscriber ten hours. A rolling
window is the stricter reading of any calendar day, everywhere, which is exactly what the
norm asks for when ours and the vendor's cannot be reconciled.

**The numbers are settings.** They are the vendor's numbers rather than ours, and a
vendor may change them without asking.

🔴 **The allowance is decided and taken in one act.** Not a gate that reads and a row
written afterwards: that is how two verifications for one number — which this capability
explicitly permits — both read an empty history, both pass, and both reach a vendor inside
the fifteen-second gap. The claim on the route does not close it, being keyed on the
verification. So the enforcement lives where the row is written, as a single conditional
statement, and a caller that forgets a gate list cannot spend the subscriber's ten hours by
forgetting. Found by the critic circle of 22.09.2026 (task 4.62).

The refusal is a reason, not an exception: a refusal here is emphatically not a vendor
failure — nothing was placed. What it costs is a re-read of the same history, done **after**
the decision and only to name it: which of the three refused is a question for the person
reading the answer, never for the claim.
"""

from __future__ import annotations

import logging

from app.db import queries
from app.settings_store import store

logger = logging.getLogger(__name__)


async def claim(verification_id: int, *, route: str, phone: str,
                outcome: str) -> tuple[int | None, str]:
    """Take this number's paid allowance for one rung, and record that rung.

    Answers the id of the row written and the empty string, or `None` and the reason it was
    refused. One statement decides and records; the reason is composed afterwards, from the
    same history, because naming *which* of the three limits refused is for whoever reads
    the answer and never for the decision.

    The vendor's numbers are read here rather than in the query: they are the vendor's and
    not ours, and a vendor may change them without asking.
    """
    window_hours = store.verification_day_window_hours
    gap = store.verification_min_gap_seconds
    rung_id = await queries.claim_paid_rung(
        verification_id, route=route, phone=phone, outcome=outcome,
        gap_seconds=gap, per_minute=store.verification_per_minute,
        per_day=store.verification_per_day, window_seconds=window_hours * 3600)
    if rung_id is not None:
        return rung_id, ""
    return None, await _why(phone, verification_id, gap=gap, window_hours=window_hours)


async def _why(phone: str, verification_id: int, *, gap: int,
               window_hours: int) -> str:
    """Which of the three refused, said in the words the refused caller is given.

    Read after the fact and never before it. A history that has moved on between the claim
    and this read can only have moved in one direction — another attempt on this number —
    so the worst this can do is name a stricter reason than the one that actually refused,
    and it can never name none: the fallback says so rather than inventing a limit.
    """
    ages = await queries.paid_attempts_for_number(
        phone, within_seconds=window_hours * 3600,
        excluding_verification=verification_id)

    if ages and ages[0] < gap:
        wait = gap - ages[0]
        logger.info("%s asked again %ds after the last paid attempt; %ds to wait",
                    phone, ages[0], wait)
        return f"too_soon: wait {wait}s before asking again"

    in_a_minute = sum(1 for age in ages if age < 60)
    if in_a_minute >= store.verification_per_minute:
        logger.info("%s has had %d paid attempts in the last minute", phone, in_a_minute)
        return (f"per_minute_ceiling: {in_a_minute} paid attempts on this number in "
                f"the last minute")

    if len(ages) >= store.verification_per_day:
        logger.info("%s has had %d paid attempts in the last %dh", phone, len(ages),
                    window_hours)
        return (f"per_day_ceiling: {len(ages)} paid attempts on this number in the "
                f"last {window_hours}h")

    logger.info("%s was refused its paid allowance and the history no longer says which "
                "limit did it", phone)
    return "per_number_limits: this number has no paid attempt left in its allowance"
