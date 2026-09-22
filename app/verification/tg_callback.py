"""The door the Telegram Gateway posts delivery outcomes to.

Public by necessity — the vendor has to reach it, and it holds no application token —
and therefore shut by default. What stands in place of the token is the signature, and
the order here is the whole point: **verify, then read, then change.** An
unauthenticated callback that moves a verification's state is a way to confirm a
verification without the code ever reaching the person: the same guarantee the code's
secrecy protects, given away at a different door.

Three things this door may do and one it may not. It records the delivery outcome
against the rung that carried the message; it fails a verification whose message the
vendor reports `expired`, with that reason; and it counts what it refuses. It never
confirms. `delivered` is the analogue of a delivery report on the modem route and `read`
is evidence the message was opened, and neither is evidence the code was used — a
verification becomes confirmed only through a correct code at
`POST /verifications/{id}/check`.

Rejections are counted by kind because the kinds mean different things. A run of
signature failures is either an attack or a rotated secret. A run of unattributed
callbacks means our own records and the vendor's have come apart. Neither is visible
without a count, and both are the sort of thing that is noticed months late.
"""

from __future__ import annotations

import collections
import json
import logging
import time
from dataclasses import dataclass

from app.db import queries
from app.verification import tg_gateway
from app.verification.routes import TG_GATEWAY

logger = logging.getLogger(__name__)

# --- where the vendor is told to find this door ------------------------------------------
#
# The Gateway takes its callback address **per request** and holds none of its own: measured
# 21.09.2026 against the vendor's reference and against the cabinet, both by layers, and
# recorded in `tests/test_where_the_vendor_reports.py`. So the address travels on every send,
# and it is assembled here rather than at the sender, because the half of it that can drift
# is the path — and the path belongs to the door.
#
# `PATH` is what `app/api/router.py` registers. One name, read by the router's decorator and
# by the builder below, so that renaming the door cannot leave the vendor posting into a 404
# it will retry ten times and then forget about.
PATH = "/verifications/tg-callback"

# The vendor's own bound on `callback_url`, off its parameter table: "An HTTPS URL … 0-256
# bytes". Measured against the address that will actually travel, not against the base.
MAX_URL_BYTES = 256


def normalize_base(raw: str) -> str:
    """The stored form of a configured base: no surrounding whitespace, no trailing slash.

    A pasted address carries both, and a doubled slash in the middle of a URL is a different
    path at some servers. Stripped once, on the way in, rather than at every read.
    """
    return raw.strip().rstrip("/")


def validate_base(raw: str) -> None:
    """Raise ValueError if the vendor would refuse the address this base builds.

    Blank is legitimate and means no address is sent at all: the rung still carries, and
    what is lost is every delivery report — see `placement.carriers_for`, which says so
    once, out loud.
    """
    base = normalize_base(raw)
    if not base:
        return
    if not base.startswith("https://"):
        # The vendor requires HTTPS. Without this the refusal arrives from the vendor, on
        # the first send, hours after the setting was saved — the same reasoning that put
        # the scheme check on `webhook_url` in the settings store.
        raise ValueError(
            f"the vendor accepts an HTTPS callback address only — got {raw!r}")
    url = base + PATH
    if len(url.encode()) > MAX_URL_BYTES:
        raise ValueError(
            f"the callback address would be {len(url.encode())} bytes, over the vendor's "
            f"{MAX_URL_BYTES}")


def url_for(base: str) -> str:
    """The address to hand the vendor, or blank when none is configured."""
    normalized = normalize_base(base)
    return normalized + PATH if normalized else ""


# Why a counter rather than a log line: a log line is read when somebody already suspects
# something. In-process, like the registry's `abandoned_probes`, and for the same reason —
# it answers "is this happening now", which is the question that gets asked.
rejections: collections.Counter[str] = collections.Counter()


@dataclass(frozen=True)
class CallbackOutcome:
    """What the door did. `accepted` is about the callback, not about the verification.

    A callback can be perfectly genuine and still move nothing — it may name a request
    no rung of ours holds, or a verification that has already ended. Those are accepted
    and attributed to nothing, which is a different thing from refused, and the
    distinction is what keeps a rotated secret from hiding among ordinary latecomers.
    """

    accepted: bool
    verification_id: int | None = None
    reason: str = ""


