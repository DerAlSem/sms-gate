## ADDED Requirements

### Requirement: Repeated send failures are evidence the modem needs recovery

The gateway SHALL track the messages that have failed transiently since the last
successful send, and SHALL treat the modem as unhealthy when, with no send having
succeeded in between, either three *different* messages have failed transiently, or one
message has exhausted its entire retry budget on transient failures.

Attempts of a single message SHALL count once toward the three, however many it makes:
repeated failure against one destination is evidence about that destination. The
budget-exhaustion clause exists because this gateway carries around a dozen messages a
day, roughly two hours apart, so waiting for three distinct messages would take hours —
long enough to be no signal at all.

A failure counts when its error is not a permanent one, whether or not the message was
eligible for a retry — a timeout after the PDU was written is not retryable, but it is
still evidence about the modem. A permanent failure, a message rejected before any AT
command is issued, an internal error that never reached the modem, and a message failed
by the pending sweep SHALL neither count toward this nor clear it. A successful send
SHALL clear it.

An unhealthy modem in this sense SHALL make the watchdog's health check fail exactly as a
failed registration poll does, so that recovery escalates on the existing ladder — soft
recovery, then a hard reset gated to once per thirty minutes, then the service exit. No
separate recovery path SHALL be introduced.

The ladder's progress SHALL belong to the problem that earned it: when the reason the
modem is unhealthy changes between a failed registration and a send stall, the escalation
SHALL start again from the first rung. Otherwise a soft recovery performed for a
registration outage would let the next stall open with a hard reset and a service restart.

Because recovery consumes the evidence, a single stall SHALL escalate no further than one
soft recovery; reaching a hard reset SHALL require messages to fail again afterwards.

The gateway SHALL provide a setting that disables this coupling on its own, leaving
recovery driven by registration alone. A mechanism able to restart the service needs a
switch that does not also give up the rest of the watchdog.

Performing a recovery SHALL discard the tracked evidence, so escalating further requires
messages to fail again. Without this a stall declared on a quiet gateway would survive
untouched — there being nothing to send that could clear it — and drive the ladder to a
service restart on evidence already acted upon.

When the watchdog is disabled this SHALL have no effect, and the tracked evidence SHALL be
discarded.

#### Scenario: The modem answers but will not send
- **WHEN** three different messages fail transiently with no successful send between them, while every registration poll succeeds
- **THEN** the watchdog's next check fails and escalates on its own ladder

#### Scenario: One message uses up its whole ladder
- **WHEN** a single message fails transiently on all four of its attempts and no send succeeds in between
- **THEN** the modem is treated as unhealthy, because nothing has got out for the length of the budget

#### Scenario: A message fails its ladder but other sends succeed
- **WHEN** a message exhausts its attempts transiently but other messages send successfully in between
- **THEN** the modem is not treated as unhealthy — the evidence points at the destination

#### Scenario: A send succeeds between failures
- **WHEN** two messages fail transiently and the next message sends successfully
- **THEN** the evidence is discarded and no recovery is triggered

#### Scenario: The failures are permanent
- **WHEN** three different messages fail with `+CMS ERROR: 1 (unassigned number)`
- **THEN** the modem is not treated as unhealthy

#### Scenario: Nothing is sent after a recovery
- **WHEN** a stall triggers a soft recovery and no message is sent for the next hour
- **THEN** no further recovery is triggered, because the evidence was consumed

#### Scenario: A stall follows a registration outage
- **WHEN** registration failures have already caused a soft recovery, registration returns, and the sends that failed meanwhile declare a stall
- **THEN** the stall begins its own escalation rather than proceeding straight to a hard reset

#### Scenario: The coupling is switched off
- **WHEN** the stall-recovery setting is disabled and messages fail transiently
- **THEN** the health check depends on registration alone

#### Scenario: The watchdog is disabled
- **WHEN** `modem_watchdog_enabled` is false and three different messages fail transiently
- **THEN** no recovery is attempted and the evidence is discarded

### Requirement: Sending is suspended while the modem is being recovered

The gateway SHALL NOT begin transmitting a message, nor read an inbound message from the
modem, while recovery is in progress, and SHALL resume when it completes. An inbound read
issued against a switched-off radio fails and its notification is discarded, leaving the
message unread until the next restart.

Recovery SHALL NOT be considered complete when its commands return: reselecting an
operator is a request, not a completed attach. The gateway SHALL wait for the modem to
report registration, up to a bound, before resuming — sending during the reattach
produces exactly the failures the recovery was meant to stop, which would re-arm the
stall that triggered it.

A recovery that restores the modem SHALL also restore the subscription that delivers
`+CDS` and `+CMTI`. Losing it is silent and total: every message would expire and every
inbound SMS would be missed, with no health check able to notice.

A message held back this way SHALL NOT have an attempt counted against it, because it was
never offered to the modem — a recovery window SHALL cost a message time, never chances.

Recovery itself SHALL be bounded, so the suspension has a stated ceiling rather than an
open-ended one — it must first take the serial port, which a long multipart send can hold
for minutes. The sender's own wait SHALL be bounded by more than that ceiling: releasing
it during a legitimate recovery is worse than not suspending at all, because the wait was
spent as well. A gateway that tries and fails can be diagnosed; one that
silently stops trying cannot. That timeout SHALL exceed the longest legitimate closure —
a hard reset and its settling period — so the bound never releases a send into a modem
that is still rebooting.

Sending SHALL be resumed even if recovery fails, so a raised exception cannot leave the
gateway permanently unable to send.

#### Scenario: Recovery runs while messages are queued
- **WHEN** soft recovery is cycling the radio and a message is due
- **THEN** the message is not transmitted until recovery finishes, and its attempt count is unchanged

#### Scenario: The modem has not come back yet
- **WHEN** the recovery commands have returned but the modem does not yet report registration
- **THEN** sending stays suspended until it does, or until the bound elapses

#### Scenario: An inbound notification arrives during recovery
- **WHEN** an inbound message is announced while the radio is being cycled
- **THEN** it is read after recovery rather than lost

#### Scenario: Recovery raises
- **WHEN** a recovery operation raises an exception
- **THEN** sending is resumed rather than left suspended

#### Scenario: Recovery never finishes
- **WHEN** the recovery gate stays closed beyond the sender's timeout
- **THEN** the sender attempts the message rather than holding it indefinitely

## REMOVED Requirements

### Requirement: Send outcomes do not influence modem recovery

**Reason**: replaced by the two requirements above. It was adopted as `descriptive`,
carried as a known gap through `add-send-retries`, and never promoted.

### Requirement: The cost of a stall-driven restart is acknowledged

A hard reset ends in a service exit, which permanently loses any message being
transmitted at that moment — an attempt already claimed is never re-attempted, by the
never-transmitted-twice rule. The pending deadline is not extended for time spent
recovering, so a message may be failed partly because the gateway spent that time
recovering the modem.

Both are accepted rather than mitigated: extending the deadline would mean a message
arriving long after its moment, and making an interrupted attempt recoverable would risk
delivering it twice. Recovery is therefore gated on renewed evidence precisely because
each escalation is expensive.

#### Scenario: A message is in flight when the service exits
- **WHEN** a hard reset ends the process while a message is being transmitted
- **THEN** that message is not re-attempted after the restart, and is swept to `failed` once past its deadline
