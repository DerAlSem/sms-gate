## ADDED Requirements

### Requirement: An alert names only what the gateway observed

An alert raised by the recovery ladder SHALL NOT name a cause the gateway did not observe.

On 2026-09-06 every alert of a two-hour outage read `check antenna/operator` while the
modem was refusing its own SIM. Both named parties were healthy. An alert that names the
wrong cause is worse than one that names none, because it is acted on: it sent the operator
to check the two things that were working, and the fault was found only by reading a
sibling service's journal.

The text SHALL carry the observations the gateway already holds. The diagnostics snapshot —
SIM state, registration, signal, operator — is collected from the modem on demand and
rendered on the console; an alert that omits it forces whoever reads it to open a second
surface to learn what the first one had. Where those observations are unavailable, the
alert SHALL say so rather than fall back to a guess.

This requirement is about what the alert *reports*, not about what the ladder *decides*.
The ladder's causes and remedies are unchanged: a registration failure with an unusable SIM
still walks the registration ladder, and this text does not pretend otherwise.

[normative · evidence: app/modem/manager.py:1094-1109, app/modem/manager.py:118,
collect_diagnostics · conf: high — the observations exist and are already collected; only
their delivery into the alert is new]

#### Scenario: The ladder escalates while the modem is reachable
- **WHEN** an alert is raised for a modem that answers AT commands
- **THEN** it carries the SIM, registration, signal and operator the gateway read, and does not assert a cause those readings do not support

#### Scenario: The observations cannot be read
- **WHEN** the snapshot cannot be collected at the moment the alert is raised
- **THEN** the alert says the observations are unavailable rather than naming a likely cause

#### Scenario: The same fault persists across many escalations
- **WHEN** escalations repeat on their normal cadence with the observations unchanged
- **THEN** the operator is not sent one full snapshot every few minutes for hours
