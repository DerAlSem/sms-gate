# Design — hold-sends-while-unregistered

## H1 — Fresh check, not the watchdog's sample

**Decided: query registration at send time.**

The version of this idea recorded as out-of-scope in `add-send-failure-recovery` was to
reuse what the watchdog already knows. That was rejected, correctly: the watchdog polls
once a minute for its own purposes, so a send would be refused on information up to a
minute old — and refusing to send is exactly the decision that must not be made on a
guess.

Asking the modem directly costs one `AT+CEREG?` inside the lock the send is about to take
anyway. At this gateway's volume the cost is irrelevant, and the staleness objection
disappears rather than being mitigated.

## H2 — What "no" means, and what a broken check means

**Decided: only a definitive negative holds the message.**

`registration_ok()` already returns False both for "the modem says it is not registered"
and for "the query failed" — it swallows `ATCommandError` for the watchdog's purposes,
where treating a broken modem as unhealthy is right. Here the two cases must differ: a
failed query means we do not know, and a gateway that stops sending whenever it cannot
ask a question is worse than one that tries and fails.

So this path reads the registration state itself and holds only on a clear negative. A
raised error, an unparseable reply, or a timeout all fall through to attempting the send —
which will produce a real, diagnosable failure rather than a silent hold.

## H3 — Holding costs time, not attempts

**Decided: a held message is rescheduled without `begin_message_attempt`.**

Identical to the recovery gate's rule and for the same reason: the message was never
offered to the network, so counting an attempt would spend the retry budget on a period
when delivery was impossible. Four attempts inside an eight-minute outage would leave a
message finally failed having never actually been transmitted.

The reschedule delay is short — the outages observed in production last a minute or two,
and the shortest configured backoff step is the natural granularity to re-check at.

## H4 — Why this cannot become a silent outage

The obvious failure mode of "decline to send" is a gateway that declines forever. Three
existing bounds already prevent it, which is why this change adds no new knob:

- the pending deadline fails any message that stays `pending` too long, so a held message
  ends in a terminal status and its app is told;
- the watchdog independently recovers a modem that stays unregistered, so the condition
  causing the hold is itself being acted on;
- a failed check does not hold (H2), so a modem that cannot answer is still attempted.

## H5 — What this does not do

It does not make delivery more likely for a message that would have failed anyway; the
retry ladder already covers that. Its entire value is in *not creating* the one failure
that cannot be retried — a multipart whose first part was accepted before the network
went away. Stating this narrowly matters, because the measured frequency is low and it
would be easy to sell the change as a general reliability win that it is not.
