## Purpose

Verifying that a person holds a particular phone number: the request, the code, the choice of
how to deliver it, and the answer to "is this the code the person was given". It exists
because delivery is not something the gateway can promise — an operator withdrew it for one
whole network on 06.09.2026 and has withdrawn it entirely before — so the application must be
able to ask for a number to be verified without knowing, or caring, which route carried it.

## ADDED Requirements

### Requirement: A verification request names only the number, and the gateway answers with the method

`POST /verifications` SHALL accept the number to be verified and nothing else that decides
how. The gateway SHALL choose the method from the routing rule, SHALL return that choice in
the same response together with the verification's id, and SHALL NOT accept a request it
already knows it cannot fulfil in order to fail it afterwards.

The response SHALL describe what the person must do — expect a call and read its last four
digits, or expect an SMS — and SHALL NOT expose which SIM, modem or vendor is involved. The
application SHALL NOT have to look up an operator or hold a table of which networks work.

The bar on disclosure is on identity, not on address: a method that requires the person to
address the gateway SHALL carry the number to address and nothing else about the estate. The
reserve path `verify-by-inbound-code` is that case — it must name the number the subscriber
texts — and this capability SHALL remain the single owner of `POST /verifications`,
`POST /verifications/{id}/check` and `GET /verifications/{id}`, a method being a variant
within it rather than a capability of its own.

[unbacked · the public API today is `/sms/send` and `/sms/{id}` only]

#### Scenario: A number on an operator routed to the call
- **WHEN** a verification is requested for a МегаФон number while the rule routes МегаФон to `call`
- **THEN** the response carries the verification id and names the call method, and the call is placed

#### Scenario: A number on an operator routed to the modem
- **WHEN** a verification is requested for a number on any other operator
- **THEN** the response names the SMS method, and the code is sent from the gateway's own number as it is today

#### Scenario: The application is not told the route
- **WHEN** any verification is created
- **THEN** the response describes what the person must do, and names no SIM, modem or vendor

### Requirement: The gateway generates the code and never accepts one from the application

The gateway SHALL generate the code. A request that supplies its own code SHALL be rejected
rather than silently honoured.

The reason is not tidiness. The code has to be the last four digits of the number the vendor
calls from, which the vendor allocates; and the party that answers "is this code correct" must
be the party that knows what to compare against. Splitting the secret from its matcher is what
makes short codes unsafe.

A code SHALL be four digits, by the owner's decision of 07.09.2026. Two verifications open at
the same time for the same number SHALL NOT carry the same code, because an answer could then
not be attributed to either with certainty.

[unbacked]

#### Scenario: An application tries to choose the code
- **WHEN** a verification request supplies its own code
- **THEN** the request is rejected

#### Scenario: Two open verifications for one number
- **WHEN** a second verification is opened for a number that already has one open
- **THEN** the two do not share a code

### Requirement: The gateway answers whether a code is correct, and the answer is single-use and bounded

`POST /verifications/{id}/check` SHALL take a code and answer whether it is this
verification's. Confirming SHALL be possible once: a verification already confirmed, expired,
or out of attempts SHALL NOT be confirmed again, and the answer SHALL say which of those it
is rather than a bare no.

A verification SHALL expire, and SHALL allow a bounded number of wrong answers before it stops
accepting any. Four digits is a small space and the only thing standing between it and a
guessing attack is the attempt limit; without one, a caller reaches the right answer in a few
thousand requests.

Confirming a verification and consuming an attempt SHALL each be decided by a single
conditional update, on the rows it changed, and SHALL NOT be decided by reading the state and
writing it back. The gateway already refuses that shape elsewhere for the same reason: a
concurrent writer moves the state between the read and the write, and a person at a barrier
double-taps `Confirm` as a matter of course.

[unbacked]

#### Scenario: The right code
- **WHEN** the code the person read from the calling number is checked
- **THEN** the verification is confirmed, and the time of confirmation is recorded

