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

A permanent failure, and a message rejected before any AT command is issued, SHALL neither
count toward this nor clear it. A successful send SHALL clear it.

An unhealthy modem in this sense SHALL make the watchdog's health check fail exactly as a
failed registration poll does, so that recovery escalates on the existing ladder — soft
recovery, then a hard reset gated to once per thirty minutes, then the service exit. No
separate recovery path SHALL be introduced.

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

#### Scenario: The watchdog is disabled
- **WHEN** `modem_watchdog_enabled` is false and three different messages fail transiently
- **THEN** no recovery is attempted and the evidence is discarded

### Requirement: Sending is suspended while the modem is being recovered

The gateway SHALL NOT begin transmitting a message while modem recovery is in progress,
and SHALL resume when it completes.

A message held back this way SHALL NOT have an attempt counted against it, because it was
never offered to the modem — a recovery window SHALL cost a message time, never chances.

The wait SHALL be bounded: if recovery does not complete within a fixed timeout, the
sender SHALL proceed anyway. A gateway that tries and fails can be diagnosed; one that
silently stops trying cannot. That timeout SHALL exceed the longest legitimate closure —
a hard reset and its settling period — so the bound never releases a send into a modem
that is still rebooting.

Sending SHALL be resumed even if recovery fails, so a raised exception cannot leave the
gateway permanently unable to send.

#### Scenario: Recovery runs while messages are queued
- **WHEN** soft recovery is cycling the radio and a message is due
- **THEN** the message is not transmitted until recovery finishes, and its attempt count is unchanged

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
