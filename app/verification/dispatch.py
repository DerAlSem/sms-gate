"""Telling the owning application how a verification ended.

The symmetric counterpart of `app/modem/delivery_dispatch.py`, and deliberately built the
same way: the route is read from `delivery_dispatch` by application, a consumer with no
route configured is silent by design, and the poll stays authoritative so a lost push
self-heals.

What is different is the payload and the reason for it. A verification push says
`"object": "verification"` because a receiver that cannot tell a verification id from a
message id will eventually mark the wrong thing delivered — the two id spaces overlap from
the first row of each table. And a confirmation names the **method** that proved it: the
methods are not equally strong, a caller number is asserted by the network and can be
forged, and an application whose stakes do not tolerate the weakest must be able to see
what it got rather than assume the strongest.

The code is never in here. Not in the payload, not in the reason, not in the log line.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.db import queries
from app.modem.delivery_dispatch import deliver, find_route
from app.settings_store import store

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


async def push_verification(
    verification_id: int, app_id: str, status: str, *,
    method: str | None = None, reason: str | None = None,
) -> bool:
    """One push. True only if a route matched and the delivery succeeded; never raises."""
    try:
        route = find_route(app_id)
        if route is None:
            return False
        payload = {
            "object": "verification",
            "id": verification_id,
            "status": status,
            "method": method,
            "reason": reason,
            "occurred_at": _utc_now(),
        }
        ok, why = await deliver(route, payload)
        logger.info("verification dispatch: app=%s id=%d status=%s ok=%s",
                    app_id, verification_id, status, ok)
        return ok
    except Exception:
        logger.exception("verification dispatch unexpected error id=%s", verification_id)
        return False


async def announce_verification_outcomes() -> int:
    """Expire what is due, announce every ended verification once, and prune the old.

    One pass, in this order on purpose. Expiry comes first so that a verification that
    ran out during the interval is announced in the same pass rather than the next one;
    pruning comes last so that nothing is deleted in the same breath it is announced.

    Returns how many announcements were made, which is what a caller logs.
    """
    announced = 0

    # Expire what is due. These rows are left unannounced on purpose and picked up by the
    # same loop as every other ending below: one announcer, so that a writer added later
    # cannot be a writer that forgot.
    expired = await queries.expire_due_verifications()
    if expired:
        logger.info("Expired %d open verification(s)", len(expired))

    # Everything that ended since the last pass. A confirmation by an arriving call or
    # message has no request to answer into, which is exactly why this exists.
    for row in await queries.unnotified_terminal_verifications():
        if not await queries.mark_verification_notified(row["id"]):
            continue        # another pass won it
        await push_verification(row["id"], row["app_id"], row["status"],
                                method=row["confirmed_by"], reason=row["reason"])
        announced += 1

    gone = await queries.prune_verifications(store.verification_retention_days)
    if gone:
        logger.info("Pruned %d finished verification(s)", gone)
    return announced
