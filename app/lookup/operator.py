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
