## Purpose

Verifying that a person holds a particular phone number: the request, the code, the choice of
how to deliver it, and the answer to "is this the code the person was given". It exists
because delivery is not something the gateway can promise — an operator withdrew it for one
whole network on 06.09.2026 and has withdrawn it entirely before — so the application must be
able to ask for a number to be verified without knowing, or caring, which route carried it.

## REMOVED Requirements

### Requirement: A verification request names only the number, and the gateway answers with the method

**Reason**: Its central clause — that the gateway picks a rung, places it, and names in the
creation response "the rung that actually accepted the verification" — describes a mechanism
this change replaces. On the owner's decision of 18.09.2026 the creation response carries the
**routes available**, and the choice among them belongs to the consuming application or to the
person standing at the barrier. Nothing has been attempted by the time that answer is written,
so there is no accepting rung to name.

Two smaller things went with it. Its text referred to the reserve path by the name
`verify-by-inbound-code`, which no longer exists; and it placed the ladder walk inside
acceptance, which the norm on preconditions below removes in favour of proving a route before
offering it rather than attempting it and finding out.

**Migration**: Replaced by `A verification request names only the number, and the gateway
answers with the routes that can carry it`, which keeps every guarantee the removed
requirement made — the number is the only input, the gateway never exposes SIM, modem or
vendor, the application never looks up an operator, and a request the gateway knows it cannot
fulfil is refused rather than accepted to fail later.

## MODIFIED Requirements

### Requirement: The gateway generates the code and never accepts one from the application

The gateway SHALL generate the code. A request that supplies its own code SHALL be rejected
rather than silently honoured.

The reason is not tidiness. The party that answers "is this code correct" must be the party
that knows what to compare against; splitting the secret from its matcher is what makes short
codes unsafe.

A code SHALL be four digits, by the owner's decision of 07.09.2026. Every route **that carries
a code** SHALL be able to carry it: `sendVerificationMessage` accepts a caller-supplied `code`
of four to eight numeric characters, so four is within it, and the `modem` route composes it
into text. Two verifications open at the same time for the same number SHALL NOT carry the
same code, because an answer could then not be attributed to either with certainty.

🔴 **What four digits buy was stated wrongly before this change, and the correction changes
what may be concluded from the length.** The earlier reasoning held that an attacker must
additionally produce a code displayed only on the subscriber's screen. The flow refutes it:
the application displays the code to whoever started the verification, so an attacker who
enters someone else's number reads the code on their own screen. **The code is an attribution
tag, not a second factor.** What it does is bind one arriving event to one open verification
so that an unrelated message from the same person confirms nothing. The defence that actually
binds a person to a number is the origin of the event, on every route without exception, and a
longer code would not add one.

**A route that carries no code at all SHALL be permitted, and SHALL NOT be given one for the
sake of uniformity.** The `inbound_call` rung introduced by this change carries nothing but the
caller's number: there is no text, no digits and nowhere to put them. Its attribution rests on
the pair of the calling number and the single open window, which is why that rung is separately
forbidden from having two windows open on one number. Requiring a code there would mean either
inventing a channel to carry it or recording a code that nothing ever compares against, and
the second is the one that would actually happen.

[unbacked · `inbound_call` capture 18.09.2026 carried `RING` and `+CLIP` and nothing else]

#### Scenario: An application tries to choose the code
- **WHEN** a verification request supplies its own code
- **THEN** the request is rejected

#### Scenario: Two open verifications for one number
- **WHEN** a second verification is opened for a number that already has one open
- **THEN** the two do not share a code

#### Scenario: A route that carries no code
- **WHEN** a verification is confirmed on a route that carries no code
- **THEN** it is confirmed on the origin of the event alone, and no code was generated for it to compare against

### Requirement: The code never appears outside the matcher

A verification's code SHALL NOT appear in an API response, in an operator notification, or in
a log line. It SHALL be readable only by the party that answers `POST /verifications/{id}/check`.