#### Scenario: The same code checked twice
- **WHEN** a confirmed verification is checked again with the same code
- **THEN** it is not confirmed a second time, and the answer says it was already confirmed

#### Scenario: Repeated wrong answers
- **WHEN** wrong codes are checked up to the configured limit
- **THEN** further checks are refused for that verification even if the right code follows

#### Scenario: Two checks arrive at once
- **WHEN** two checks for the same verification are handled concurrently
- **THEN** it is confirmed at most once and one attempt is consumed at most once, whichever of them wins

#### Scenario: The right code after expiry
- **WHEN** the correct code is checked after the verification expired
- **THEN** it is not confirmed, and the answer says it expired

### Requirement: A placed call is not a delivered code, and the two are not reported as one

On the call route the vendor reports whether it managed to place the call. That is all it
reports: uCaller's `call_status` is `-1` while the outcome is still being established, `0`
when it could not connect, and `1` when the call was made. It says nothing about whether the
subscriber saw the number or read the digits.

The gateway SHALL treat `call_status: 1` as the analogue of an SMS having been sent, not of a
code having been received, and SHALL NOT report a verification as confirmed on the strength of
it. A verification SHALL become confirmed only through the check above.

The gateway SHALL bound how long it waits for `-1` to resolve and SHALL record an unresolved
outcome as unknown rather than as either success or failure. The vendor's documentation gives
a resolution time of one second to one minute.

The code a verification is matched against SHALL be the one the vendor reports for that call,
not the one requested. `code` is optional on `initCall` and `getInfo` reports a `code` of its
own; nothing in the reference promises the vendor can always allocate a number ending in the
four digits we asked for. Where the reported code differs from the requested one the gateway
SHALL adopt the reported code or fail the verification with that reason, and SHALL NOT match
against digits the vendor never dialled — that failure is indistinguishable, from the outside,
from every subscriber suddenly typing the wrong code, and every instance of it is paid for.

[unbacked · vendor reference, uCaller `getInfo`, read 08.09.2026 — no live sample captured]

#### Scenario: The call is placed
- **WHEN** the vendor reports `call_status: 1`
- **THEN** the verification is open and awaiting a code, and it is not reported as confirmed

#### Scenario: The call could not be connected
- **WHEN** the vendor reports `call_status: 0`
- **THEN** the verification fails with that reason and the application is told, so it can offer the person another attempt

#### Scenario: The vendor called from a number that does not carry our code
- **WHEN** the code the vendor reports for a call differs from the one the gateway supplied
- **THEN** the verification matches the reported code or fails with that reason, and the operator is alerted

#### Scenario: The outcome does not resolve
- **WHEN** `call_status` is still `-1` when the wait bound is reached
- **THEN** the outcome is recorded as unknown, and it is neither counted as a placed call nor as a failure

### Requirement: The vendor's per-number limits are enforced here, before the vendor enforces them

uCaller allows four authorisations per number per minute with at least fifteen seconds between
them, and thirty per number per day; exceeding them blocks that number for ten hours. The
gateway SHALL enforce these limits itself and refuse the request with a reason, rather than
letting the vendor discover them.

A limit discovered at the vendor costs the subscriber ten hours during which they cannot log
in at all — a far worse outcome than being told to wait fifteen seconds. The limits SHALL be
configurable, because they are the vendor's numbers and not ours, and a vendor may change
them.

The daily ceiling SHALL state the window it counts in, and that window SHALL be configurable
to match the vendor's. Where ours and the vendor's cannot be reconciled the gateway SHALL
count on the stricter of the two. This is not pedantry: this database stores naive UTC and the
vendor is Russian, so a calendar day read in the wrong zone leaves a three-hour window in which
our counter has reset and theirs has not — and the gateway confidently places the call that
costs the subscriber ten hours.

[unbacked · vendor reference, read 08.09.2026]

#### Scenario: A second attempt too soon
- **WHEN** a verification is requested for a number eight seconds after the previous one
- **THEN** the request is refused with a reason naming the wait, and no call is placed

