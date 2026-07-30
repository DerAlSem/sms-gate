## MODIFIED Requirements

### Requirement: A message is `delivered` only when every part is reported delivered

On a positive `+CDS` the part SHALL be marked delivered, and the message SHALL move to
`delivered` only once no part is outstanding. On a negative `+CDS` the message SHALL move
to `failed` carrying the decoded TP-status, and a permanent status SHALL count toward the
destination's blacklist threshold.

This holds while reports are still expected. It SHALL NOT survive the timeout: a network
that reports one segment of a multipart message and no more would otherwise leave every
such message outstanding for ever, and the sweep would call a delivery a failure.

#### Scenario: One part of two is reported delivered
- **WHEN** part 1 is reported delivered and part 2 is outstanding
- **THEN** the message stays `sent`

#### Scenario: The remaining reports never come
- **WHEN** the timeout is reached with at least one part confirmed and none failed
- **THEN** the message is `delivered`, not `expired`

### Requirement: A `sent` message with no delivery report expires

A sweep SHALL run every 60 seconds and move every message that has been `sent` longer
than `delivery_timeout_seconds` to `expired`, notifying the owning app per message. The
timeout SHALL be re-read each sweep so a settings change applies without a restart.

A message SHALL expire only when **nothing** about it was confirmed. Where at least one
part was reported delivered and none was reported failed, the sweep SHALL complete it as
`delivered` instead — the network said it handed over part of the message and never said
otherwise about the rest, which is evidence of delivery rather than of its absence. Absence
of *any* report remains absence of evidence, and still expires.

A message completed this way SHALL be distinguishable afterwards from one whose every part
was confirmed. "We were told" and "we concluded" are different facts, and an operator
diagnosing a complaint needs to know which one they are reading.

#### Scenario: No report arrives in time
- **WHEN** a message has been `sent` for longer than the configured timeout and no part was ever confirmed
- **THEN** it becomes `expired` and its app is notified once

#### Scenario: Some parts were confirmed and the rest never were
- **WHEN** the timeout is reached, one part of two is confirmed delivered, and neither is failed
- **THEN** the message becomes `delivered`, its app is notified once, and the record shows the status was inferred rather than reported

#### Scenario: A part was reported failed
- **WHEN** a part has been reported failed
- **THEN** the timeout does not turn the message into a delivery