This has to be said out loud because it is the whole guarantee: a code returned to an
application lets that application confirm a verification without the code ever reaching the
person. The gateway also has live paths that would carry it out — notifications relay message
text to Telegram, and the admin console renders it.

**There is exactly one exception, and it is a route, not an application.** On the `inbound_sms`
rung the person is the sender: they read the code from the screen in front of them and text it
to the gateway from the number being verified. The code must therefore be returned to the
owning application, which has no other way to display it. On that rung, and only there, the
code SHALL be returned in the creation response to the owning application and to no one else,
and SHALL still be absent from every operator notification and every log line.

**Where the exception applies, the guarantee this requirement otherwise makes does not exist,
and the spec says so rather than leaving it to be discovered.** A code the requester can read
is a code an attacker who opened the verification can read. That is why `inbound_sms`
confirmation requires **both** halves — the code and the originating number — and why the
number is the half that does the binding. It is also part of why that rung sits last on the
ladder: it is the weakest of them on evidence as well as the only one the subscriber pays for.

The exception SHALL follow the rung, not the application: the same application asking for a
verification on any other route SHALL NOT be given the code.

[unbacked]

#### Scenario: The code is not in the response
- **WHEN** a verification is created or asked about on a route where the gateway sends the code
- **THEN** neither answer carries the code

#### Scenario: The code is not in an alert or a log
- **WHEN** a verification fails and the operator is alerted
- **THEN** the alert and the log name the verification and the reason, and not the code

#### Scenario: The route where the person must type the code back
- **WHEN** a verification is created on the `inbound_sms` rung
- **THEN** the creation response carries the code to the owning application, and the operator notification and the log still do not

#### Scenario: The same application on another rung
- **WHEN** the same application creates a verification on any rung the gateway itself sends
- **THEN** the code is not returned to it

### Requirement: Accepting a verification is bounded and does not hang on the vendor

Every call to the vendor SHALL be bounded by a configurable timeout. `POST /verifications`
SHALL answer with the verification's id and the routes available for it within that bound.

**Acceptance proves preconditions; it does not place anything.** Under this change the ladder
is not walked at accept time: no vendor is asked to send, no call is placed and no message is
composed until the consumer has selected a route. What acceptance costs is the set of
precondition probes, and **that set SHALL be bounded as a whole** rather than probe by probe —
otherwise a slow day at one vendor spends the budget the whole answer was promised in.

A probe that has not answered when the bound is reached SHALL count as **unproven**, and its
route SHALL be absent from the answer. This is the failing direction on purpose: the norm on
preconditions below forbids treating an unread precondition as satisfied, and a bound that
expired is the commonest way for one to go unread.

Placement, once a route is selected, SHALL be bounded by the same configurable timeout. A
vendor that has not answered SHALL leave the verification in a stated in-flight state rather
than failing the request, and its outcome SHALL reach the application by the ordinary push or
poll.

The answer SHALL NOT report the available routes as unknown or as pending. They are the only
part of the response anybody acts on: an application that cannot say whether to watch Telegram
or the phone has nothing to put on the screen, and the whole reason the routes travel in the
creation response is that the person is already standing at the barrier.

That is why an abandoned probe is counted rather than shrugged at. A Gateway that answers
slowly instead of refusing turns the cheap rung off silently: every verification still
completes, by a dearer route, and the only visible symptom is the bill.

The gateway already refuses to make acceptance wait on a slow thing it does not control —
`outbound-send` states that acceptance does not wait for the modem — and it already bounds its
one existing outbound lookup for the same reason.

[unbacked · bounded-external-call precedent: voxlink_timeout in app/settings_store.py]

#### Scenario: A probe is slow
- **WHEN** a route's precondition probe has not answered within the configured bound
- **THEN** the route is absent from the answer, the abandoned probe is counted, and the answer still arrives within the one bound

#### Scenario: One slow probe does not extend the promise
- **WHEN** one probe of several consumes most of the bound
- **THEN** the response still arrives within the one bound, naming the routes that did prove themselves

#### Scenario: The vendor is slow after a route is selected
- **WHEN** the vendor has not answered within the configured bound after the consumer selected its route
- **THEN** the verification is in flight rather than failed, and its outcome arrives by push or poll

