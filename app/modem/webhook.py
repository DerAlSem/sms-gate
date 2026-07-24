"""Shared webhook transport for both dispatch directions.

`inbound_dispatch` (SMS in → application) and `delivery_dispatch` (message status →
application) POST to operator-configured routes with the same auth, the same retry
ladder and the same settings. Only the payload and the routing key differ, so the
transport lives here and both callers stay thin.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from app.settings_store import store

logger = logging.getLogger(__name__)


async def post_with_retry(route: dict, payload: dict, *, what: str) -> tuple[bool, str | None]:
    """POST `payload` to `route`, retrying with exponential backoff.

    `inbound_dispatch_retries` attempts (default 3), each with a `inbound_dispatch_timeout`
    timeout (default 10 s); the gap before a retry starts at 1 s and quadruples (1 s, 4 s,
    …). At the default of 3 attempts that is two gaps — 1 s and 4 s — since the loop does
    not sleep after the final attempt.

    Returns (True, None) on 2xx; otherwise (False, reason) where reason describes the
    LAST attempt — it is what the operator alert shows, so it must survive past the log.
    `what` labels the log lines ("inbound" / "delivery").
    """
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
                    "%s dispatch non-2xx: url=%s status=%d attempt=%d/%d body=%r",
                    what, url, resp.status_code, attempt, attempts, resp.text[:200],
                )
            except httpx.HTTPError as exc:
                reason = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "%s dispatch error: url=%s attempt=%d/%d err=%r",
                    what, url, attempt, attempts, exc,
                )
            if attempt < attempts:
                await asyncio.sleep(backoff)
                backoff *= 4
    return False, reason