async def handle_callback(
    body: bytes, *, timestamp: str, signature: str, token: str, tolerance: float,
    now: float,
) -> CallbackOutcome:
    """Verify a callback and, if it is the vendor's, record what it reports."""
    refusal = tg_gateway.callback_refusal(body, timestamp=timestamp, signature=signature,
                                          token=token, tolerance=tolerance, now=now)
    if refusal:
        # 🔴 Two keys, not one. A run of `stale` is a clock; a run of `signature` is a
        # forged callback — or a credential rotated while messages were in flight, which
        # is neither. Counted together, the one that costs money looked exactly like the
        # one that does not. Task 4.66, the owner's decision of 22.09.2026: the loss is
        # made visible rather than softened, so nothing here honours a previous key.
        rejections[refusal] += 1
        logger.warning("tg_gateway callback refused: %s (%d refused so far)",
                       refusal, rejections[refusal])
        if refusal == "signature":
            await _say_what_a_rotation_would_cost()
        return CallbackOutcome(accepted=False, reason=refusal)

    try:
        status = tg_gateway.parse_request_status(json.loads(body))
    except (ValueError, TypeError) as e:
        # Signed by the right key and still not something this door understands. Counted
        # apart from a bad signature: this one says the vendor changed its payload, and
        # reading it as an attack would send somebody hunting the wrong thing.
        rejections["unreadable"] += 1
        logger.warning("tg_gateway callback signed but unreadable: %s", e)
        return CallbackOutcome(accepted=False, reason="unreadable")

    refunded, note = _refund_note(status)
    verification_id = await queries.record_rung_delivery(
        status.request_id, route=TG_GATEWAY,
        outcome=status.delivery_status or "unknown", reason=note, refunded=refunded)

    if verification_id is None:
        rejections["unattributed"] += 1
        logger.warning("tg_gateway callback names request %s, which no rung holds "
                       "(%d unattributed so far)",
                       status.request_id, rejections["unattributed"])
        return CallbackOutcome(accepted=True, reason="unattributed")

    if status.delivery_status == "expired":
        # The owner's default of 18.09.2026, pinned until they decide otherwise: a
        # message the Gateway took and did not deliver fails the verification and does
        # **not** escalate to the paid call. The safe default is the one that cannot
        # spend money on a decision nobody has taken.
        failed = await queries.fail_verification(
            verification_id,
            reason=f"the Telegram message expired undelivered ({note})")
        if not failed:
            # Already terminal. The terminal state decides, and a late report must not
            # reopen or overwrite it.
            logger.info("tg_gateway: expiry reported for verification %d, which had "
                        "already ended", verification_id)

    logger.info("tg_gateway callback: verification %d, delivery %s",
                verification_id, status.delivery_status)
    return CallbackOutcome(accepted=True, verification_id=verification_id,
                           reason=status.delivery_status or "")


def _refund_note(status: tg_gateway.RequestStatus) -> tuple[bool, str]:
    """What the vendor said about the fee, in words, because the column has two states
    and the vendor has three.

    `is_refunded` was absent from all seven captures of 18.09.2026, and the norm forbids
    reading absence as either answer. So "did not mention it" is written down rather than
    collapsed into the same zero as "said no".
    """
    if status.is_refunded is True:
        return True, "the vendor reports the fee refunded"
    if status.is_refunded is False:
        return False, "the vendor reports the fee not refunded"
    return False, "the vendor said nothing about a refund"


async def _say_what_a_rotation_would_cost() -> None:
    """Name the two readings of a refused signature, and put a number on the expensive one.

    From this door the two are genuinely indistinguishable, so both are said. What is not
    a guess is the count: the rungs still awaiting a report are exactly the messages whose
    refunds a rotation drops, and the callback is the only path a refund ever takes. An
    operator who has just rotated the token reads it as the size of what they gave up; one
    who has not reads it as an attack.

    Deduplicated on the event rather than on the callback: at a vendor reporting every
    delivery, one alert per refused report is the noise that buries the first.
    """
    from app.alerting import notify

    in_flight = await queries.rungs_awaiting_report(TG_GATEWAY)
    notify("routing",
           f"a correctly timed Telegram Gateway callback was refused on its signature. "
           f"Two things look exactly like this from here: a forged callback, and the "
           f"access token having been rotated while messages were still in flight. If it "
           f"is the rotation, {in_flight} message(s) bought on this rung are still "
           f"awaiting a report, the callback is the only path a refund ever takes, and "
           f"every one of those refunds is lost — recorded spend will stand above the "
           f"money actually spent until they age out",
           dedup_extra="tg_callback_signature")
