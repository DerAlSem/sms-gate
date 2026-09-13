# number-reachability Specification

## Purpose

What this gateway is able to say about a phone number **as a channel to a person**: when
that number was last reached, by which route, and on the strength of whose statement —
together with the limits on what such an answer may reveal and on who may ask. Every
application sees only its own traffic; the gateway alone sees the number across all of
them, and this seam owns that asymmetry. It observes a channel and never an identity:
whether the number belongs to the person claiming it is the application's question,
because the application owns the code.

## ADDED Requirements

### Requirement: The gateway reports when a number was last reached, never whether it is reachable

`GET /reachability/{phone}` SHALL return, for each route, the time that route last carried
a message to the number and whether that delivery was reported by the network or inferred,
together with the number's blacklist state and the time it was blocked. It SHALL NOT
return a boolean verdict.

Reachability decays and the gateway cannot observe the decay: a SIM changes hands, a
released number returns to circulation, a messenger account is abandoned. A boolean turns
a statement about the past into a claim about the present, and once the gateway has
discarded the age, no consumer can recover it.

A number that has **never been offered** to a route SHALL be answered as never offered,
distinctly from a number that was offered and never accepted. The two look alike in an
absence of acceptances and have opposite remedies — the first is a number we have not
tried, the second a number that does not answer.

The answer SHALL NOT assert that the number belongs to any person or account.

[unbacked · no such endpoint exists today; the facts it reads are `messages` at
app/db/migrate.py:134-145, `bad_numbers` at :152-159, and the rung ledger this change adds]

#### Scenario: Two routes reached the number at different times
- **WHEN** `tg_user` carried a message to the number three days ago and the modem carried one two months ago
- **THEN** the answer carries both routes with their own times
- **AND** it carries no single verdict about the number

#### Scenario: The number has never been offered to any route
- **WHEN** the door is asked about a number no message was ever addressed to
- **THEN** the answer says never offered, which is not the same answer as offered and never accepted

#### Scenario: The number is blacklisted
- **WHEN** the number is on the blacklist
- **THEN** the answer carries that state and the time it was blocked

### Requirement: The answer is read from records already written, and asking reaches no vendor

The answer SHALL be derived solely from records this gateway already holds — the rung
ledger, the delivery records and the blacklist — and the door SHALL NOT call any route,
SHALL NOT resolve the number at any messenger, and SHALL NOT send anything.

A door that resolved the number to answer would be a send in everything but name: it would
consume a sender account's rate allowance, disclose the number to a vendor on every call,
and fill the disclosure ledger with lookups no message was ever sent for — all behind a
request that reads as free. An application that wants fresher evidence sends a message,
which is the only act that produces any.

[unbacked]

#### Scenario: The door is asked about a number with no records
- **WHEN** the door is asked about a number that has never been offered to a route
- **THEN** no messenger is contacted and the answer is produced from the absence of records

#### Scenario: The door is called repeatedly
- **WHEN** the door is called a hundred times for one number
- **THEN** no sender account's hourly or daily allowance is consumed

### Requirement: The answer carries the strength of its evidence

Each route's last reach SHALL be marked as reported or inferred, on the same distinction
the blacklist suppression rests on: a positive `+CDS` is the network's statement, a
messenger acceptance is ours.

A messenger acceptance means the message was handed over, not that a person saw it — no
route in this change can report that a message was read. An answer that collapses the two
invites a consuming application to read "we gave it to Telegram" as "the person has it",
which is the very confusion the route report exists to prevent.

[unbacked · the reported-versus-inferred distinction is the `delivery_inferred` column
this change reuses]

#### Scenario: The last reach was a messenger acceptance
- **WHEN** the most recent message to the number was accepted by `tg_user`
- **THEN** that reach is marked inferred

#### Scenario: The last reach was a delivery report
- **WHEN** the most recent message to the number was confirmed by a positive `+CDS`
- **THEN** that reach is marked reported

### Requirement: The answer names routes and times, never applications, text or counts

The answer SHALL carry route names, times, evidence strength and blacklist state, and
SHALL NOT carry the identity of the application that sent, any message text, or any count
of messages.

**The answer SHALL span every application's traffic**, not only the asking application's:
an application already knows its own sends, so an answer narrowed to them would carry no
evidence the asker did not have. This is the owner's decision of 13.09.2026, and it is
what the door exists for.

That same property links the customers of two brands through one gateway, which is why the
answer is held to the minimum that serves reachability: a route and a time say that we can
reach this person, while an application name says whose customer they are. The first is the
question; the second is a profile, and nothing in this door needs it. The legal review of
the linkage is still owed and is recorded in the proposal.

[unbacked]

#### Scenario: A number only the other application has messaged
- **WHEN** `app1` asks about a number only `app2` has ever sent to
- **THEN** the answer carries the route and the time
- **AND** it names no application, carries no text and carries no count

### Requirement: Every question put to the door is recorded

The gateway SHALL record every call to the door — the asking application, the number and
the time — append-only, in the manner the rung ledger is recorded.

The door tells one tenant something produced by another tenant's traffic. Without the
record, "who asked about this number" is unanswerable, and it is the first question both
an audit and the person themselves would put. The disclosure records of `messenger-delivery`
account for numbers sent to a vendor; this accounts for numbers asked about, which is a
different set and a larger one.

[unbacked]

#### Scenario: An application asks about a number
- **WHEN** an application calls the door for a number
- **THEN** the asking application, the number and the time are recorded

#### Scenario: The same number is asked about twice
- **WHEN** two applications ask about one number on different days
- **THEN** both questions are recorded, and neither overwrites the other
