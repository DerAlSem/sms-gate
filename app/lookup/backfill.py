import asyncio
import logging

import httpx

from app.settings_store import store
from app.db import queries
from app.lookup import voxlink

logger = logging.getLogger(__name__)


async def backfill_ranges(throttle: float = 0.15) -> dict:
    """Resolve every not-yet-cached number via voxlink and persist the resolved
    ones. Runs in-process on the existing DB connection. One retry on None; only
    resolved rows are written (never a blank); throttled to stay under voxlink's
    10 req/s limit."""
    rows = await queries.list_unresolved_numbers()
    resolved = 0
    skipped = 0
    async with httpx.AsyncClient(timeout=store.voxlink_timeout) as client:
        for row in rows:
            info = await voxlink.lookup(
                row["msisdn10"], store.voxlink_url, store.voxlink_timeout,
                client=client,
            )
            if info is None:
                info = await voxlink.lookup(
                    row["msisdn10"], store.voxlink_url, store.voxlink_timeout,
                    client=client,
                )
            if info is None:
                skipped += 1
            else:
                await queries.save_number_operator(row["phone"], info.operator, info.region)
                resolved += 1
            if throttle:
                await asyncio.sleep(throttle)
    result = {"total": len(rows), "resolved": resolved, "skipped": skipped}
    logger.info("voxlink backfill: %s", result)
    return result
