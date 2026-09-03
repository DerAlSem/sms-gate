"""Deciding which part a `+CDS` is about.

This is record linkage, and the two sides have separate identities. A part's identity is
`(message_id, seq)` — the only two facts the gateway owns at send time. A report's
identity is `(mr, ra, scts)` — facts the network owns. Neither is the other, and joining
them is a decision that can be wrong, so the decision is returned whole and written down
rather than being implied by which row a query happened to return.

**The chain fails open.** Absent evidence never closes a door: an empty or short `ra`, an
`scts` that will not parse, a part whose submit time is unknown — each leaves attribution
exactly where it was before this change. The new fields may *eliminate* a candidate they
contradict, or *order* candidates they can separate; they may never be *required* before
an attribution is made.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

# Statuses of the owning message that still owe a report. `expired` is included on
# purpose: a message the sweep gave up on can still be corrected by a late report, which
# is the promise `delivery-dispatch` makes and the reason such a message is not deletable.
ELIGIBLE_MESSAGE_STATUSES = ("sent", "expired")

# Per-row outcomes recorded in the ledger's `candidates`. Every part whose reference
# matched gets one, not only the winner: "how many reports did we contradict" is
# unanswerable from a record that stores the choice and forgets the alternatives.
CHOSEN = "chosen"
ELIGIBLE = "eligible"
CONTRADICTED = "contradicted"
OUTSIDE_WINDOW = "outside_window"
SUPERSEDED = "superseded"

# Whole-report outcomes. Only `unplaced` notifies an operator.
ATTRIBUTED = "attributed"
UNPLACED = "unplaced"

# How the winner was picked. `recency` is a guess, named as one, and it carries a
# consequence: a report attributed by recency alone does not count toward the
# destination's blacklist, because an irreversible penalty may not rest on a tiebreak.
BY_SOLE = "sole"
BY_NEAREST = "nearest"
BY_RECENCY = "recency"

_DIGITS = "0123456789"
_SIGNIFICANT = 10


def significant_digits(value: str | None) -> str | None:
    """The last ten digits of a number, or None when there are fewer than ten.

    Numbers are compared this way rather than by canonicalizing them. `validate_and_
    normalize` needs a region and raises on anything it dislikes, and both failure modes
    are wrong here: with `restrict_region=True` a foreign `ra` raises and the rule
    silently switches itself off, and a national-format address parsed against our region
    can canonicalize into a *different valid* number and eliminate the correct sole
    candidate — which is the regression this change exists to avoid, arrived at through
    the safety mechanism.

    None means "not comparable", and nothing is eliminated on a comparison that cannot be
    made: a length difference is not a disagreement.
    """
    if not value:
        return None
    digits = "".join(c for c in value if c in _DIGITS)
    return digits[-_SIGNIFICANT:] if len(digits) >= _SIGNIFICANT else None


def _parse_stored_time(value) -> datetime | None:
    """A `TIMESTAMP` column SQLite wrote with `CURRENT_TIMESTAMP`, as aware UTC.

    Anything that will not parse is *unknown*, which the rules below treat as inside the
    window and unusable for ordering — never as a particular time.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    for shape in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(str(value), shape).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


@dataclass
class AttributionDecision:
    """What attribution concluded, whole.

    Three consumers read this and each reads a different field: the ledger writes all of
    it, the alert fires on `unplaced` alone, and `record_permanent_fail` must not fire
    when the choice was made by recency. A lookup that returned only a row could not carry
    that, and the blacklist rule would have a test and no mechanism.
    """
    outcome: str
    message_id: int | None = None
    seq: int | None = None
    decided_by: str | None = None
    reason: str | None = None
    candidates: list[dict] = field(default_factory=list)


def _contradicts(report_recipient: str | None, stored_phone: str | None) -> bool:
    theirs = significant_digits(report_recipient)
    ours = significant_digits(stored_phone)
    if theirs is None or ours is None:
        return False
    return theirs != ours


