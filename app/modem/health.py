"""What the gateway believes about the modem, and how far up the recovery ladder it has
gone.

Extracted from `ModemManager` because this is one invariant spread across four methods
written at different times — the send path contributes evidence, the watchdog acts on it,
and both share the counters that decide how hard to act. That spread is where the sharp
bug of this feature came from: one "have we tried the gentle thing" bit answering for two
different problems, so a soft recovery performed for a lost registration let the next send
stall open with a hard reset and a service restart.

Deciding is kept free of I/O. `decide()` is a pure state transition over "is it
registered" and "may we hard-reset", returning the rung to act on; performing the
recovery, reading the cooldown marker off disk and driving the serial port stay with the
caller. That is what makes the ladder testable as a table of histories rather than only
through a live modem.
"""

from __future__ import annotations

import asyncio

from app.modem.errors import is_permanent_failure

# Rungs `decide()` can return.
OK = "ok"
WAIT = "wait"
SOFT = "soft"
COOLDOWN = "cooldown"
HARD = "hard"

# Why the modem is considered unhealthy. The ladder's progress belongs to one of these:
# mixing them is what let a stall inherit a recovery it did not earn.
REGISTRATION = "registration"
STALL = "stall"
# The link itself is gone — the port cannot be read or written at all. Distinct from the
# two above because no remedy made of AT commands can reach a modem whose port has been
# destroyed, so the ladder must not spend its rungs issuing them.
TRANSPORT = "transport"

# How many consecutive observations a cause needs before the ladder acts on it. Three
# exists to absorb one unlucky registration sample; a port that cannot be written is not
# a sample, and waiting three minutes to act on it buys nothing.
_IMMEDIATE = 1


class ModemHealth:
    """Evidence about the modem, the escalation ladder, and the gate that suspends use
    of the modem while it is being recovered."""

    def __init__(self, fail_threshold: int, stall_threshold: int) -> None:
        self._fail_threshold = fail_threshold
        self._stall_threshold = stall_threshold
        self.fails = 0
        self.soft_tried = False
        self.cause: str | None = None
        # Ids rather than a count: one message's four attempts are one piece of evidence
        # about one destination, not three about the hardware.
        self.failed_ids: set[int] = set()
        self.budget_exhausted = False
        # Set means the modem is usable. Closed around recovery so neither a send nor an
        # inbound read is issued into a radio that is off or has just come back.
        self.gate = asyncio.Event()
        self.gate.set()

    # ------------------------------------------------------------------ evidence

    def note_send_failure(self, message_id: int, error: str, *, exhausted: bool) -> None:
        """Record a failed send as possible evidence about the modem.

        A permanent failure is neutral — it neither counts nor clears, because it
        describes the destination. Letting it clear would let a stream of bad numbers
        mask a genuinely dead radio.
        """
        if is_permanent_failure(error):
            return
        self.failed_ids.add(message_id)
        if exhausted:
            self.budget_exhausted = True

    def note_send_success(self) -> None:
        """A modem that just sent something is not stalled."""
        self.clear_stall()

    def clear_stall(self) -> None:
        self.failed_ids.clear()
        self.budget_exhausted = False

    def stalled(self, *, enabled: bool = True) -> bool:
        """Whether the send path believes the modem needs recovering.

        Either several different messages have failed, or one has used up its whole
        ladder — roughly eight minutes in which nothing got out. The second clause is
        what carries a quiet gateway: at around a dozen messages a day, waiting for
        several distinct ones would take hours, which is no signal at all.
        """
        if not enabled:
            return False
        return self.budget_exhausted or len(self.failed_ids) >= self._stall_threshold

    # -------------------------------------------------------------------- ladder

    def _threshold(self, cause: str) -> int:
        """How many consecutive observations this cause needs before the ladder acts.

        Belongs to the cause, not to the ladder: the three-poll threshold is there to
        absorb a single unlucky registration sample, which is not a thing a missing port
        can be.
        """
        return _IMMEDIATE if cause == TRANSPORT else self._fail_threshold

    def decide(
        self,
        *,
        registered: bool,
        stalled: bool,
        hard_reset_allowed: bool,
        link_lost: bool = False,
    ) -> str:
        """Advance the ladder one step and name the escalation level to act on.

        Pure: no serial port, no filesystem, no clock. The caller supplies the
        observations, chooses the remedy that fits the cause, and performs it.

        The returned value is a *level*, not a command sequence. What "gentle" and
        "blunt" mean depends on why the modem is unhealthy, and for a lost link neither
        of them is an AT command.
        """
        # A lost link outranks the other two: with the port gone, "is it registered" is
        # not a question that has an answer, and the value passed for it says more about
        # how the caller handled the failure than about the modem.
        cause = None
        if link_lost:
            cause = TRANSPORT
        elif not registered:
            cause = REGISTRATION
        elif stalled:
            cause = STALL
        if cause is None:
            self.fails = 0
            self.soft_tried = False
            self.cause = None
            return OK

        if self.cause is not None and cause != self.cause:
            # The problem changed. Progress up the ladder belongs to the problem that
            # earned it — otherwise a soft recovery done for a registration outage lets
            # the next stall open with a hard reset and a restart.
            self.fails = 0
            self.soft_tried = False
        self.cause = cause

        self.fails += 1
        if self.fails < self._threshold(cause):
            return WAIT
        if not self.soft_tried:
            self.soft_tried = True
            self.fails = 0
            return SOFT
        if cause == TRANSPORT:
            # The cooldown exists so a modem is not hammered with resets. The blunt
            # remedy for a lost link is not a reset — it restarts this process — so
            # nothing is being hammered and the supervisor's own restart limits bound it.
            # Gating it here would leave the gateway unusable for up to half an hour with
            # no remedy available in the meantime.
            return HARD
        if not hard_reset_allowed:
            self.fails = 0
            return COOLDOWN
        return HARD

    def forget(self) -> None:
        """Drop everything — used when the watchdog is switched off, so the gateway
        stops accumulating a suspicion nothing will act on."""
        self.fails = 0
        self.soft_tried = False
        self.cause = None
        self.clear_stall()

    # ---------------------------------------------------------------------- gate

    def snapshot(self, *, held: int, stalled: bool) -> dict:
        """What the admin page shows. Without it, diagnostics taken mid-recovery report
        an unregistered modem with no signal — a true reading of a radio the gateway
        switched off itself, and an easy one to misread as dead hardware."""
        return {
            "recovering": not self.gate.is_set(),
            "send_stall": stalled,
            "failed_messages_since_last_success": len(self.failed_ids),
            "unhealthy_because": self.cause or "—",
            "queued_or_in_flight": held,
        }
