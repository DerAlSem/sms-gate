## ADDED Requirements

### Requirement: A send failure is classified as transient or permanent

The gateway SHALL classify every send failure before deciding its fate.

A failure SHALL be permanent when retrying it cannot change the outcome: a message over
the `max_sms_parts` budget; `+CMS` 1, 21, 28, 50, 69 or 96 (the network refuses this
message or this destination); `+CMS` 301–305, 321 or 330 (a malformed or misconfigured
request that will fail identically); `+CMS` 310, 311 or 313, and the `+CME` codes for the
same conditions, 10, 11 and 13 (the SIM is absent, locked or failed).

Every other failure — no response, a prompt timeout, `+CMS` 38, 41, 42, 331, 332, 350 or
500, a bare `ERROR`, an unrecognised or unparseable reply — SHALL be treated as
transient. An unrecognised failure SHALL default to transient.

This classification SHALL be independent of the TP-status classification applied to
delivery reports.

#### Scenario: The modem does not answer
- **WHEN** a send fails with `no response from modem (timeout)`
- **THEN** the failure is transient

#### Scenario: The network refuses the destination
- **WHEN** a send fails with `+CMS ERROR: 1 (unassigned number)`
- **THEN** the failure is permanent

#### Scenario: An unlisted code arrives
- **WHEN** a send fails with a `+CMS` code that is in no classification list
- **THEN** the failure is transient

### Requirement: Transient send failures are retried before the message is failed

A transient failure on a message that has not been transmitted SHALL schedule another
attempt instead of failing the message. The message SHALL stay `pending`, SHALL keep its
id, and SHALL NOT produce a `failed` webhook or an operator alert for that attempt.

The number of attempts SHALL be one more than the number of delays configured in
`send_retry_backoff`, and the *n*-th retry SHALL be scheduled for the *n*-th delay after
the failure. An empty `send_retry_backoff` SHALL disable retrying, giving each message a
single attempt. The setting SHALL be re-read per use so a change applies without a
restart.

A message SHALL become `failed` — notifying the owning app and alerting the operator, as
it does today and naming the last error — when the failure is permanent, or when the
attempts are exhausted.

#### Scenario: A transient failure with budget left
- **WHEN** the first attempt fails with a timeout and `send_retry_backoff` is `30,120,300`
- **THEN** the message stays `pending`, no webhook or alert is emitted, and another attempt is scheduled 30 seconds later

#### Scenario: The budget is exhausted
- **WHEN** the fourth attempt fails with a timeout and `send_retry_backoff` is `30,120,300`
- **THEN** the message becomes `failed` with that error, the owning app is notified, and the operator is alerted

#### Scenario: A permanent failure on the first attempt
- **WHEN** the first attempt fails with `+CMS ERROR: 1`
- **THEN** the message becomes `failed` immediately and no retry is scheduled

#### Scenario: Retrying is disabled
- **WHEN** `send_retry_backoff` is empty and an attempt fails transiently
- **THEN** the message becomes `failed` on that attempt

### Requirement: A partly transmitted message is never automatically re-attempted

Only a message still in status `pending` SHALL be eligible for an automatic attempt. Once
any part has been accepted by the modem — that is, once the message has reached `sent` —
a later failure SHALL fail the message immediately, whatever its classification, because
re-sending would deliver an already-transmitted part a second time.

#### Scenario: The second part of a two-part message fails
- **WHEN** part 1 is accepted, the message is `sent`, and part 2 fails with a timeout
- **THEN** the message becomes `failed` at once and no retry is scheduled

### Requirement: Retries are scheduled and never block other messages

A message awaiting a retry SHALL leave the send queue, so no other message waits behind
it for the length of a backoff delay.

The scheduled time SHALL be persisted with the message, so a pending retry survives a
restart. A scheduler SHALL re-queue messages whose scheduled time has passed, and SHALL
NOT re-queue a message the sender already holds queued or in flight.

#### Scenario: A short message follows a deferred one
- **WHEN** a message is deferred for five minutes and another send arrives immediately after
- **THEN** the second message is transmitted without waiting for the first

### Requirement: Repeated send failures drive modem recovery

Three consecutive transient send failures SHALL cause the watchdog's next check to take
its failure branch regardless of what registration reports, so a modem that answers
`AT+CEREG?` while refusing to send is still recovered. A successful send SHALL clear that
condition.

Recovery SHALL remain the watchdog's: the existing escalation from soft recovery to hard
reset, and the once-per-30-minutes hard-reset gate, SHALL apply unchanged. No separate
recovery path SHALL be introduced.

#### Scenario: The modem answers but will not send
- **WHEN** three consecutive sends fail transiently while every registration poll succeeds
- **THEN** the watchdog proceeds as if registration had failed, escalating on its own ladder

#### Scenario: A send succeeds between failures
- **WHEN** two sends fail transiently and the next succeeds
- **THEN** no recovery is triggered

## MODIFIED Requirements

### Requirement: Queued messages survive a restart

A message accepted as `pending` SHALL be transmitted after a service restart.

A `pending` message that the sender does not hold queued or in flight SHALL be re-queued
by the scheduler once it is due; a message that has never been attempted SHALL be
considered due only after it is older than 60 seconds, so a message still being handed to
the queue is not claimed twice.

#### Scenario: The service restarts before transmission
- **WHEN** a message is accepted and the service restarts before it is transmitted
- **THEN** the message is transmitted after the restart rather than staying `pending` forever

#### Scenario: A message is accepted normally
- **WHEN** a message is accepted and handed straight to the queue
- **THEN** the scheduler does not enqueue it a second time

## REMOVED Requirements

### Requirement: A message gets exactly one transmission attempt

**Reason**: replaced by the retry policy above — the behaviour this recorded is the defect
this change fixes. It was adopted as `descriptive` and never promoted.

### Requirement: Send outcomes do not influence modem recovery

**Reason**: replaced by "Repeated send failures drive modem recovery". Adopted as
`descriptive` and never promoted.
