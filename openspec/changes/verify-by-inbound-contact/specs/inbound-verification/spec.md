## Purpose

Verifying that a person holds a particular phone number, and choosing among the routes that
can prove it. It exists because reaching a person is not something the gateway can promise
on any single channel: an operator withdrew delivery for one whole network on 06.09.2026
and has withdrawn it entirely before. The routes available differ in what they cost us, in
what they cost the subscriber, and in how strongly they bind a person to a number. The
owning application asks for a number to be verified and is never required to know which
channels exist, which operator a number is on, or which of them is working today.

## ADDED Requirements

### Requirement: The gateway answers with the routes that can carry the verification, cheapest first

A verification request SHALL name only the number to be verified. The gateway SHALL answer
with the routes available for that number **at that moment**, ordered by cost, and SHALL
NOT require the application to choose among channels it does not know about.

The application MAY take the first route silently or present the list to the person; both
SHALL be supported by the same answer. The application SHALL NOT have to look up an
operator, consult a vendor, or hold a table of which networks work.

The gateway SHALL NOT accept a verification it already knows it cannot carry: if no route
can prove itself, the answer SHALL say so rather than opening a verification that can only
expire.

#### Scenario: Several routes are available
- **WHEN** verification is requested for a number that more than one route can carry
- **THEN** the answer lists those routes in cost order and opens the verification

#### Scenario: The application is not told the mechanism
- **WHEN** any verification is created
- **THEN** the answer describes what the person must do for each route, and does not expose which SIM, modem, vendor or account is involved

#### Scenario: No route can carry it
- **WHEN** verification is requested and no route can prove its precondition
- **THEN** the request is refused in that same answer, and no verification is left open to expire

### Requirement: A route is offered only while its precondition is proven

A route SHALL be offered only when the gateway holds current evidence that it can work.
Being configured, enabled, or having worked before SHALL NOT be treated as evidence.

This is normative because every route in this capability fails **silently**: an incoming
call to a modem whose IMS has switched off produces no error, no log line and no rejected
request — it produces nothing at all, and the verification expires exactly as it would if
the person had never called. A route that cannot prove itself SHALL be skipped so that the
ladder starts one rung lower, and SHALL NOT be offered and then quietly fail.

The gateway SHALL NOT infer a route's health from the absence of complaints, and SHALL NOT
treat an unread or unreadable precondition as satisfied.

#### Scenario: The voice route loses its precondition
- **WHEN** the modem's IMS registration is not established and verification is requested
- **THEN** the call route is absent from the answer and a lower rung is offered instead

#### Scenario: The precondition cannot be read at all
- **WHEN** the gateway cannot determine whether a route's precondition holds
- **THEN** that route is treated as unavailable rather than as available

#### Scenario: A vendor route without funds
- **WHEN** a paid route's account cannot fund a verification
- **THEN** that route is absent from the answer rather than attempted and failed

#### Scenario: A vendor route unreachable on the current uplink
- **WHEN** the gateway has failed over to an uplink from which a vendor's API cannot be reached
- **THEN** that route is absent from the answer, and the routes that do not leave the host are still offered

### Requirement: An inbound call confirms by the caller's number within one open window

A verification offered by the call route SHALL be confirmed by an incoming call whose
caller number is the number being verified and which arrives before the verification
expires. Nothing else in the call SHALL be required, because nothing else is carried.

Because a call carries no code, attribution rests entirely on the number and the window.
Therefore the gateway SHALL NOT hold two call verifications open for the same number at the
same time: when one is already open, a second request for that number SHALL be answered
with a different route, so that any arriving call belongs to exactly one verification.

A single call SHALL confirm at most once. The modem reports one call as many repetitions —
fifteen `RING` / `+CLIP` pairs in sixteen seconds was measured on 2026-09-18 — and every
repetition after the first SHALL change nothing.

A call whose caller number is withheld or unparseable SHALL confirm nothing. This is an
ordinary outcome and SHALL NOT be reported as a fault.

#### Scenario: A call from the number being verified
- **WHEN** a call arrives from the number of an open call verification, before it expires
- **THEN** the verification is confirmed, and the method recorded is the call

#### Scenario: One call repeated by the modem
- **WHEN** the modem reports the same call many times in succession
- **THEN** the verification is confirmed once and the repetitions change nothing

#### Scenario: A second verification for a number already being called
- **WHEN** a call verification is requested for a number that already has one open
- **THEN** the answer offers a different route, and two call verifications are never open for one number

#### Scenario: A call from an unknown number
- **WHEN** a call arrives from a number with no open verification
- **THEN** nothing is confirmed and the call is recorded as unattributed

#### Scenario: A withheld caller number
- **WHEN** a call arrives carrying no usable caller number
- **THEN** nothing is confirmed and no fault is reported

