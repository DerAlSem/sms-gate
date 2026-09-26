"""Task 2.2 — the interface every rung implements, and the four outcomes it may report.

Three outcomes are not enough, and the missing one is the expensive one. A connection
lost after the frame was written, classified as `unavailable`, sends the same
verification code again down the next rung: the person receives two different codes and
neither works. This gateway has already decided for the modem that a possibly-transmitted
message is never re-offered; the messenger routes are not given the opposite default.

No type, exception or session object of a messenger client library crosses this
interface. `max_user` speaks an unofficial internal API that its own author warns may
change without notice, so containment is the whole point of the seam.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable


class Outcome(str, Enum):
    #: This rung has the message. The ladder stops.
    ACCEPTED = "accepted"
    #: This recipient cannot be reached by this route — no account, hidden from lookup.
    #: About the *recipient*, not about us. The ladder continues.
    MISS = "miss"
    #: This route cannot be used right now — limited, logged out, rate bound, missing.
    #: About *us*, not about the recipient. The ladder continues.
    UNAVAILABLE = "unavailable"
    #: The send may already have happened. The ladder stops without handing the message
    #: to any lower rung, the modem included.
    INDETERMINATE = "indeterminate"


#: Recorded for a rung that was never asked, because it cannot carry this class. Not an
#: outcome a route may report: "never offered" and "offered and missed" have opposite
#: remedies, and the reachability door has to tell them apart.
SKIPPED = "skipped"

#: Recorded for a rung that was never asked, because the number is withheld from
#: messenger lookup — the person refused, or an operator withheld it. Kept apart from
#: `SKIPPED` rather than folded into it: both mean "not asked", but the remedies are
#: opposite ends of the system. `SKIPPED` is ours to fix by configuring the class onto
#: the route; this one is not ours to fix at all, and an operator who reads it as a
#: configuration gap would answer it by configuring around a person's refusal.
WITHHELD = "withheld"


@dataclass(frozen=True)
class Attempt:
    """What one rung concluded, and why in words.

    `reason` is evidence, not a user-facing string: it is what makes "our account is
    dead" distinguishable from "these recipients have no messenger account", which
    otherwise look alike in an absence of acceptances.

    `limits_account` is that same distinction made machine-readable, for the one consumer
    entitled to act on it: task 5.5 owes an alert naming the brand and the messenger when
    a vendor says our *sender account* has been limited, revoked or logged out. It rides
    on the attempt rather than being re-derived downstream because the only place the fact
    is knowable is where the vendor's named error is classified — anywhere later it could
    be recovered only by matching on `reason`, which is the invented verdict
    `messenger-delivery` forbids.

    It is deliberately **not** how the ladder decides anything. The outcome already says
    `unavailable`; this only says why, to the operator.
    """
    outcome: Outcome
    reason: str = ""
    limits_account: bool = False


@runtime_checkable
class Route(Protocol):
    """A rung. Implementations wrap a client library and never leak its types."""

    name: str

    def carries(self, message_class: str) -> bool:
        """Whether this route may carry that class at all. A rung that cannot is skipped
        without being asked — and without disclosing the number to its vendor."""
        ...

    async def offer(
        self,
        *,
        message_id: int,
        phone: str,
        text: str,
        message_class: str,
        brand: str,
        account: str,
    ) -> Attempt:
        """Try to carry the message. Bounded by the ladder, not by the implementation:
        an exception cannot express a client that never returns, so the deadline is
        applied from outside.

        `account` is the one account `brand` owns on this messenger, handed down rather
        than looked up — task 2.5. An implementation that resolved its own account would
        hold the whole map, and holding the map is what makes substituting another
        brand's account expressible at all. A rung whose brand owns no account here is
        never called; it does not receive an empty string and decide for itself, because
        resolving the recipient would already have disclosed the number to that vendor.
        """
        ...