#### Scenario: The daily ceiling
- **WHEN** a number reaches the configured daily ceiling
- **THEN** further requests for it are refused until the ceiling resets, and the operator can see that it happened

### Requirement: A repeat uses the vendor's free repeat, and a retried request does not buy a second call

When a person did not get the call and asks again within the vendor's repeat window, the
gateway SHALL use the vendor's repeat of the existing verification rather than opening a new
one. uCaller allows two repeats per verification at no charge, no sooner than sixty seconds
after the original.

Every call to the vendor SHALL carry an idempotency key unique to the **attempt** — the
original call and each repeat being separate attempts — so that a retry of our own HTTP
request (a timeout, a restart mid-flight) cannot place and pay for a second call, while a
legitimate repeat remains possible. A key unique to the verification cannot do both jobs at
once: deduplicating our retry by it would also deduplicate the repeat.

Cost is not the only reason. A second call for the same verification carries a *different*
last four digits, and the person is then reading digits from one call while the gateway
expects the other. It follows that a repeat SHALL be offered only once it is established from
a captured live sample that the vendor repeats from the same number; until that is
established the gateway SHALL open a new verification instead and SHALL tell the application
that the digits have changed.

When the vendor's free repeats for a verification are exhausted, a further request SHALL open
a new, paid verification whose code differs, SHALL close the previous one so that its code
confirms nothing, and SHALL tell the application that the identifier changed. Otherwise a late
call from the closed verification hands the person digits that spend one of their few
attempts.

A repeated request for a number that already has an open verification SHALL answer with that
verification's id and its method rather than with a bare refusal. The idempotency key protects
the vendor's side of a lost response; it does nothing for an application that lost ours and is
left holding a ringing phone with no id to check a code against.

[unbacked · vendor reference: `initRepeat`, `unique` (UUID v4), read 08.09.2026]

#### Scenario: The person asks for the call again
- **WHEN** a repeat is requested more than sixty seconds after the original and within the free allowance
- **THEN** the vendor's repeat is used, the code stays the same, and nothing is charged

#### Scenario: Our own request is retried after a timeout
- **WHEN** the gateway retries a vendor call it is not sure was received
- **THEN** the idempotency key prevents a second call being placed and charged

#### Scenario: The free repeats are used up
- **WHEN** a person asks for the call again after the vendor's free repeats are exhausted
- **THEN** a new paid verification with a different code is opened, the previous one is closed, and the application is told the identifier changed

#### Scenario: The application lost our response and asks again
- **WHEN** a verification is requested for a number that already has one open
- **THEN** the answer carries the open verification's id and method instead of a bare refusal

### Requirement: The application learns a verification's outcome without polling the modem

The owning application SHALL be able to learn that a verification was confirmed, failed or
expired, by a push to the route already configured for it in `delivery_dispatch`, or by
asking `GET /verifications/{id}`. A push SHALL be distinguishable from a message status push,
so that a receiver cannot mistake a verification id for a message id.

[unbacked]

#### Scenario: The outcome is pushed
- **WHEN** a verification is confirmed and the application has a configured route
- **THEN** the application is notified without having asked, and the body identifies it as a verification

#### Scenario: The outcome is polled
- **WHEN** the application asks for a verification's state after confirmation
- **THEN** it is told the verification is confirmed, and when

### Requirement: What verifications cost is visible before the bill is

The gateway SHALL record the vendor's reported cost of each paid verification and SHALL raise
an operator alert when the vendor's reported balance falls below a configured floor.

A prepaid vendor fails by running out, and it fails at the worst moment: the balance is fine
until it is not, and the first symptom is every verification failing at once. `getInfo`
returns both `cost` and `balance` on every enquiry, so this costs nothing extra to know.

[unbacked · vendor reference: `getInfo` returns `cost` and `balance`, read 08.09.2026]

