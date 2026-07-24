"""Delivery dispatch — push outbound message status to the application that sent it.

The symmetric counterpart of `dispatch.py`: that one routes an *inbound* SMS by the
first word of its text, because an inbound message carries no application identity.
An outbound message does — `messages.app_id` is recorded at `POST /sms/send` — so
routing here keys off the app, and no prefix is involved.

Config lives in `store.delivery_dispatch`. An app with no route is silent by design:
not every consumer wants a webhook, and polling `GET /sms/{id}` stays authoritative.

Best-effort: a notification that fails every attempt is dropped rather than persisted.
The receiver polls as a floor, so a loss self-heals within one poll interval — unlike
inbound dispatch, where a drop has no second channel at all.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.alerting import notify
from app.db import queries
from app.modem.webhook import post_with_retry
from app.settings_store import store

logger = logging.getLogger(__name__)

# Statuses worth pushing. `pending` is absent on purpose: POST /sms/send already returns
# it synchronously, so a webhook would duplicate it — and could beat the HTTP response.
NOTIFIED_STATUSES = ("sent", "delivered", "failed", "expired")

_bg_tasks: set[asyncio.Task] = set()


def find_route(app_id: str) -> dict | None:
    """Route for an application. First match wins; None when unconfigured."""
    if not app_id:
        return None
    for item in store.delivery_dispatch_parsed:
        if str(item.get("app_id", "")) == app_id:
            return item
    return None


async def deliver(route: dict, payload: dict) -> tuple[bool, str | None]:
    """POST with retry. See `app.modem.webhook.post_with_retry`."""
    return await post_with_retry(route, payload, what="delivery")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


async def dispatch_delivery(message_id: int, status: str, error: str | None = None) -> bool:
    """Notify the owning app that `message_id` moved to `status`.

    The app id and the resend link are read here rather than passed in, so every call
    site is just (id, status[, error]) — one less thing for a new status writer to get
    wrong. True only if a route matched AND delivery succeeded; never raises.
    """
    try:
        row = await queries.get_message_delivery_context(message_id)
        if row is None:
            logger.warning("delivery dispatch: message %s not found", message_id)
            return False
        route = find_route(row["app_id"])
        if route is None:
            return False
        payload = {
            "id": message_id,
            "status": status,
            "error": error,
            "occurred_at": _utc_now(),
        }
        if row["resent_from"] is not None:
            payload["resent_from"] = row["resent_from"]
        url = route["webhook_url"]
        ok, reason = await deliver(route, payload)
        logger.info(
            "delivery dispatch: app=%s id=%d status=%s url=%s ok=%s",
            row["app_id"], message_id, status, url, ok,
        )
        if not ok:
            # Nothing else surfaces this: the message's own status is already correct in
            # the DB, and the modem is fine. Dedup on the url so a dead endpoint alerts
            # once per window rather than once per message.
            notify(
                "dispatch_error",
                f"{row['app_id']} → {url}\nmessage {message_id}: {status}\n{reason}",
                dedup_extra=url,
            )
        return ok
    except Exception:
        logger.exception("delivery dispatch unexpected error id=%s", message_id)
        return False


def spawn_delivery_dispatch(message_id: int, status: str, error: str | None = None) -> None:
    """Fire-and-forget dispatch with a strong reference: the event loop holds tasks
    weakly, and a sleeping retry ladder could be collected by the GC."""
    task = asyncio.create_task(dispatch_delivery(message_id, status, error))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
