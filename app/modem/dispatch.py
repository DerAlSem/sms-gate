"""Inbound-SMS dispatch — push inbound SMS to application webhooks by prefix.

The gateway is shared among several applications (turbo-lk, HRM, park-bot, GM…). To avoid
sending one inbound message to all of them at once (privacy fail), routing is done by the
first word of the text — a prefix the application prints for the user in its instructions
("send TURBO XXXX").

Config lives in `store.inbound_dispatch` (JSON string, see settings_store.py). Without it —
no-op (only records in `inbound_messages`).
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from app.alerting import notify
from app.settings_store import store

logger = logging.getLogger(__name__)


def parse_prefix(text: str) -> str | None:
    """First word of the SMS in upper case (for routing). None if empty."""
    if not text:
        return None
    parts = text.strip().split()
    if not parts:
        return None
    return parts[0].upper()


def find_route(prefix: str) -> dict | None:
    """Find a route by prefix. Case-insensitive."""
    if not prefix:
        return None
    target = prefix.upper()
    for item in store.inbound_dispatch_parsed:
        if str(item.get("prefix", "")).upper() == target:
            return item
    return None


async def deliver(route: dict, payload: dict) -> tuple[bool, str | None]:
    """POST with retry (1 + 4 + 16 sec). (True, None) on 2xx; otherwise
    (False, reason) where reason describes the LAST attempt — it is what the
    operator alert shows, so it must survive past the log."""
    url = route["webhook_url"]
    bearer = route.get("bearer", "")
    headers = {"Content-Type": "application/json"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"

    attempts = max(1, store.inbound_dispatch_retries)
    timeout = store.inbound_dispatch_timeout
    backoff = 1.0
    reason = "no attempt made"
    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt in range(1, attempts + 1):
            try:
                resp = await client.post(url, json=payload, headers=headers)
                if 200 <= resp.status_code < 300:
                    return True, None
                reason = f"HTTP {resp.status_code}: {resp.text[:200]!r}"
                logger.warning(
                    "inbound dispatch non-2xx: url=%s status=%d attempt=%d/%d body=%r",
                    url, resp.status_code, attempt, attempts, resp.text[:200],
                )
            except httpx.HTTPError as exc:
                reason = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "inbound dispatch error: url=%s attempt=%d/%d err=%r",
                    url, attempt, attempts, exc,
                )
            if attempt < attempts:
                await asyncio.sleep(backoff)
                backoff *= 4
    return False, reason


async def dispatch_inbound(phone: str, text: str, received_at: str | None = None) -> bool:
    """Main entry point: parse prefix → find route → send webhook.

    True if there was a match AND delivery succeeded; False in all other cases (no prefix,
    unknown prefix, delivery failed). Never raises — errors go to the log.
    """
    try:
        prefix = parse_prefix(text)
        if not prefix:
            return False
        route = find_route(prefix)
        if not route:
            return False
        payload = {"phone": phone, "text": text}
        if received_at is not None:
            payload["received_at"] = received_at
        url = route["webhook_url"]
        ok, reason = await deliver(route, payload)
        logger.info(
            "inbound dispatch: prefix=%s phone=%s url=%s ok=%s",
            prefix, phone, url, ok,
        )
        if not ok:
            # The SMS is stored and the modem is fine, so nothing else raises the
            # alarm — but the receiving app never learned about it. Dedup on the url:
            # a dead endpoint alerts once per window, not once per message.
            notify(
                "dispatch_error",
                f"{prefix} → {url}\n{phone}: {text}\n{reason}",
                dedup_extra=url,
                phone=phone,
            )
        return ok
    except Exception:
        logger.exception("inbound dispatch unexpected error phone=%s", phone)
        return False