#### Scenario: The balance runs low
- **WHEN** the vendor's reported balance falls below the configured floor
- **THEN** the operator is alerted once within the dedup window, before verifications start failing

#### Scenario: A month's spend is answerable
- **WHEN** an operator asks what the call route cost last month
- **THEN** the answer comes from recorded per-verification costs, not from the vendor's invoice

#### Scenario: The spend is answerable per application
- **WHEN** an operator asks which application spent it
- **THEN** the answer comes from the application recorded on each verification

### Requirement: A verification is a stored thing with an owner, a deadline and a secret that stops existing

A verification SHALL be persisted before the vendor is called, carrying at minimum its id, the
application that requested it, the normalised number, the route assigned to it, the code, the
attempts spent, the deadline, its state, and the vendor's identifiers and reported cost.

It SHALL belong to the application that created it. `GET /verifications/{id}` and
`POST /verifications/{id}/check` SHALL answer only to that application, and SHALL be
indistinguishable from a missing verification to any other. Without this, one application's
token walks another's verifications by id — and worse than reading them, it spends their
attempts, locking a real person out of a barrier they are standing at. The gateway already
holds this line for messages, where the scoped read is the default and the unscoped one exists
separately and only for the admin console.

A verification's state SHALL survive a restart: one interrupted while awaiting the vendor's
outcome SHALL be resolved or recorded as unknown by a sweep, not lost with the process.

A verification SHALL be deleted once past a configured retention, and its code SHALL stop
being readable once the verification is confirmed, expired or out of attempts. This row holds
a subscriber's number together with a live secret; every other store in this gateway that
holds subscriber data has a retention rule, and this one has the strongest reason for it.

The recorded cost SHALL be answerable per application as well as in total.

[unbacked · no verification storage exists; retention precedent at app/db/queries.py — inbound_seen and delivery_reports]

#### Scenario: The state outlives the process
- **WHEN** the gateway restarts while a verification awaits the vendor's outcome
- **THEN** the verification is still there and is resolved or recorded as unknown, not silently dropped

#### Scenario: Another application asks about a verification
- **WHEN** an application that did not create a verification asks for it or checks a code against it
- **THEN** it is answered as if no such verification exists, and no attempt is spent

#### Scenario: A finished verification stops holding a usable secret
- **WHEN** a verification is confirmed, expires or runs out of attempts
- **THEN** its code is no longer readable, and the row is removed once past the configured retention

### Requirement: The code never appears outside the matcher

A verification's code SHALL NOT appear in an API response, in an operator notification, or in
a log line. It SHALL be readable only by the party that answers `POST /verifications/{id}/check`.

This has to be said out loud precisely because the reserve path says the opposite: the frozen
`verify-by-inbound-code` returns the code to the application by design, because there the
person reads it from their own screen. Whoever implements against both contracts will carry
that habit across, and a code returned here lets an application confirm a verification without
the call ever reaching the person — which is the whole guarantee, gone. The gateway also has
live paths that would carry it out: notifications relay message text to Telegram, and the
admin console renders it.

[unbacked]

#### Scenario: The code is not in the response
- **WHEN** a verification is created or asked about
- **THEN** neither answer carries the code

#### Scenario: The code is not in an alert or a log
- **WHEN** a verification fails and the operator is alerted
- **THEN** the alert and the log name the verification and the reason, and not the code

### Requirement: A verification request passes the same gates a send passes

`POST /verifications` SHALL normalise the number by the rule `POST /sms/send` applies, and
SHALL refuse a number the gateway holds blocked, with the same vocabulary and without creating
a verification or placing a call.

Every existing door into sending checks the blacklist — the API, the admin console's resend
and reply, the Telegram reply path — and the sender checks it again before a retry. A new
public door that skips it is a hole, not a simplification. Normalisation matters for a second
reason beyond consistency: the operator table is keyed on the normalised number, so an
unnormalised one resolves to no operator at all and takes the default route — which for a
МегаФон subscriber is the route that does not work.

