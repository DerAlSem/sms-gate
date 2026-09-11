## Purpose

Which way out the gateway reaches a subscriber. There are two — the local modem, which
carries arbitrary text, and a vendor flash call, which carries four digits and nothing else —
and this capability owns the choice between them, the rule that expresses it, what a route is
capable of carrying, and what happens when the choice cannot be honoured. It exists because
the modem route has been withdrawn by operators before, at whole-estate scale, and the
replacement must be reachable by configuration rather than by deploying code during an
outage.

## ADDED Requirements

### Requirement: Every outbound attempt is assigned exactly one route before it leaves

A message or a verification SHALL be assigned a route — `modem` or `call` — before any
transmission is attempted, and that assignment SHALL be recorded against it. It SHALL NOT be
carried by a route other than the one recorded, and SHALL NOT be carried by two.

The recorded route SHALL be readable afterwards, because the cost, the outcome vocabulary and
the meaning of success all differ by route, and none of them can be reconstructed afterwards
from the message alone. It SHALL be a field of the item it belongs to — of the message for a
send, of the verification for a verification — and SHALL stay readable for that item's whole
life.

The route names the way out. The method an application is told about SHALL be derived from the
route by a mapping this capability owns and states, and no other capability SHALL define a
second vocabulary for the same decision. Two words for one choice agree while there are
exactly two routes and disagree on the day there is a third.

[unbacked · no route concept exists in the code today]

#### Scenario: A route is decided and recorded before transmission
- **WHEN** a send or a verification is accepted
- **THEN** its route is decided and stored before any transmission is attempted

#### Scenario: The recorded route is the one used
- **WHEN** an item carries a recorded route of `call`
- **THEN** the modem sender does not pick it up, and the reverse for `modem`

### Requirement: The route is chosen by a configured rule keyed on the recipient's operator

Route selection SHALL be expressed as configuration read at send time, keyed on the
recipient's operator as recorded in `number_operators`. Adding, changing or removing an
operator's route SHALL NOT require a code change or a deploy.

No operator name SHALL appear in a branch in the sending path. The rule's initial content —
МегаФон to `call`, everything else to `modem` — is data, and the change that introduces it is
not permitted to hard-code it, because the event this capability exists for is the next
withdrawal rather than this one.

The rule SHALL NOT be keyed on the originating application. An `app_id` in the rule is the
same hard-coding moved into configuration, and it would route by who is asking rather than by
what is reachable. Who is allowed to spend on a paid route is a separate question from which
route reaches a subscriber, and it is answered below rather than by the rule.

The rule SHALL be held as a typed setting of its own, validated when it is saved: each entry
SHALL name an operator and a route drawn from the known routes, entries SHALL be stripped of
surrounding whitespace on write as well as on read, and an entry naming an unknown route SHALL
be refused at save time rather than discovered at send time. It SHALL NOT be carried by the
existing dispatch-route setting, which requires a webhook URL on every entry and would reject
this rule outright.

A stored rule that cannot be parsed SHALL raise an operator alert and SHALL NOT be treated as
an empty rule. Read as empty, a broken rule sends the whole of an operator's traffic back to
the route that is rejecting it, and does so without a single line in the log — the one failure
mode of this capability that is both total and silent.

The default route SHALL be an entry of the same rule, changeable by the same means. A default
compiled into the sending path is the hard-coding this requirement forbids, merely spelled
differently.

[unbacked]

#### Scenario: An operator with a configured route
- **WHEN** the rule routes МегаФон to `call` and a verification is requested for a МегаФон number
- **THEN** the verification is routed `call`

#### Scenario: An operator with no entry in the rule
- **WHEN** an item is addressed to an operator the rule does not mention
- **THEN** it is routed `modem`, the configured default

#### Scenario: The rule changes without a deploy
- **WHEN** a second operator is added to the rule while the service is running
- **THEN** subsequent items for that operator take the new route, with no restart and no code change

### Requirement: Operator names are matched normalised, never by exact string

