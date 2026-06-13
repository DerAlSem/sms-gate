"""Assembly of multipart-SMS from parts (UDH concat).

Part → inbound_parts; once all parts are collected (or the group has expired) —
saved as a single record in inbound_messages. DB only: dispatch is done by the caller.

Saving the assembled message uses a «claim»: the group is deleted first, and only
the caller whose DELETE actually deleted rows saves it. This prevents the inbound
loop and the flush loop from writing the same group twice. Serialisation of
read→delete→save via a lock prevents loss of a late-arriving part.
"""

from __future__ import annotations

import asyncio
import logging

from app.db import queries
from app.modem.pdu import ConcatInfo

logger = logging.getLogger(__name__)

# Serialises read→delete→save: otherwise the flush loop could delete a part
# appended by the inbound loop between its read and the group deletion.
_claim_lock = asyncio.Lock()


async def handle_inbound(phone: str, text: str, concat: ConcatInfo | None) -> str | None:
    """Save an inbound message. Returns the full text if the message is complete
    (single-part or the last part has arrived); None — waiting for remaining parts."""
    if concat is None or concat.total <= 1:
        await queries.save_inbound(phone, text)
        return text

    async with _claim_lock:
        await queries.save_inbound_part(phone, concat.ref, concat.total, concat.seq, text)
        parts = await queries.get_inbound_parts(phone, concat.ref, concat.total)
        if len(parts) < concat.total:
            logger.info(
                "Multipart pending: phone=%s ref=%d %d/%d",
                phone, concat.ref, len(parts), concat.total,
            )
            return None

        if not await queries.delete_inbound_parts(phone, concat.ref, concat.total):
            return None  # group already claimed by the flush loop
        full = "".join(p["text"] for p in parts)
        await queries.save_inbound(phone, full)
        return full


async def flush_stale_parts(max_age_seconds: int = 300) -> list[tuple[str, str]]:
    """Save incomplete groups older than max_age_seconds as-is.
    Returns [(phone, text)] — for dispatch by the caller."""
    flushed: list[tuple[str, str]] = []
    for g in await queries.stale_part_groups(max_age_seconds):
        try:
            async with _claim_lock:
                parts = await queries.get_inbound_parts(g["phone"], g["ref"], g["total"])
                if not parts or not await queries.delete_inbound_parts(g["phone"], g["ref"], g["total"]):
                    continue  # group already assembled by the inbound loop
                full = "".join(p["text"] for p in parts)
                await queries.save_inbound(g["phone"], full)
            logger.warning(
                "Flushed incomplete multipart: phone=%s ref=%d %d/%d parts",
                g["phone"], g["ref"], len(parts), g["total"],
            )
            flushed.append((g["phone"], full))
        except Exception:
            logger.exception("Flush failed for group phone=%s ref=%s", g["phone"], g["ref"])
    return flushed
