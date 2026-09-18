## MODIFIED Requirements

### Requirement: An alert names only what the gateway observed

An alert raised by the recovery ladder SHALL NOT name a cause the gateway did not observe.

On 2026-09-06 every alert of a two-hour outage read `check antenna/operator` while the
modem was refusing its own SIM. Both named parties were healthy. An alert that names the
wrong cause is worse than one that names none, because it is acted on: it sent the operator
to check the two things that were working, and the fault was found only by reading a
sibling service's journal.

The text SHALL carry the observations the gateway already holds — SIM state, registration,
signal, operator. Where those observations are unavailable, the alert SHALL say so rather
than fall back to a guess.

**Gathering those observations SHALL cost no more than the observations themselves.** The
alert asks the modem only for the readings it prints. It runs while the modem is by
definition already misbehaving and it holds the command port for the whole sweep, so every
command on that path delays the alert, the recovery behind it, and any send queued behind
the lock. Today it runs the entire diagnostic sweep — fourteen commands, of which two are
refused and one waits out its timeout — to print four readings.

This also decides what a new reading costs. The diagnostics page is a surface an operator
chose to open and can afford to be thorough; the alert path is not. Without the separation
every reading added to the page lengthens every future incident, and the pressure becomes to
keep the page thin — the opposite of what an operator needs when the page is the only place
a fault is visible.

**The readings the alert asks for and the readings it prints SHALL be one declaration.**
Split into two lists they drift, and the drift is silent in the worst direction: a reading
that was never asked for is rendered as unavailable, which is exactly how a modem that
failed to answer is rendered, so a gateway that stopped asking looks like a modem that
stopped answering.

This requirement is about what the alert *reports*, not about what the ladder *decides*.
The ladder's causes and remedies are unchanged: a registration failure with an unusable SIM
still walks the registration ladder, and this text does not pretend otherwise.

#### Scenario: The ladder escalates while the modem is reachable
- **WHEN** an alert is raised for a modem that answers AT commands
- **THEN** it carries the SIM, registration, signal and operator the gateway read, and does not assert a cause those readings do not support

#### Scenario: The observations cannot be read
- **WHEN** the snapshot cannot be collected at the moment the alert is raised
- **THEN** the alert says the observations are unavailable rather than naming a likely cause

#### Scenario: The same fault persists across many escalations
- **WHEN** escalations repeat on their normal cadence with the observations unchanged
- **THEN** the operator is not sent one full snapshot every few minutes for hours

#### Scenario: An alert gathers its observations
- **WHEN** the gateway collects modem observations for an alert
- **THEN** only the readings that appear in the alert are asked of the modem

#### Scenario: A reading is added to the diagnostics page
- **WHEN** a new query is added to the sweep an operator sees
- **THEN** the alert path is not lengthened by it

#### Scenario: A reading is added to the alert
- **WHEN** a reading is added to what the alert prints
- **THEN** it is asked of the modem by the same declaration, rather than printed as unavailable