### Requirement: An inbound message confirms only by the pair of number and code

A verification offered by the inbound-message route SHALL be confirmed only by a message
that **both** originates from the number being verified **and** carries that verification's
code. Neither half alone SHALL confirm anything. The gateway SHALL generate the code; an
application-supplied code SHALL NOT be accepted.

The code's purpose is **attribution, not secrecy.** It is not hidden from an attacker — the
application displays it to whoever started the verification — and it SHALL NOT be relied on
as a second factor. What it does is bind one arriving message to one open verification, so
that an unrelated message from the same person confirms nothing. This is stated normatively
because a reader who believes the code is a secret will draw the wrong conclusion about how
long it needs to be.

#### Scenario: The right code from the right number
- **WHEN** a message carrying the code arrives from the number being verified
- **THEN** the verification is confirmed

#### Scenario: The right code from another number
- **WHEN** a message carrying a valid open code arrives from a different number
- **THEN** no verification is confirmed

#### Scenario: The wrong code from the right number
- **WHEN** a message arrives from the number being verified carrying a code that is not this verification's
- **THEN** the verification stays pending

#### Scenario: An application tries to choose the code
- **WHEN** a verification request supplies its own code
- **THEN** the request is rejected rather than silently honoured

### Requirement: A verification is single-use and time-bound

A verification SHALL expire, and SHALL stop being confirmable once it has expired or once
it has been confirmed. A confirmation arriving after expiry SHALL NOT revive it, and a
second confirming event SHALL NOT confirm it twice.

Codes SHALL be reusable across time — a short code is a small space and forbidding reuse
forever would exhaust it — but two verifications open **at the same time for the same
number** SHALL NOT carry the same code, for the same reason two call verifications may not
be open at once: an arriving event must be attributable to exactly one.

#### Scenario: A replayed confirmation
- **WHEN** the same confirming event is received twice
- **THEN** the verification is confirmed once and the second arrival changes nothing

#### Scenario: A confirmation after expiry
- **WHEN** a correct confirming event arrives after the verification expired
- **THEN** the verification stays expired and is not confirmed

#### Scenario: Two open verifications for one number
- **WHEN** a second verification is opened for a number that already has one open
- **THEN** the two are distinguishable, and never share a code or a route that cannot tell them apart

### Requirement: The application learns the outcome and which method proved it

The owning application SHALL be able to learn that a verification was confirmed, by a push
to its configured route or by asking for the verification's current state. A confirmation
SHALL be observable within seconds of the confirming event, because the person waiting for
it is standing at a barrier.

The answer SHALL name **which method confirmed it**. The methods are not equally strong: a
caller number is asserted by the network and can be forged, while a contact shared through
a messenger is vouched for by that messenger. An application whose stakes do not tolerate
the weaker evidence SHALL be able to see what it got and refuse it, and SHALL NOT have to
assume the strongest.

#### Scenario: Confirmation is pushed
- **WHEN** a verification is confirmed and the application has a configured route
- **THEN** the application is notified without having asked, and the notification names the method

#### Scenario: Confirmation is polled
- **WHEN** the application asks for a verification's state after confirmation
- **THEN** it is told the verification is confirmed, when, and by which method

### Requirement: Traffic that confirms nothing is kept, and a call is not a message

An inbound message that confirms nothing SHALL still be stored and remain visible exactly
as inbound messages are today. Verification SHALL NOT delete, hide or reclassify traffic
that was not meant for it: the gateway receives ordinary messages from people, and a person
replying to a verification with a question SHALL still be visible in the admin console.

An incoming call SHALL NOT be recorded as an inbound message. It is a different kind of
event, it carries no text, and writing it into the message store would corrupt the record
the previous paragraph protects. Calls SHALL be recorded in their own right, including
those that confirmed nothing, so that "who called us" has an answer.

#### Scenario: An unrelated inbound message
- **WHEN** a message arrives that matches no open verification
- **THEN** it is stored and visible exactly as inbound messages are today

#### Scenario: A call is not filed as a message
- **WHEN** any incoming call is observed
- **THEN** it is recorded as a call and does not appear among inbound messages

### Requirement: The order and membership of the ladder are configuration

The routes the gateway will offer, and the order it offers them in, SHALL be configuration
rather than compiled-in behaviour. Prices change, vendors are added and dropped, and an
operator that refuses delivery today may accept it next month; none of those SHALL require
changing code.

Changing the order SHALL NOT change what any route proves, and SHALL NOT allow a route to
be offered without its precondition.

#### Scenario: The order is changed
- **WHEN** the configured order of routes is changed and a verification is requested
- **THEN** the answer lists the available routes in the new order, unchanged in every other respect

#### Scenario: A route is removed from the ladder
- **WHEN** a route is removed from the configuration
- **THEN** it is never offered, even where its precondition would have held