### Requirement: The application learns a verification's outcome without polling the modem

The owning application SHALL be able to learn that a verification was confirmed, failed or
expired, by a push to the route already configured for it in `delivery_dispatch`, or by
asking `GET /verifications/{id}`. A push SHALL be distinguishable from a message status push,
so that a receiver cannot mistake a verification id for a message id.

**A confirmation SHALL name the method that proved it**, in the push and in the answer to a
poll alike. The methods are not equally strong and the difference is not a detail: a caller
number is asserted by the network and can be forged, a code typed back from the number being
verified adds an event the attacker must also originate, and a contact shared through a
messenger is vouched for by that messenger. An application whose stakes do not tolerate the
weakest of these SHALL be able to see what it got and refuse it, and SHALL NOT have to assume
the strongest.

A confirmation SHALL be observable within seconds of the confirming event, because the person
waiting for it is standing at a barrier.

[unbacked]

#### Scenario: The outcome is pushed
- **WHEN** a verification is confirmed and the application has a configured route
- **THEN** the application is notified without having asked, the body identifies it as a verification, and it names the method that confirmed

#### Scenario: The outcome is polled
- **WHEN** the application asks for a verification's state after confirmation
- **THEN** it is told the verification is confirmed, when, and by which method

#### Scenario: A weak method is visible as such
- **WHEN** a verification is confirmed by the rung whose only evidence is the caller's number
- **THEN** the named method distinguishes it from a rung that also required a code, so an application may refuse it

## ADDED Requirements

### Requirement: A verification request names only the number, and the gateway answers with the routes that can carry it

`POST /verifications` SHALL accept the number to be verified and nothing else that decides
how. The gateway SHALL answer with the verification's id and with **the routes that can carry
it at that moment**, ordered by cost, cheapest first.

The consuming application MAY take the first route silently or present the list to the person;
both SHALL be served by the same answer. The application SHALL NOT have to look up an operator,
consult a vendor, or hold a table of which networks work.

The answer SHALL describe, for each route offered, what the person must do — expect a message
in Telegram, expect a call and read its last four digits, place a call to this number, text
this code to this number — and SHALL NOT expose which SIM, modem or vendor account is
involved. The bar on disclosure is on identity, not on address: a route that requires the
person to look somewhere, or to address the gateway, SHALL carry what they need to do that and
nothing else about the estate. "Open Telegram" is the address; which Gateway account paid for
it is the identity. The two rungs this change adds are the same case in the other direction and
must name the number the subscriber calls or texts.

This capability SHALL remain the single owner of `POST /verifications`,
`POST /verifications/{id}/check` and `GET /verifications/{id}`, and of the selection door
below. A route is a variant within this capability rather than a capability of its own; a
second capability under the same doors is how one of them silently stops being consulted.

The gateway SHALL NOT accept a verification it already knows it cannot carry. Where no route
can prove its precondition, the answer SHALL say so in the same response, and SHALL NOT open a
verification whose only possible outcome is to expire.

[unbacked · the public API today is `/sms/send` and `/sms/{id}` only]

#### Scenario: Several routes can carry it
- **WHEN** a verification is requested for a number that more than one route can prove it can carry
- **THEN** the answer carries the verification's id and lists those routes in cost order

#### Scenario: The application is not told the mechanism
- **WHEN** any verification is created
- **THEN** the answer says what the person must do for each route offered, and names no SIM, modem or vendor

#### Scenario: No route can carry it
- **WHEN** a verification is requested and no route can prove its precondition
- **THEN** the request is refused in that same answer, and no verification is left open to expire

### Requirement: A route is offered only while its precondition is proven, and the proof has a maximum age

A route SHALL be offered only when the gateway holds **current** evidence that it can work.
Being configured, being enabled, or having worked before SHALL NOT be treated as evidence.