A failed call SHALL NOT count toward the destination's permanent-failure threshold: the call
route does not share the modem's evidence about a number, and a number the modem has been
failing to reach is exactly the number this route exists to serve.

[unbacked · gates live in the handlers today: app/api/router.py:21, app/api/schemas.py:19-22]

#### Scenario: A blocked number is asked to verify
- **WHEN** a verification is requested for a number the gateway holds blocked
- **THEN** it is refused with that reason, no verification is created and no call is placed

#### Scenario: The number arrives in a different shape
- **WHEN** a verification is requested with a number written unnormalised
- **THEN** it is normalised before the operator is looked up, exactly as a send would normalise it

#### Scenario: A call that did not connect does not blacklist the number
- **WHEN** a call route verification fails to connect
- **THEN** the number's permanent-failure count is unchanged

### Requirement: Accepting a verification is bounded and does not hang on the vendor

Every call to the vendor SHALL be bounded by a configurable timeout. `POST /verifications`
SHALL answer with the verification's id and its method within that bound; a vendor that has
not answered SHALL leave the verification in a stated in-flight state rather than failing the
request, and its outcome SHALL reach the application by the ordinary push or poll.

The gateway already refuses to make acceptance wait on a slow thing it does not control —
`outbound-send` states that acceptance does not wait for the modem — and it already bounds its
one existing outbound lookup for the same reason. Without a bound the parking app's HTTP
request hangs on uCaller's, the person watches a spinner, the app times out its own client,
and the call may well have been placed and charged in the meantime.

[unbacked · bounded-external-call precedent: voxlink_timeout in app/settings_store.py]

#### Scenario: The vendor is slow
- **WHEN** the vendor has not answered within the configured bound
- **THEN** the request is answered with the verification's id and method, and the verification is in flight rather than failed

### Requirement: An open verification ends by itself, and its end is announced

A periodic sweep SHALL move open verifications past their deadline to expired, and the owning
application SHALL be notified once per verification when that happens. Every writer of a
verification's state SHALL notify, and a test SHALL enumerate those writers and fail when one
of them does not.

An expiry computed only when somebody next asks never fires for the case that matters: the
person who never got the call has no reason to come back with a code, so nothing triggers the
lazy check, and the application holds a session open forever waiting for an answer that will
not be computed. The gateway resolved exactly this for messages with a sweep and a
notification per row, and `delivery-dispatch` already carries the enumerating test as a
standing requirement.

[unbacked · sweep precedent: the message expiry sweep, app/db/queries.py:749-769]

#### Scenario: Nobody ever comes back with a code
- **WHEN** a verification passes its deadline with no check attempted
- **THEN** the sweep expires it and the application is notified once

### Requirement: A verification carried by the modem takes that message's outcome

A verification on the `modem` route SHALL own the message it creates: the message SHALL be
marked as belonging to a verification, and its status changes SHALL NOT be pushed to the
application as message statuses. The verification's own outcome SHALL be derived from them —
`sent` leaves it open, `failed` or `expired` fails it with that reason and notifies the
application under the verification's id.

The call route has this: `call_status: 0` fails the verification and the application is told.
The modem route, which carries every operator except the one this change moves, has no such
rule — and the modem has a dozen ways to fail that are already named and handled. Without
this, a code the network has already refused to carry leaves the person waiting at the barrier
until a deadline, and the application learns nothing until then. It also closes the hole in the
other direction: the live rule that every status writer notifies would otherwise push a raw
message id to an application that only ever asked for a verification.

[unbacked · modem failure vocabulary at app/modem/errors.py:19-38]

#### Scenario: The SMS carrying a code fails
- **WHEN** the message carrying a verification's code is failed or expired by the sender
- **THEN** the verification fails with that reason and the application is notified under the verification's id

#### Scenario: A verification's message does not notify as a message
- **WHEN** the status of a message belonging to a verification changes
- **THEN** no message-status push is sent for it; the verification's own notification carries the outcome
