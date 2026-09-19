"""One call, however many times the modem announces it.

The modem does not report a call; it reports that a call is ringing, over and over, for
as long as it rings. Fifteen `RING` / `+CLIP` pairs in sixteen seconds was measured on
the production EP06-E on 2026-09-18 for a single call. Anything that acts per line
therefore acts fifteen times, and the two things built on top of this — confirming a
verification and counting nameless calls — are both things that must happen once.

Collapsing lives here rather than in the reader because it is a rule about time, and a
rule about time is worth being able to test without a modem in the loop.

The rule: ringing is a cadence of roughly a second, so a gap an order of magnitude longer
than that means the ringing stopped. A `RING` after such a gap is a new call; anything
inside it belongs to the call already open. That is deliberately not "the same number
within N seconds" — the number arrives on a *different line* from the event that starts
the call, and often does not arrive at all.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

# An order of magnitude over the ringing cadence. Long enough that no repetition of one
# call escapes it, short enough that a person who hangs up and dials again is two calls.
# Erring towards collapsing costs a record of a second call; erring the other way invents
# calls that never happened, and the count of nameless ones is a detector.
_RING_GAP = 10.0

# What became of a call, as stored. Named here because the reader writes them and the
# chooser will read them, and two spellings of one outcome is how a count stops counting.
NO_NUMBER = "no_number"        # nothing usable to attribute it by
UNATTRIBUTED = "unattributed"  # a number arrived and no open verification wanted it
CONFIRMED = "confirmed"        # it confirmed a verification


@dataclass
class OpenCall:
    """The call currently ringing, as far as this gateway can tell."""

    started_at: float
    last_at: float
    # The row this call was written to on its first `RING`. The number is attached to it
    # later, if one arrives at all.
    row_id: int | None = None
    # Whether a usable number has already been joined to this call. The second `+CLIP` of
    # one call says the same thing as the first and must change nothing.
    named: bool = False


class CallWatch:
    """Which arriving URC belongs to which call.

    Holds no I/O and no knowledge of verifications: it answers "is this a new call or the
    one already ringing", and the caller does the recording.
    """

    def __init__(self, gap: float = _RING_GAP) -> None:
        self._gap = gap
        self._open: OpenCall | None = None

    @property
    def open_call(self) -> OpenCall | None:
        return self._open

    def observe(self, now: float | None = None) -> tuple[OpenCall, bool]:
        """Take one arrival — a `RING` or a `+CLIP` — and say which call it belongs to.

        Returns the call and whether it was started by this arrival. A `+CLIP` with no
        `RING` before it starts a call of its own: a truncated read or a port reopened
        mid-call would otherwise lose the whole event, and the join must not be the thing
        that drops what it was meant to connect.
        """
        now = time.monotonic() if now is None else now
        call = self._open
        if call is None or now - call.last_at > self._gap:
            call = OpenCall(started_at=now, last_at=now)
            self._open = call
            return call, True
        call.last_at = now
        return call, False
