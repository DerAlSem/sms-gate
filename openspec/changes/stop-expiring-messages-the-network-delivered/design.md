## Context

`expire_stale_messages` selects every message that has been `sent` longer than the timeout
and moves it to `expired`, returning the ids so the expiry loop can notify each owner. It
does not look at the parts.

`message_parts_all_delivered` decides the ordinary path: a positive `+CDS` marks its part
delivered, and the message becomes `delivered` only when nothing is outstanding.

Between them sits the case this change is about: a multipart message where some parts were
confirmed, none failed, and the rest will never be reported.

## Goals / Non-Goals

**Goals:**

- Stop reporting deliveries as failures.
- Keep the distinction between a delivery the network confirmed and one we concluded.

**Non-Goals:**

- Inferring anything from silence alone. A message with no report at all still expires.
- Changing what happens on a negative report.
- Making the rule operator-aware. The behaviour is a property of reports arriving or not,
  and encoding one carrier's name into the gateway would be a guess about the next one.

## Decisions

### The inference happens at the timeout, not on every report

The obvious alternative is to complete a message as soon as any part is confirmed. It is
simpler and it is wrong: while reports are still expected, "part 2 delivered" genuinely does
not mean part 1 was, and a message half delivered would be announced as whole. The evidence
that the rest is not coming is *the timeout*, and until it fires there is no such evidence.

So the happy path keeps its strictness and only the boundary moves. This also means the
change cannot affect a message that behaves normally, which bounds what it can break.

### Silence about everything still expires; silence about the rest does not

The two look similar and are not. A message with no report at all may have gone nowhere —
nothing has been observed about it, and calling that a delivery would be inventing evidence.
A message with one part confirmed has been observed: the network took a segment and handed it
over, and then said nothing about the others. Saying nothing is what this network does about
the others; it is not what it does about a failure, which it reports.

That asymmetry is the whole justification, and it is why the rule is conditioned on a
confirmation existing rather than on a timeout alone.

### The conclusion is recorded as a conclusion

A message completed this way must not be indistinguishable from one the network confirmed
outright. The gateway will be read by someone chasing a complaint — "the customer says they
never got it" — and the first question will be how solid the `delivered` is. Losing that
distinction would make the record confidently wrong, which is worse than the `expired` this
change removes: an operator distrusts `expired` already.

### The application hears the conclusion, not the reasoning

One notification, `delivered`, with no `expired` before it. Emitting both would be honest
about the sequence and harmful in practice, because a receiver that acts on `expired` has
already acted by the time the correction lands — and this project has an example: a `failed`
webhook is answered by messaging an operator.

The existing scenario where a late report corrects an already-expired message stays as it
is. That one is a genuine correction after the fact, not a decision the gateway could have
made in time.

## Risks / Trade-offs

- **A genuinely half-delivered message is reported delivered.** → Accepted, and narrowly:
  it requires the network to deliver one segment, never report the others, and never report a
  failure. Where a failure is reported the message does not take this path. A handset shows a
  concatenated message only once every segment arrives, so the recipient sees nothing at all
  in the bad case — the same outcome as the `expired` we send today, but now mislabelled.
  The recorded distinction is what makes that diagnosable.
- **A receiver may have learned that `expired` is normal for some recipients.** → It stops
  arriving, which is the point; nothing new appears that it does not already handle.

## Open Questions

- **Does the operator's behaviour hold for three-part messages?** Observed on two parts
  only, with a single three-part message in the record. It does not change the rule — the
  rule is about reports, not counts — but it would be worth knowing before shortening
  templates is treated as the only mitigation.
