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

The refusal is a reason, not an exception: the ladder's gates answer with the reason they
refuse, and a refusal here is emphatically not a vendor failure — nothing was placed.
"""

from __future__ import annotations

import logging

from app.db import queries
from app.settings_store import store

logger = logging.getLogger(__name__)


def per_number_gate(phone: str):
    """A gate the ladder can run before it contacts anything, for this number."""
    async def gate() -> str:
        window_hours = store.verification_day_window_hours
        ages = await queries.paid_attempts_for_number(
            phone, within_seconds=window_hours * 3600)
        if not ages:
            return ""

        gap = store.verification_min_gap_seconds
        if ages[0] < gap:
            wait = gap - ages[0]
            logger.info("%s asked again %ds after the last paid attempt; %ds to wait",
                        phone, ages[0], wait)
            return f"too_soon: wait {wait}s before asking again"

        in_a_minute = sum(1 for age in ages if age < 60)
        if in_a_minute >= store.verification_per_minute:
            logger.info("%s has had %d paid attempts in the last minute", phone,
                        in_a_minute)
            return (f"per_minute_ceiling: {in_a_minute} paid attempts on this number in "
                    f"the last minute")

        if len(ages) >= store.verification_per_day:
            logger.info("%s has had %d paid attempts in the last %dh", phone, len(ages),
                        window_hours)
            return (f"per_day_ceiling: {len(ages)} paid attempts on this number in the "
                    f"last {window_hours}h")

        return ""

    return gate