An operator name in the rule SHALL be compared against the stored operator case-insensitively
over Cyrillic and after trimming surrounding whitespace. An exact-string comparison SHALL NOT
be used.

This is normative because the data already breaks it: `number_operators` holds МегаФон under
two spellings — `МЕГАФОН` and `МегаФон` — written by the same lookup at different times, and
on 08.09.2026 they covered 120 and 57 numbers respectively. A rule matching one spelling
would route a third of МегаФон subscribers correctly and the rest to a route that has been
rejecting them, and it would do so silently.

The comparison SHALL NOT be built on SQLite's `upper()`, `lower()` or `LIKE`, all of which
are ASCII-only in the shipped build and leave Cyrillic untouched. A measurement taken with
`upper()` on 08.09.2026 undercounted МегаФон traffic by half before the mistake was caught.

[unbacked · evidence for the two spellings: production `number_operators`, read 08.09.2026]

#### Scenario: The other spelling routes identically
- **WHEN** the rule names `МегаФон` and a number's stored operator is `МЕГАФОН`
- **THEN** it takes the same route as a number stored as `МегаФон`

#### Scenario: A stored name with surrounding whitespace
- **WHEN** a stored operator name differs from the rule's only by surrounding whitespace
- **THEN** the rule still matches it

### Requirement: An unknown operator does not block, delay or fail the attempt

The operator lookup is enrichment and SHALL remain so. Nothing SHALL be delayed, held or
failed because the recipient's operator is unknown, unresolved or stale: `record_operator`
never fails a send today, and routing SHALL NOT be the thing that makes it blocking.

When the operator is not known at routing time, the item SHALL take the route the rule
configures for the unknown-operator case and SHALL be recorded as having been routed without a
known operator, so that the case is countable rather than invisible. That route SHALL be part
of the rule's data and SHALL be settable to a refusal, because an unknown operator on a
network being refused is a coin toss with a person's login on it.

A **verification**, whose answer must name the method in the same response, SHALL resolve the
operator synchronously within a bounded time before answering, and SHALL NOT silently answer
with the default route when it could not.

This matters more than it looks: the numbers most likely to lack an operator row are the ones
never messaged before, and a first-time recipient is exactly who a confirmation code is
usually for. Today a send resolves such a number synchronously — `record_operator` is awaited
before the message is created and waits on the lookup up to its timeout — so what is unknown
at routing time is not "every new number" but every number whose lookup failed, and for those
the default route is a guess.

[normative · evidence: app/lookup/operator.py:23-45 (awaited before create_message at app/api/router.py:26, and waits on a cache miss) · conf: high]

#### Scenario: A first-time number whose lookup has not resolved
- **WHEN** a message is addressed to a number with no row in `number_operators`
- **THEN** it goes over the unknown-operator route without being failed for it, and the absence of the operator is recorded

#### Scenario: A verification for a number whose operator will not resolve
- **WHEN** a verification is requested and the operator cannot be resolved within the bound
- **THEN** it takes the configured unknown-operator route, which may be a refusal, and the answer says which method was chosen

#### Scenario: The lookup service is unreachable
- **WHEN** the operator lookup fails for every number for an hour
- **THEN** sending continues over the default route throughout, and nothing is failed for want of an operator

### Requirement: A route carries only what it is capable of carrying

Each route SHALL declare what it can carry. The `modem` route carries arbitrary text. The
`call` route carries a verification code and nothing else: the code is the last four digits of
the calling number, so there is no field in which words, a link or a second sentence could
travel.

An item whose assigned route cannot carry it SHALL NOT be handed to that route, SHALL NOT be
rerouted to another, and SHALL NOT be attempted. It SHALL be refused with a reason naming the
route and what it cannot carry.

The alternative — quietly sending such a message over the modem instead — is the automatic
failover this change refuses, arrived at by accident rather than by decision.

[unbacked]

#### Scenario: Free text addressed to an operator routed to the call route
- **WHEN** an application sends arbitrary text to a number whose operator is routed `call`
- **THEN** the message is refused with a reason naming the route, and no AT command is issued

