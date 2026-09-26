"""Task 3.4 — what the configured limit rule permits, above the claim that records it.

The split is the same one the rest of this seam is built on: `queries` owns the atomic
consumption of an allowance, this owns the reading of the rule, and the ladder owns
neither. A rung is never handed the rule and never asked to hold itself down — the
per-recipient bound spans every brand's account, and a rung that knew enough to enforce
it would be a rung that knew enough to substitute a brand.

**Both of the wrong readings the delta names are refusals here.** A limit rule that does
not parse is not absent and is not zero; an account the rule does not mention has no
allowance rather than an unbounded one. The save-time validator already refuses both
configurations, and this reader calls that same validator rather than a second, looser
one of its own — a reader written in its own words is a reader that drifts from the
writer, and the direction it drifts in costs an account permanently.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.db import queries
from app.routing.config import parse_limits, validate_limits

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Claim:
    """Granted, or refused with the reason the ladder records against the route."""

    granted: bool
    reason: str = ""


class DurableBounds:
    """The configured bounds, consumed in the database.

    Stateless on purpose. The counters live in SQLite because this process exits by
    design — the modem's hard recovery rung calls `os._exit(1)`, and every push to
    `master` restarts the service — and an instance holding a window in memory would hand
    the account a fresh allowance on every one of those restarts, inside the same hour.
    """

    def _rule(self) -> dict | None:
        """The parsed limit rule, or None when it cannot be read.

        None is the *alerting* answer and never an empty rule: returning `{}` here is
        precisely the "read as absent" the delta forbids, and it is what the lenient
        `parse_limits` does on its own.
        """
        from app.settings_store import store

        raw = store.get("messenger_limits") or ""
        try:
            validate_limits(raw)
        except ValueError as refusal:
            # The operator channel is a handler on the root logger at ERROR, so this is
            # the alert. Deduped there by the message template, which is what keeps a
            # rule that is broken for an hour from becoming an hour of notifications.
            logger.error(
                "the messenger limit rule does not parse and no account may send until "
                "it does: %s", refusal,
            )
            return None
        return parse_limits(raw)

    async def claim(self, *, message_id: int, route: str, account: str, phone: str) -> Claim:
        """Consume one unit of this account's allowance, or say why not."""
        rule = self._rule()
        if rule is None:
            return Claim(False, "the limit rule does not parse; no account may send")

        bounds = (rule.get("accounts") or {}).get(account)
        if not isinstance(bounds, dict):
            return Claim(
                False,
                f"account {account!r} has no rate bound in the limit rule, so it has no "
                "allowance — an account without one is never read as unbounded",
            )

        granted = await queries.claim_rate_allowance(
            message_id=message_id,
            route=route,
            account=account,
            phone=phone,
            per_hour=bounds["per_hour"],
            per_day=bounds["per_day"],
            recipient_window_seconds=rule.get("recipient_window_seconds") or 0,
        )
        if granted:
            return Claim(True)
        return Claim(
            False,
            f"account {account!r} is at a configured bound "
            f"({bounds['per_hour']}/hour, {bounds['per_day']}/day) or this number was "
            "addressed by another account inside the recipient window",
        )

    async def settle(self, *, message_id: int, route: str, may_have_reached: bool) -> None:
        """Say whether the send this claim paid for may have reached the person.

        The account's own bound is unaffected: it counts the claim either way, because
        the vendor was asked either way. Only the recipient window reads this.
        """
        await queries.settle_rate_claim(
            message_id=message_id, route=route, may_have_reached=may_have_reached,
        )