This is the load-bearing norm of this change, and it is normative because the routes it adds
fail **silently**. An incoming call reaches this modem only while IMS is registered; if IMS
goes off — a reset, a firmware reload, a change at the carrier — `RING` simply stops arriving.
There is no error, no rejected request and no log line. Every call verification would hang
until it expired and then report "expired", which is indistinguishable from "the person never
called". With the call as the first rung that is a silent total outage of verification.

The remedy is not a better handler. A route that cannot prove its precondition SHALL be
skipped, so that the ladder starts one rung lower and the person verifies another way without
ever learning there was a problem. A route SHALL NOT be offered and then quietly fail.

The gateway SHALL NOT infer a route's health from the absence of complaints, and SHALL NOT
treat an unread or unreadable precondition as satisfied.

**Evidence SHALL carry the time it was obtained, and SHALL be refused once older than a
configured maximum.** Without a bound, "current evidence" is not defined and the norm above
decides nothing: a reading taken once at boot would satisfy it forever, which is precisely the
failure it exists to prevent. The sibling change `watch-the-voice-route` is required to report
when the voice route was last successfully measured; this capability is the consumer of that
time, and the bound on it belongs here because it is a decision about how stale a proof may be
before a person is sent down a route that no longer works.

⚠️ **Two rungs depend on egress, and egress is not stable.** `ucaller` and `telegram_gateway`
are calls to `api.ucaller.ru` and `gatewayapi.telegram.org`. Telegram is blocked on this host's
backup uplink — measured, not supposed — and reaches it today only through a relay that the
sibling change `carry-telegram-on-any-uplink` records as working but nowhere normalises. The
moment the gateway fails over is therefore the moment two paid rungs may become unreachable,
and it is also the moment things are already degraded. Their preconditions SHALL be
reachability now, not configuration. The general norm covers this; it is named because it is
history rather than foresight.

[unbacked · consumes the last-measured time required by `watch-the-voice-route`; IMS evidence captured live 18.09.2026]

#### Scenario: The voice route loses its precondition
- **WHEN** the modem's IMS registration is not established and a verification is requested
- **THEN** the call route is absent from the answer and a lower rung is offered instead

#### Scenario: The precondition cannot be read at all
- **WHEN** the gateway cannot determine whether a route's precondition holds
- **THEN** that route is treated as unavailable rather than as available

#### Scenario: The proof is stale
- **WHEN** a route's precondition was last proven longer ago than the configured maximum age
- **THEN** the route is absent from the answer, exactly as if the proof had failed

#### Scenario: A vendor route without funds
- **WHEN** a paid route's account cannot fund a verification
- **THEN** that route is absent from the answer rather than attempted and failed

#### Scenario: A vendor route unreachable on the current uplink
- **WHEN** the gateway has failed over to an uplink from which a vendor's API cannot be reached
- **THEN** that route is absent from the answer, and the routes that do not leave the host are still offered

### Requirement: The consumer selects one route, and the gateway never moves to another by itself

A verification SHALL be carried by exactly one route at a time, and that route SHALL be chosen
by the consumer from the offered list, through `POST /verifications/{id}/route`. Only on that
selection SHALL the gateway place a call, send a message or begin waiting for one.

**The gateway SHALL NOT move a verification to another route by itself after the chosen one
fails.** This is the owner's standing decision and it survives the ladder: a list to choose
from is not a licence to hop. A person told to watch Telegram, whose verification silently
becomes an SMS, is looking at the wrong screen while the right one is already showing the
code — and the application has put an instruction on the display that has stopped being true.

A route whose attempt fails SHALL fail the verification with that reason, and the answer SHALL
carry the routes still available so that the consumer may select again. Selecting again SHALL
be the consumer's act, and the reason the previous attempt failed SHALL be visible to it.

Selecting a route that was not offered, or one whose precondition has since stopped holding,
SHALL be refused with that reason rather than attempted.