#### Scenario: A verification addressed to an operator routed to the modem
- **WHEN** a verification is requested for a number whose operator is routed `modem`
- **THEN** it is carried as an SMS, because the modem route can carry a code

### Requirement: A route that cannot be used fails loudly and does not silently fall back

If the assigned route cannot carry an item it is capable of carrying — the vendor is
unreachable, unauthenticated, or out of credit — the item SHALL NOT be transmitted over the
other route. It SHALL follow the retry and expiry rules already governing its kind, and the
operator SHALL be alerted.

Automatic failover between routes is deliberately absent. Escalating into a paid channel
without a spend ceiling turns a modem fault into an unbounded bill, and escalating out of one
turns a vendor outage into traffic on a route an operator has already refused.

That argument applies to the paid route itself, not only to escalation into it. A paid route
SHALL have a configured ceiling on how many paid items it may carry per rolling hour and per
rolling day, counted across every number and every application. A request that would exceed it
SHALL be refused with a reason naming the ceiling, no vendor call SHALL be placed, and the
operator SHALL be alerted on the first refusal within the dedup window. A ceiling reached SHALL
NOT be reported to the application as a vendor failure.

The vendor's own limits do not provide this: they are per number — four a minute, thirty a day
— and a loop over five hundred numbers violates none of them while spending four hundred
roubles. A balance floor is not a ceiling either; it reports money already gone.

[unbacked]

#### Scenario: The vendor rejects our credentials
- **WHEN** the vendor answers with an authentication error
- **THEN** nothing is sent over the modem instead, the operator is alerted, and the existing retry rules apply

#### Scenario: The vendor is out of credit
- **WHEN** the vendor reports insufficient balance
- **THEN** the operator is alerted with that reason, and nothing is rerouted

### Requirement: What the rule costs is countable per operator

The gateway SHALL record, per operator, how many items it refused because the operator's
configured route could not carry them, and that count SHALL be visible to an operator without
reading the database.

A rule set during an outage outlives the outage. When МегаФон starts accepting traffic again,
the rule will still be in force, and the applications that do not send codes will still be
refused — with nothing on any screen to say so. A count is the difference between a rule that
is reviewed and a rule that is forgotten.

[unbacked]

The count SHALL be answerable per application as well as per operator: it decides whether to
call the developer of a particular application or to drop the rule, and "seventy refusals"
answers neither.

The count SHALL NOT be relied upon as evidence that the route has recovered. Once a rule is in
force, the modem route to that operator receives no attempts at all — codes leave by the other
route and text is refused before any AT command — so the one source of proof that the refusal
has ended is the thing the rule switches off. The gateway SHALL therefore retain a way to
observe recovery: either a rate-bounded probe send to that operator over the `modem` route,
counted separately, or an alert once a rule entry has been in force longer than a configured
review period.

A refusal SHALL reach the operator on the configuration the gateway ships with. It SHALL NOT
depend on a notification toggle that is off by default — `notify_send_errors` is such a toggle
— and it SHALL be deduplicated on the operator and the route rather than raised once per
refused message, since the measured traffic is about seventy refusals a month and rising.

[unbacked · the default-off toggle: app/settings_store.py, notify_send_errors]

#### Scenario: Refusals accumulate against an operator
- **WHEN** three applications are refused for one operator over a day
- **THEN** the count for that operator shows three, attributable to that operator rather than to the gateway as a whole

#### Scenario: The refusals are attributable to an application
- **WHEN** an operator asks which applications the refusals came from
- **THEN** the count answers per application as well as per operator

#### Scenario: A rule outlives the outage that justified it
- **WHEN** an operator's entry has been in force longer than the configured review period
- **THEN** the operator is alerted that the rule is still in force and has not been reviewed

#### Scenario: The refusal alert arrives on the shipped configuration
- **WHEN** a message is refused for want of a usable route on a gateway whose settings are untouched
- **THEN** the operator is alerted, once per operator and route within the dedup window