def attribute(report, rows, *, window_hours: int, strict: bool,
              now: datetime | None = None) -> AttributionDecision:
    """Decide which part `report` is about, given every part whose reference matched.

    `rows` must be **every** part sharing the reference, collected before any window or
    status filter. Filtering in the query instead would mean the record cannot name what
    it excluded: it would answer "nothing matched" where the truth was "one match, too
    old", the question the strict switch is flipped on would become unanswerable, and —
    worse — a superseded report would be indistinguishable from a report about nothing and
    would start waking an operator on ordinary traffic.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=window_hours)
    reported_at = report.submitted_at

    graded: list[tuple[dict, str, datetime | None]] = []
    for row in rows:
        sent_at = _parse_stored_time(row["sent_at"])
        if row["msg_status"] not in ELIGIBLE_MESSAGE_STATUSES or row["part_status"] != "sent":
            # The message already reached `delivered` or `failed`, or a report has already
            # set this part. Ordinary network behaviour, not a fault: a multipart message
            # completed at the timeout still receives its remaining reports.
            graded.append((row, SUPERSEDED, sent_at))
        elif sent_at is not None and sent_at < cutoff:
            graded.append((row, OUTSIDE_WINDOW, sent_at))
        elif _contradicts(report.recipient, row["phone"]):
            # Recorded whether or not it eliminates. While the switch is off this is the
            # evidence the flip decision is taken on.
            graded.append((row, CONTRADICTED, sent_at))
        else:
            graded.append((row, ELIGIBLE, sent_at))

    def _record(chosen_key=None) -> list[dict]:
        return [
            {
                "message_id": row["message_id"],
                "seq": row["seq"],
                "outcome": CHOSEN if (row["message_id"], row["seq"]) == chosen_key
                           else grade,
            }
            for row, grade, _ in graded
        ]

    # A contradiction is the one rule in this change that can refuse a delivery, so it is
    # the only one behind a switch. While the switch is off the candidate stands.
    surviving = [
        (row, sent_at) for row, grade, sent_at in graded
        if grade == ELIGIBLE or (grade == CONTRADICTED and not strict)
    ]

    if not surviving:
        grades = {grade for _, grade, _ in graded}
        if SUPERSEDED in grades:
            # A completed message is an ordinary explanation for a report that cannot be
            # applied. Recorded, silent — the operator is not woken by ordinary traffic.
            row = next(r for r, g, _ in graded if g == SUPERSEDED)
            return AttributionDecision(
                outcome=SUPERSEDED, message_id=row["message_id"], seq=row["seq"],
                reason="the reference matches a part already reported or completed",
                candidates=_record(),
            )
        if OUTSIDE_WINDOW in grades:
            reason = "the only matches fell outside the delivery-report window"
        elif CONTRADICTED in grades:
            reason = "every candidate is addressed to a different number"
        else:
            reason = "no part carries this reference"
        return AttributionDecision(outcome=UNPLACED, reason=reason, candidates=_record())

    if len(surviving) == 1:
        chosen, _ = surviving[0]
        decided_by = BY_SOLE
    else:
        chosen, decided_by = _choose(surviving, reported_at)

    key = (chosen["message_id"], chosen["seq"])
    return AttributionDecision(
        outcome=ATTRIBUTED, message_id=key[0], seq=key[1], decided_by=decided_by,
        candidates=_record(chosen_key=key),
    )


def _choose(surviving, reported_at):
    """Nearest submit time, else the most recently sent."""
    if reported_at is not None:
        datable = [(row, sent_at) for row, sent_at in surviving if sent_at is not None]
        if datable:
            distances = [(abs(sent_at - reported_at), row) for row, sent_at in datable]
            best = min(d for d, _ in distances)
            closest = [row for d, row in distances if d == best]
            if len(closest) == 1:
                return closest[0], BY_NEAREST

    # A guess, and named as one. A known submit time outranks an unknown one for
    # "most recent": an unknown time is a backfill from before per-segment times existed.
    def recency_key(item):
        row, sent_at = item
        return (sent_at is not None, sent_at or datetime.min.replace(tzinfo=timezone.utc),
                row["message_id"], row["seq"])

    return max(surviving, key=recency_key)[0], BY_RECENCY
