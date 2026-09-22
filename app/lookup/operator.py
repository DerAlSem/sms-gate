import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.settings_store import store
from app.db import queries
from app.lookup import voxlink

logger = logging.getLogger(__name__)


def is_stale(checked_at: str | None, ttl_days: int, now: datetime) -> bool:
    """True if a cached number row should be re-looked-up. Missing/unparseable
    timestamps count as stale. `checked_at` is sqlite's naive-UTC string."""
    if not checked_at:
        return True
    try:
        ts = datetime.fromisoformat(checked_at)
    except (TypeError, ValueError):
        return True
    return (now - ts) > timedelta(days=ttl_days)


async def record_operator(phone: str) -> None:
    """Resolve and cache this number's operator/region via voxlink (MNP-aware,
    per-number). Pure enrichment — never blocks the send. A fresh cache hit is
    skipped; a stale row is refreshed; a failed/None lookup keeps the existing
    row (no downgrade)."""
    if not phone.startswith("+7"):
        return  # operator/region lookup (voxlink) is RF-only; see docs
    if not store.voxlink_enabled:
        return
    # naive UTC, to match sqlite's CURRENT_TIMESTAMP (always UTC, no tz)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cached = await queries.get_number_operator(phone)
    if cached is not None and not is_stale(
        cached["checked_at"], store.voxlink_cache_ttl_days, now
    ):
        return
    msisdn10 = phone[2:]
    info = await voxlink.lookup(msisdn10, store.voxlink_url, store.voxlink_timeout)
    if info is None:
        if cached is None:
            logger.warning("voxlink lookup failed for %s, no cache yet", phone)
        return
    await queries.save_number_operator(phone, info.operator, info.region)


async def cached_operator(phone: str) -> str | None:
    """The operator already on record, or None — including when the row names nobody.

    A row that exists and holds a NULL operator is the absence, not the presence:
    `save_number_operator` accepts `None`, and treating "there is a row" as "there is an
    operator" would route the number on nobody, invisibly.
    """
    row = await queries.get_number_operator(phone)
    if row is None:
        return None
    named = (row["operator"] or "").strip()
    return named or None


async def resolve_within_bound(phone: str) -> str | None:
    """This number's operator, resolved under the routing bound. None if it will not be.

    🔴 **The waiting lives here and nowhere else, and that placement is the norm rather
    than an optimisation.** An application's answer must not wait for enrichment — an
    unreachable resolver as a slow API is what this replaced. But since the route is read
    from the operator, an empty cache is not the same fact as an unresolvable number:
    routed on an empty cache, the first message ever addressed to a diverted operator's
    subscriber takes the rule's `?` entry and goes out over the modem — the route that
    operator has been rejecting, on exactly the message the rule exists for. So `?` means
    "the lookup did not answer" and never "the lookup has not been asked".

    **A stale row is used as it stands.** It still names an operator; refreshing it
    changes no decision this rule can make — numbers move between operators on a scale of
    years and the rule is reviewed on a scale of months — and whoever is behind this call
    pays for the refresh: the next message in a single-file queue, or a person standing at
    a barrier.

    **Shared by the sender and the verification door on purpose.** Measured 22.09.2026,
    task 6.4: the door had its own unconditional `await record_operator(...)`, so a stale
    row held `POST /verifications` for 3.01 seconds and the budget being spent was
    `voxlink_timeout` — the patience of one HTTP call — rather than the routing bound.
    Two callers that must make the same decision are one function, or they are one
    function and a copy that falls behind.

    Nothing here fails anything. The bound expiring, the lookup raising and the lookup
    answering with nobody are one outcome to every caller: the unknown-operator entry
    answers, and what it answers with is the owner's.
    """
    named = await cached_operator(phone)
    if named is not None:
        return named

    bound = store.operator_lookup_bound
    try:
        await asyncio.wait_for(record_operator(phone), timeout=bound)
    except asyncio.TimeoutError:
        # Abandoned, not cancelled in spirit: the lookup is still worth having for the
        # next caller asking about this number, but this one is not waiting any longer.
        logger.info("operator lookup for %s did not answer within %.2fs; routing by the "
                    "rule's unknown-operator entry", phone, bound)
        return None
    except Exception:
        logger.exception("operator lookup for %s failed; routing by the rule's "
                         "unknown-operator entry", phone)
        return None
    return await cached_operator(phone)