[unbacked · owner's decision 18.09.2026; the prohibition on silent switching predates the ladder and is unchanged by it]

#### Scenario: The consumer picks a route
- **WHEN** the consumer selects one of the offered routes
- **THEN** the gateway begins carrying the verification by that route and by no other

#### Scenario: The chosen route fails
- **WHEN** the selected route fails to carry the verification
- **THEN** the verification fails with that reason, the remaining available routes are offered, and no other route is attempted without a new selection

#### Scenario: A route that was never offered
- **WHEN** the consumer selects a route that was not in the offered list
- **THEN** the selection is refused with that reason and nothing is placed

#### Scenario: Nothing is placed before a selection
- **WHEN** a verification has been created and no route has been selected
- **THEN** no call has been placed, no message composed and no vendor charged

### Requirement: An inbound call to the gateway's own modem confirms by the caller's number alone

A verification carried by the `inbound_call` rung SHALL be confirmed by an incoming call to the
gateway's own SIM whose caller number is the number being verified and which arrives before the
verification expires. Nothing else about the call SHALL be required, because nothing else is
carried.

This rung SHALL NOT be called `call`. That name is already taken in this capability by
uCaller's flash call, where the vendor dials and this gateway's modem does not participate at
all; two different mechanisms under one name is how an implementer builds the wrong one.

Because a call carries no code, attribution rests entirely on the number and the window.
The gateway SHALL NOT hold two `inbound_call` verifications open for the same number at the
same time: where one is already open, a second request for that number SHALL be answered
without that rung, so that any arriving call belongs to exactly one verification.

A single call SHALL confirm at most once. The modem reports one call as many repetitions —
fifteen `RING` / `+CLIP` pairs in sixteen seconds was measured on 18.09.2026 — and every
repetition after the first SHALL change nothing.

**The gateway SHALL NOT answer the call.** Answering costs the caller money and needs an audio
path this module does not have. Whether the gateway actively ends an unanswered call is
outside this change: `ATH` needs the command port, which the sender holds, and that it rejects
an unanswered incoming call on this firmware is an assertion about the device rather than a
measurement.

🔴 **The consequence is that an unanswered call goes to the carrier's voicemail, and whether
that is a connection the subscriber pays for is NOT established.** This rung sits first on the
ladder because it is believed free to both sides; if the subscriber is charged, the premise
that orders the ladder is wrong for its first rung. The cost claim SHALL NOT be published to
consumers until it is measured.

**The window for this rung SHALL be configurable separately from the capability's default, and
SHALL default to no longer than it.** The rung's residual risk scales with the window: an
attacker can open a verification on a victim's number and, inside the window, give the victim a
reason to call the gateway. A person is easy to persuade to dial a number and nearly impossible
to persuade to text four specific digits, which is the one asymmetry between this rung and the
inbound-message rung and the reason the window is worth shortening here and nowhere else.

`+CLIP` is spoofable. What this rung proves is possession of the number exactly as well as the
network's caller ID can be trusted, and no better. That is stated here rather than buried,
because this rung is first and will carry most verifications.

[normative · live capture 18.09.2026: fifteen `RING`/`+CLIP` pairs in sixteen seconds from the production EP06-E after `AT+QCFG="ims",1` and `AT+CFUN=1,1` · conf: high that the URCs arrive and carry the number; the withheld-number case and the voicemail charge are unmeasured]

#### Scenario: A call from the number being verified
- **WHEN** a call arrives from the number of an open `inbound_call` verification, before it expires
- **THEN** the verification is confirmed, and the method recorded is the inbound call

#### Scenario: One call repeated by the modem
- **WHEN** the modem reports the same call many times in succession
- **THEN** the verification is confirmed once and the repetitions change nothing

#### Scenario: A second verification for a number already being called
- **WHEN** a verification is requested for a number that already has an open `inbound_call` verification
- **THEN** that rung is absent from the offered routes, and two are never open for one number

#### Scenario: A call from an unknown number
- **WHEN** a call arrives from a number with no open verification
- **THEN** nothing is confirmed and the call is recorded as unattributed

#### Scenario: The call is not answered
- **WHEN** any call arrives at the gateway's SIM
- **THEN** the gateway does not answer it, and confirmation does not depend on the call being ended

### Requirement: The caller-ID subscription is a fact the gateway holds, not one it reads back

The gateway SHALL treat the caller-ID subscription as **its own recorded state**: whether
`AT+CLIP=1` was last issued successfully on the link generation now in service. That record,
and not a query to the modem, SHALL be the `inbound_call` rung's precondition on this point.

The reason is that the modem will not answer the question. `AT+CLIP?` reports the subscription
and the network's provisioning of caller ID, and the live modem does not reply to it — given
eight seconds it spent all eight and answered nothing. `AT+CLIP=?` answers at once but says
only that the firmware knows the command, which is not the same fact. A precondition that can
only be read from the device is, on this device, a precondition that can never be read, and the
norm above would then switch the first rung off permanently.

**`AT+CLIP=1` SHALL be re-issued wherever `AT+CNMI` is re-issued.** Recovery cycles `CFUN`,
whether a firmware keeps a URC subscription across that cycle is not something to assume, and
losing this one is silent and total in exactly the way the existing code already refuses to
accept for `CNMI`: the argument written in `soft_recover`'s own docstring applies unchanged to
caller ID, and today the command is not there. After an ordinary recovery IMS still reads
`1,1`, the rung is still offered, and `RING` arrives anonymous.

**A `RING` that is not accompanied by a usable caller number SHALL NOT be read as a fault while
the subscription is recorded as held.** With the subscription held, an anonymous call means the
caller withheld their number or the network could not supply it — an ordinary outcome that
confirms nothing and SHALL NOT be reported as a malfunction. With the subscription recorded as
lost, the rung SHALL NOT have been offered at all. The two cases are separated by what the
gateway knows about itself, not by what it can read from the modem, which is why the record is
the requirement.

**Calls arriving with no usable caller number SHALL be counted, and the count SHALL be visible
to an operator.** The record above can be wrong in one direction — a firmware that drops the
subscription without a `CFUN` cycle leaves the gateway believing it holds something it does
not — and that failure presents as anonymous calls where there were none before. Counted, it is
a rate an operator can see; uncounted, it is the silent outage this change exists to prevent,
reached by a different door. The gateway already keeps this shape for `+CDS`, where a line the
parser cannot read is recorded under its own outcome rather than dropped.

[normative · `CLIP_SUBSCRIBE` at app/modem/at_commands.py:38, issued at init and allowed to fail at app/modem/at_commands.py:706-715; `soft_recover` re-issues `CNMI_SUBSCRIBE` and not `CLIP_SUBSCRIBE` at app/modem/at_commands.py:669-681; `AT+CLIP?` timed out on the live modem, app/modem/manager.py:125-147; unparsable-`+CDS` precedent at app/modem/manager.py:780-792 — all read 18.09.2026]

#### Scenario: A recovery does not take caller ID with it
- **WHEN** the modem is recovered by the cycle that re-issues the URC subscription
- **THEN** the caller-ID subscription is re-issued in the same act, and the rung's recorded precondition still holds

#### Scenario: The subscription could not be issued
- **WHEN** `AT+CLIP=1` fails on the link now in service
- **THEN** the recorded precondition does not hold and the `inbound_call` rung is not offered

#### Scenario: A caller who withheld their number
- **WHEN** a call arrives with no usable caller number while the subscription is recorded as held
- **THEN** nothing is confirmed, no fault is reported, and the call is counted among those carrying no number

#### Scenario: The count makes an invisible loss visible
- **WHEN** calls begin arriving with no usable caller number where previously they carried one
- **THEN** the count is readable by an operator, so a subscription lost without a recovery is observable

### Requirement: A verification whose route stops working ends with a named reason, and a call that arrived during an outage is gone

An open verification whose selected route has lost the precondition it was offered on SHALL be
**terminated with that reason and the application notified**, rather than left to reach its
deadline and be reported as expired.

The norm on preconditions stands at the offer; the proof decays afterwards. The two are not
the same moment and the gap is not small: a verification's default lifetime is five minutes,
while one recovery of this modem is bounded at three hundred seconds of gate-closed time plus a
thirty-second settle, and the hard rung of the escalation exits the process outright. A
recovery can therefore consume a verification's whole window. "Expired" told to a person who
did call, on time, from the right number, is the gateway reporting the one thing that did not
happen.

🔴 **A call that arrives while the modem is out of service is lost, and the gateway SHALL NOT
behave as though it could be recovered.** Inbound SMS has a buffer: messages accumulate in
modem memory while the link is down and are reconciled by a scan when it returns. A call has
none — it exists nowhere in the modem, nowhere in the log, and the caller hears the carrier's
voicemail. The asymmetry is a property of the bearer and cannot be engineered away here; what
this requirement forbids is concealing it. A verification carried by `inbound_call` across an
outage SHALL end with a reason naming the outage, so the person is told to try again rather
than left waiting for an acknowledgement that no longer exists anywhere.

Every writer of a verification's terminal state SHALL notify, on this path as on expiry.

[normative · `scan_inbox` after reconnect at app/modem/manager.py:452; `_RECOVERY_TIMEOUT = 300.0` at app/modem/manager.py:55; `_RECOVERY_SETTLE = 30.0` at app/modem/manager.py:58; `os._exit(1)` at app/modem/manager.py:1236 — read 18.09.2026]

#### Scenario: The route dies under an open verification
- **WHEN** an open verification's selected route loses the precondition it was offered on
- **THEN** the verification ends with that reason and the application is notified, rather than expiring silently

#### Scenario: The person called during a recovery
- **WHEN** a recovery takes the modem out of service for the remainder of an `inbound_call` verification's window
- **THEN** the verification ends naming the outage, and the arriving call is not claimed to be recoverable

#### Scenario: Inbound SMS is still reconciled
- **WHEN** the link returns after an outage during which messages arrived
- **THEN** they are reconciled as they are today, and the difference from the call rung is not papered over

### Requirement: An inbound message confirms only by the pair of number and code

A verification carried by the `inbound_sms` rung SHALL be confirmed only by a message that
**both** originates from the number being verified **and** carries that verification's code.
Neither half alone SHALL confirm anything.

The code binds the arriving message to one open verification; the originating number is what
binds the person to the number. The code is not a secret from whoever opened the verification —
it is displayed to them, which is the exception the code-secrecy requirement now carves out —
so a reader who believes the code is the defence will draw the wrong conclusion about how long
it needs to be. It is four digits because that is enough to attribute, not because it is enough
to withstand a guess.

This rung SHALL be last on the ladder and SHALL NOT be offered where a cheaper one proved
itself. It is the only route on which **the subscriber pays** — one message at their tariff —
and it is the weakest of them on evidence. Both facts point the same way.

A message that carries a valid open code but arrives from another number SHALL confirm nothing
and SHALL NOT consume the verification. A message from the number being verified carrying a
code that is not this verification's SHALL leave the verification pending.

[unbacked · the inbound path exists; nothing consumes it for verification today]

#### Scenario: The right code from the right number
- **WHEN** a message carrying the code arrives from the number being verified
- **THEN** the verification is confirmed and the method recorded is the inbound message

#### Scenario: The right code from another number
- **WHEN** a message carrying a valid open code arrives from a different number
- **THEN** no verification is confirmed and none is consumed

#### Scenario: The wrong code from the right number
- **WHEN** a message arrives from the number being verified carrying a code that is not this verification's
- **THEN** the verification stays pending

#### Scenario: A cheaper rung proved itself
- **WHEN** any cheaper rung proved its precondition for this number
- **THEN** the inbound-message rung is not offered, because it is the only one the subscriber pays for

### Requirement: A verification confirmed by an arriving event is bounded exactly as one confirmed by a check

A verification SHALL be confirmed at most once and SHALL stop being confirmable once it has
expired, **whichever door the confirmation comes through**. An event arriving after the
deadline SHALL NOT revive a verification, and a second confirming event SHALL NOT confirm it
twice.

This has to be said because the guarantee already in this capability is written for
`POST /verifications/{id}/check` — a caller presenting a code — and the two rungs added here
do not use that door. A call from the right number and a message carrying the right code
arrive on their own, from the person rather than from the application, and nothing about them
passes through the endpoint the single-use rule was written on. Left unsaid, "single use" would
hold for the rungs the gateway sends and lapse for the rungs it receives, which are the two
this change exists to add.

Confirmation by an arriving event SHALL be decided by the same single conditional update the
check path uses, on the rows it changed, and SHALL NOT be decided by reading the state and
writing it back. Repetition is not an edge case here: the modem reports one call fifteen times.

**A wrong code arriving from the number being verified SHALL NOT consume an attempt**, and the
difference from the check door is deliberate. The attempt limit exists because four digits are
a small space and a caller at `check` can walk it. On the inbound-message rung the guess must
also originate from the number being verified, so a third party cannot spend the attempts of a
person they are attacking — and the only party who *can* is the person themselves, mistyping.
Counting those would lock a real person out of a barrier they are standing at, which is the
outcome the ownership rule elsewhere in this capability exists to prevent.

[unbacked · atomic-confirmation precedent is this capability's own rule for the check path]

#### Scenario: An event arrives after expiry
- **WHEN** a call from the right number, or a message carrying the right code, arrives after the verification expired
- **THEN** it is not confirmed, the verification stays expired, and the answer says it expired

#### Scenario: A confirming event is repeated
- **WHEN** the same confirming event is received twice
- **THEN** the verification is confirmed once and the second arrival changes nothing

#### Scenario: Two confirming events arrive at once
- **WHEN** two confirming events for one verification are handled concurrently
- **THEN** it is confirmed at most once, whichever of them wins

#### Scenario: The person mistypes the code they were shown
- **WHEN** a message arrives from the number being verified carrying a wrong code
- **THEN** the verification stays pending and no attempt is consumed

### Requirement: Traffic that confirms nothing is kept, and a call is not a message

An inbound message that confirms nothing SHALL still be stored and remain visible exactly as
inbound messages are today. Verification SHALL NOT delete, hide or reclassify traffic that was
not meant for it: the gateway receives ordinary messages from people, and a person replying to
a verification with a question SHALL still be visible in the admin console.

An incoming call SHALL NOT be recorded as an inbound message. It is a different kind of event,
it carries no text, and writing it into the message store would corrupt the record the
paragraph above protects. Calls SHALL be recorded in their own right, including those that
confirmed nothing and those that carried no number, so that "who called us" has an answer.

[unbacked · inbound messages are visible in the admin console today at app/admin/router.py:351]

#### Scenario: An unrelated inbound message
- **WHEN** a message arrives that matches no open verification
- **THEN** it is stored and visible exactly as inbound messages are today

#### Scenario: A call is not filed as a message
- **WHEN** any incoming call is observed
- **THEN** it is recorded as a call and does not appear among inbound messages

### Requirement: The order and membership of the ladder are configuration

The routes the gateway will offer, and the order it offers them in, SHALL be configuration
rather than compiled-in behaviour. Prices move, vendors are added and dropped, and an operator
that refuses delivery today may accept it next month; none of those SHALL require a
deployment.

Changing the order SHALL NOT change what any route proves, and SHALL NOT allow a route to be
offered without its precondition. Removing a route from the configuration SHALL mean it is
never offered, whatever its precondition would have said.

The shipped order is the owner's decision of 18.09.2026 and is recorded as a decision rather
than a measurement: `inbound_call`, then the gateway's own outbound SMS, then `ucaller`, then
`telegram_gateway`, and `inbound_sms` last. uCaller ranks above Telegram Gateway even though
Telegram refunds an undelivered code, which would otherwise make a failure there free; the
counter-argument was raised and declined.

[unbacked · owner's decision 18.09.2026]

#### Scenario: The order is changed
- **WHEN** the configured order is changed and a verification is requested
- **THEN** the answer lists the available routes in the new order, unchanged in every other respect

#### Scenario: A route is removed from the ladder
- **WHEN** a route is removed from the configuration
- **THEN** it is never offered, even where its precondition would have held
