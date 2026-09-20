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

The response SHALL describe what the person must do — expect a message in Telegram, or expect a
call and read its last four digits, or expect an SMS — and SHALL NOT expose which SIM, modem or
vendor account is involved. The application SHALL NOT have to look up an operator or hold a
table of which networks work.

The bar on disclosure is on identity, not on address: a method that requires the person to look
somewhere, or to address the gateway, SHALL carry what they need to do that and nothing else
about the estate. "Open Telegram" is the address; which Gateway account paid for it is the
identity. The reserve path `verify-by-inbound-contact` is the same case in the other direction —
it must name the number the subscriber texts — and this capability SHALL remain the single
owner of `POST /verifications`, `POST /verifications/{id}/check` and
`GET /verifications/{id}`, a method being a variant within it rather than a capability of its
own.

Because the paid route is a ladder, the method named in the response is the rung that actually
accepted the verification, not the first rung attempted. An application told to expect a
Telegram message for a person the Gateway declined would put the wrong instruction on the
screen, which is worse than no instruction: the person waits in the wrong place while a phone
they are holding rings.

[unbacked · the public API today is `/sms/send` and `/sms/{id}` only]

#### Scenario: A number on an operator routed to the call
- **WHEN** a verification is requested for a МегаФон number while the rule routes МегаФон to `[tg_gateway, call]` and the Gateway declines the subscriber
- **THEN** the response carries the verification id and names the call method, and the call is placed

#### Scenario: The rung that accepted is the method reported
- **WHEN** the same request is made for a subscriber the Gateway confirms
- **THEN** the response names the Telegram method rather than the call, and no call is placed

#### Scenario: A number on an operator routed to the modem
- **WHEN** a verification is requested for a number on any other operator
- **THEN** the response names the SMS method, and the code is sent from the gateway's own number as it is today

#### Scenario: The application is not told the route
- **WHEN** any verification is created
- **THEN** the response describes what the person must do, and names no SIM, modem or vendor

### Requirement: The gateway generates the code and never accepts one from the application

The gateway SHALL generate the code. A request that supplies its own code SHALL be rejected
rather than silently honoured.

The reason is not tidiness. The party that answers "is this code correct" must be the party
that knows what to compare against; splitting the secret from its matcher is what makes short
codes unsafe.

A code SHALL be four digits, by the owner's decision of 07.09.2026. Every route SHALL be able
to carry it: `sendVerificationMessage` accepts a caller-supplied `code` of four to eight
numeric characters, so four is within it, and the `sms_out` route composes it into text. Two
verifications open at the same time for the same number SHALL NOT carry the same code, because
an answer could then not be attributed to either with certainty.

Where a route's vendor can also generate a code of its own, the gateway SHALL NOT let it. On
`tg_gateway` this means `code` SHALL always be supplied and `code_length` SHALL NOT be used:
delegating generation puts the secret at the vendor and leaves the matcher here with nothing
to compare against, which is the same split this requirement forbids on the application's side.

The `flash_call` route is the one exception, and it runs the other way: there the code is the last
four digits of a number the vendor allocates, so what the gateway supplies is a request rather
than a decision. That case is governed below.

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

**Both bounds SHALL be settings, and their shipped defaults SHALL be five minutes and five
attempts — the owner's decision of 18.09.2026.** Neither number is arbitrary and neither is
free to drift:

- five minutes is `delivery_timeout_seconds`, which is 300 in `app/settings_store.py`. A
  verification that outlives the message carrying it would sit open waiting on an outcome the
  sender has already abandoned;
- five attempts is `blacklist_threshold`, which is 5 in the same table. A person who has
  exhausted an operator's patience five times over is the same person either way, and two
  different numbers for "enough" is two support answers to one question;
- from below, five minutes is propped by the vendor's free repeat, which cannot be used sooner
  than sixty seconds after the original: a window shorter than a few multiples of that leaves
  the free remedy unreachable;
- from above, it is propped by the vendor's ten-hour block on a number that exceeds its
  per-number limits. Every minute a verification stays open is a minute in which the person
  asks again, and asking again is what walks into that block.

⚠️ **This diverges from the integration contract drafted for the parking developer**, which
states ten minutes to the end user and carries an `expires_at`. 🔴 **That draft was never sent** —
the owner's word, 18.09.2026 — so there is no agreement to renegotiate and no party waiting on
one: the draft moves to meet this norm before it is handed over, which the owner will do once
the shape is settled. Task 3.1 carries it. Nothing here may be built as though a developer had
agreed to anything.

Where a route's vendor holds its own expiry, the gateway SHALL set it from the verification's
remaining lifetime rather than from a constant of its own. On `tg_gateway` that is `ttl`, whose
supported range is 30 to 3600 seconds, so five minutes sits inside it; setting it to anything
longer than the verification would also forfeit the automatic refund on non-delivery, which is
tied to that same `ttl`.

The attempt count SHALL be kept here and SHALL NOT be delegated to a vendor that offers to keep
it. Telegram's `checkVerificationStatus` will match a code and report
`code_max_attempts_exceeded` on a counter of its own; using it would mean two authorities
counting the same thing, on different routes, with different limits, and a person exhausting
one while the other still says four left. The gateway matches the code it generated.

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

#### Scenario: The vendor's expiry follows the verification's
- **WHEN** a verification is handed to `tg_gateway`
- **THEN** the `ttl` sent with it is the verification's remaining lifetime, not a constant of the adapter's own

#### Scenario: The attempt limit is not the vendor's
- **WHEN** a verification carried by `tg_gateway` is checked with a wrong code
- **THEN** the attempt is consumed against this gateway's limit, and the vendor's own code-checking endpoint is not called

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

The rest of this requirement governs the `flash_call` route alone, and SHALL NOT be carried across to
the other routes. On `tg_gateway` and on `sms_out` the code is the gateway's own from end to end,
and a rule that prefers a vendor-reported code there would prefer a value no vendor sets.

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

### Requirement: Telegram's delivery report says more than a call's, and still does not say the code was used

On `tg_gateway` the vendor reports a `delivery_status` whose `status` is one of `sent`,
`delivered`, `read`, `expired` or `revoked`. The gateway SHALL record it and SHALL treat
`delivered` as the analogue of a delivery report on the modem route — evidence the message
arrived — and `read` as evidence it was opened. It SHALL treat neither as confirmation: a
verification SHALL become confirmed only through a correct code at `POST /verifications/{id}/check`.

`expired` SHALL fail the verification with that reason. The gateway SHALL record that the fee
for it was refunded, which the vendor reports as `is_refunded` on the same object, rather than
assuming either that it was or that it was not.

**When a verification becomes terminal — confirmed, expired, or out of attempts — the gateway
SHALL ask the vendor to revoke any message still outstanding for it** with
`revokeVerificationMessage`, because the call is free and may yet do something. It SHALL NOT
treat the vendor's answer as evidence that the code stopped being readable, and **no guarantee
of this capability SHALL rest on revocation succeeding.**

🔴 **Measured 18.09.2026, twice, and it is the reason this requirement is worded that way.**
`revokeVerificationMessage` answered `{"ok": true, "result": true}` both for a message the
subscriber had already read and for one revoked within a second of delivery, before it could be
read. In both trials the message stayed visibly in the chat, and `delivery_status.status`
remained `read` and `delivered` respectively — it never became `revoked`. The vendor's `true`
therefore reports that the request was accepted, not that anything was withdrawn, and the two
are indistinguishable through the API.

🟢 **And the vendor says why, which a re-reading of its reference on 20.09.2026 established:**
*"this does not guarantee that the message will be deleted. For example, if the message has
already been delivered or read, it will not be removed."* So the inertness is documented
behaviour rather than a defect, and the bound on it is now known: **what was never tried is
revoking a message that had not yet been delivered.** All three trials — two free, one billed
— revoked something already delivered or read, which is precisely the case the vendor excludes.
The requirement stands unchanged, because a guarantee that holds only when delivery has not
happened is no guarantee at the moment we would want one.

⚠️ Those two trials ran on an unfunded account using free messages to the account holder's own
number, and this paragraph used to say that a **paid** message to a third party might revoke
differently. **It does, and the sample that decided it was taken 20.09.2026.** Revoking a
billed message to a third party answered the same `true` — and the status that followed
carried `verification_status: expired`, a field absent from all seven earlier captures, the
one taken after a revocation among them, while `delivery_status` read `delivered` and still
not `revoked`. So revocation is not inert on the paid path: it closes the verification.

**What does not change is the requirement.** What still nobody has observed, on either path,
is a message leaving the recipient's screen — and that, not the verification's state, is what
a guarantee would have to rest on. `delivery_status` never becoming `revoked` is now measured
on both paths rather than one.

This is the same shape as `call_status: 1` on the other rung, and it earns the same treatment:
a vendor's acknowledgement is a fact about our request, never about the subscriber's screen.
The guarantee that a finished verification stops being usable is therefore carried **here** —
the code is matched by this gateway, and a terminal verification refuses it regardless of what
is still sitting in a chat. What is lost without a working revocation is tidiness and the
shared-device case, not the guarantee.

**The asymmetry between the two paid rungs is worth stating rather than discovering.** This
route can prove that a code arrived; the `flash_call` route cannot, and says so above. The change's
own unproven link — whether a paid route reaches a МегаФон subscriber at all — is therefore
answerable on this rung from the vendor's own report, and on the other rung only by asking the
person. That does not make the rungs interchangeable, and it does not reorder the ladder: it
means the two rungs will never be equally well evidenced, and a comparison of their success
rates is comparing two different measurements.

[normative · live samples captured 18.09.2026 and 20.09.2026 in `captures/`. 18.09, free, to the account holder's own number: delivery `sent`→`delivered` in one second, `read` at 71 s; the number echoed back without its leading `+`; `verification_status`, `is_refunded` and `remaining_balance` absent from responses that do not need them; revocation inert. ⚠️ The 18.09 reading of `request_cost: 0` with `remaining_balance: 0` is superseded — the zero was the account's real balance, not evidence about the field. 20.09, billed, to a third party (`probe-1.7-*`): the subscriber is reachable, the decline is spelled `PHONE_NUMBER_NOT_AVAILABLE`, revocation sets `verification_status: expired` while leaving `delivery_status` at `delivered`, and one `updated_at` serves two delivery statuses. · conf: high for both paths on everything the samples touch; the refund remains untouched by any sample]

🔴 **Two different fields say `expired`, they mean different things, and one of them is about money.** Settled 20.09.2026 by re-reading the vendor's reference against the sample. `DeliveryStatus.status` carries `sent`, `delivered`, `read`, `expired` and `revoked`; `VerificationStatus.status` carries `code_valid`, `code_invalid`, `code_max_attempts_exceeded` and `expired`. So the scenario below is watching the right field for what it claims — **delivery** expiry, which is the one the refund is tied to — and the sample's `verification_status: expired` beside a `delivery_status` of `delivered` is coherent rather than contradictory: the message arrived, and the revocation closed the code window.

The gateway SHALL therefore never record or act on a bare `expired`: every reading of that word SHALL name which of the two fields it came from. Delivery expiry means the fee comes back and nothing reached the subscriber; verification expiry means the code window is shut and says nothing about money or delivery. A ledger that confused them would refund a verification that was delivered, or charge for one that never arrived.

#### Scenario: The message is delivered
- **WHEN** the vendor reports `delivery_status.status` of `delivered`
- **THEN** the verification is open and awaiting a code, and it is not reported as confirmed

#### Scenario: The message is read
- **WHEN** the vendor reports `delivery_status.status` of `read`
- **THEN** the verification is still not confirmed, and only a correct code confirms it

#### Scenario: The message expires unread
- **WHEN** the vendor reports `delivery_status.status` of `expired`
- **THEN** the verification fails with that reason, and the refund the vendor reports is recorded against it

#### Scenario: A finished verification asks for its message back
- **WHEN** a verification carried by `tg_gateway` is confirmed, expires or runs out of attempts while its message is still outstanding
- **THEN** revocation is requested at the vendor, and the verification is terminal whether or not the request changes anything

#### Scenario: The vendor says it revoked and the message is still there
- **WHEN** revocation answers `true` but the message remains readable by the subscriber
- **THEN** the code is still refused by this gateway, because the terminal state decides it and the vendor's answer does not

### Requirement: A vendor callback changes nothing until its signature verifies

Where a vendor delivers outcomes by callback, the gateway SHALL verify that the callback is the
vendor's before it changes any state. Telegram's Gateway signs each callback with an
`X-Request-Signature` (HMAC-SHA-256) over a body timestamped by `X-Request-Timestamp`; the
gateway SHALL check both, SHALL reject a callback whose signature does not verify or whose
timestamp is outside a configured tolerance, and SHALL change no verification's state on a
rejected one.

An unauthenticated callback endpoint that moves a verification's state is a way to confirm a
verification without the code ever reaching the person — the same guarantee the code-secrecy
requirement protects, given away at a different door. The endpoint is public by necessity: the
vendor has to reach it.

This does not reopen the uCaller webhook. `inboundCallWaiting` stays out of this change because
its payload is not documented, and a parser may not be written from guesses; the difference here
is that the Gateway's callback body, its headers and its signature scheme are all in the
vendor's reference. A rejected callback SHALL be counted, because a run of them is either an
attack or a rotated secret, and both need to be visible.

[unbacked · vendor reference: Telegram Gateway API, callback headers `X-Request-Timestamp` and `X-Request-Signature`, read 18.09.2026 and re-read 20.09.2026, which records the computation the earlier reading left as a name: `data_check_string = X-Request-Timestamp + "\n" + post_body`, `secret_key = SHA256(api_token)`, and the header is `hex(HMAC_SHA256(data_check_string, secret_key))`. Unbacked still — no callback has ever arrived, because no request has yet been made that had one to report]

#### Scenario: A callback that does not verify
- **WHEN** a callback arrives whose signature does not verify
- **THEN** no verification changes state, and the rejection is counted

#### Scenario: A callback replayed later
- **WHEN** a correctly signed callback arrives with a timestamp outside the configured tolerance
- **THEN** it is rejected on the same terms

#### Scenario: A callback that verifies
- **WHEN** a correctly signed and timely callback reports a delivery outcome
- **THEN** the verification's recorded delivery outcome is updated from it

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

**Telegram's reference publishes no rate limits at all, and that SHALL NOT be read as their
absence.** The gate this change works under says a vendor's reference binds what we may assert
about it, and silence is not a statement that a limit does not exist — it is the absence of one.
The per-number limits configured here SHALL therefore be applied to the **ladder as a whole**
rather than to the `flash_call` rung alone. They exist to keep a person from being blocked by a
vendor, and a rung whose block conditions are unpublished is the one to be more careful with,
not less. If a live sample later shows the Gateway publishing or enforcing its own, the limits
become the stricter of the two, exactly as they already do for a calendar day.

[unbacked · vendor reference, uCaller read 08.09.2026, Telegram Gateway read 18.09.2026]

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
until it is not, and the first symptom is every verification failing at once. uCaller reports
it for nothing: `getInfo` returns `cost` and `balance` on every enquiry.

🔴 **Telegram does not, and the shape of this alert follows from that.** Measured 20.09.2026
within one request: `checkSendAbility` answered `remaining_balance: 99.99`, and the send that
followed it answered `remaining_balance: 0` with nothing in between that could have spent it.
So on the `tg_gateway` rung the gateway SHALL read the balance **only from a confirming
`checkSendAbility`**, and SHALL NOT read it from a send, from a status or from a decline —
where the field is either absent or not the account's balance. An 18.09 reading that took the
zero at face value was wrong and had no way to know it: the account genuinely held zero then,
and the field agreed by coincidence.

The consequence is normative because it costs money: a confirming check is the billed call, so
**Telegram's balance cannot be polled for free.** The floor on this vendor SHALL therefore be
held against the balance that arrives with ordinary traffic, and the gateway SHALL NOT place a
check of its own merely to read it. A balance late by one verification is the cheaper error; a
paid poll buys nothing the next real check does not deliver, and on an idle rung it spends
exactly when nothing is being verified.

**There are two balances now, and the floor SHALL be held against each of them separately.** A
single floor over a sum would be satisfied by one funded account while the other is empty, and
the empty one is a rung of the same ladder. Every alert SHALL name which vendor it is about.

🔴 **A refund is tied to non-delivery and to nothing else, which makes it unobservable on
demand.** The vendor is explicit both ways: *"If a message is not delivered within the
specified `ttl`, the request fee will be refunded automatically"* and *"If a message is
successfully delivered within the `ttl`, it will not be refunded."* A `checkSendAbility` that
confirms is a statement that the subscriber is reachable, and every message we have ever sent
was delivered within a second. So the refund path cannot be exercised by a probe: it is
reached only by a subscriber who was confirmed reachable and then was not reached. Nothing
here may be built on having seen one, and the ledger SHALL treat a refund as an event that
arrives late and rarely rather than as a step in the ordinary sequence.

**A refund SHALL lower the recorded spend, not be left as an asterisk.** Telegram reports
`is_refunded` on the request it refunded, and a verification whose fee came back cost nothing;
a ledger that records the charge and ignores the refund overstates the bill in the one
direction that makes the route look worse than it is, and it does so silently.

The gateway SHALL also record, separately from both, what it spent **without getting anything
for it**: an ability check that did not answer within the bound may have been confirmed and
charged at the vendor without our ever learning the `request_id`. Such a fee cannot be spent
and cannot be refunded. It is the only class of spend this design cannot attribute to a
verification, and if it is not counted it appears as a balance that drifts for no reason.

[partly backed · uCaller half unbacked — vendor reference `getInfo` (`cost`, `balance`) read 08.09.2026, no live sample. Telegram half backed by `captures/probe-1.7-check-able.json` and `captures/probe-1.7-send.json`, 20.09.2026, which are what establish that `remaining_balance` is the account's balance only in the answer to `checkSendAbility`; guarded by `tests/test_tg_gateway_adapter.py`. The refund half is backed by nothing at all: `is_refunded` has been absent from ten captures running and no message has been left to expire unread (task 1.8)]

#### Scenario: The balance runs low
- **WHEN** one vendor's reported balance falls below the configured floor while the other's is healthy
- **THEN** the operator is alerted once within the dedup window, with that vendor named, before verifications start failing

#### Scenario: Telegram's balance is read from the only call that tells the truth
- **WHEN** a send or a status answers with a `remaining_balance` of its own
- **THEN** it is not taken as the account's balance, and the floor is held against the figure last returned by a confirming `checkSendAbility`

#### Scenario: A refunded request
- **WHEN** the vendor reports a request as refunded
- **THEN** the recorded spend for that verification falls to nothing, rather than keeping the charge with a note beside it

#### Scenario: A fee that bought nothing
- **WHEN** an ability check does not answer within the bound
- **THEN** it is counted as possibly-charged spend attributable to no verification, and the count is readable beside the attributed spend

#### Scenario: A month's spend is answerable
- **WHEN** an operator asks what the call route cost last month
- **THEN** the answer comes from recorded per-verification costs, not from the vendor's invoice

#### Scenario: The spend is answerable per application
- **WHEN** an operator asks which application spent it
- **THEN** the answer comes from the application recorded on each verification

### Requirement: A verification is a stored thing with an owner, a deadline and a secret that stops existing

A verification SHALL be persisted before the vendor is called, carrying at minimum its id, the
application that requested it, the normalised number, the code, the attempts spent, the
deadline, its state, and — per rung attempted — that rung's route, the vendor's identifiers for
it, its reported cost and whether that cost was refunded.

Per rung rather than per verification, because a ladder has more than one: a verification that
tried Telegram and then placed a call holds two vendor identifiers, two costs and one code, and
a row shaped for a single route answers "what did this person's login cost" by overwriting half
of it. The verification SHALL name which rung carried the code it is matching against.

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
`verify-by-inbound-contact` returns the code to the application by design on that one rung,
because there the
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

**The ladder's rung SHALL be decided within that same bound**, and the bound SHALL cover the
ladder as a whole rather than each rung separately — otherwise two rungs of a slow day take
twice the time the application was promised. A rung that has not answered when the bound is
reached SHALL be abandoned in favour of the next, and the last rung's silence SHALL leave the
verification in flight as above.

The method SHALL NOT be answered as unknown or as pending. It is the only part of the response
the person acts on: an application that cannot say whether to watch Telegram or the phone has
nothing to put on the screen, and the whole reason the method travels in the creation response
is that the person is already standing at the barrier.

That is why the abandoned check is counted rather than shrugged at. A Gateway that answers
slowly instead of refusing turns the cheap rung off silently: every verification still
completes, by call, at full price, and the only visible symptom is the bill.

The gateway already refuses to make acceptance wait on a slow thing it does not control —
`outbound-send` states that acceptance does not wait for the modem — and it already bounds its
one existing outbound lookup for the same reason. Without a bound the parking app's HTTP
request hangs on uCaller's, the person watches a spinner, the app times out its own client,
and the call may well have been placed and charged in the meantime.

[unbacked · bounded-external-call precedent: voxlink_timeout in app/settings_store.py]

#### Scenario: The vendor is slow
- **WHEN** the vendor has not answered within the configured bound
- **THEN** the request is answered with the verification's id and method, and the verification is in flight rather than failed

#### Scenario: A slow rung does not extend the promise
- **WHEN** the first rung of a ladder consumes most of the bound before the second is tried
- **THEN** the response still arrives within the one bound, naming a method

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

### Requirement: The text of an SMS-carried verification comes from the application's own template, and there is no default

Where a verification is carried on the `sms_out` route, its text SHALL be composed from a
template configured **per application**, in the manner `delivery-dispatch` already configures a
dispatch route per application. A request from an application that has no template SHALL be
refused, with a reason naming the missing template, at the moment the request is accepted
rather than when the message is composed.

There SHALL be no built-in default text, and the gateway SHALL NOT compose wording of its own.
This is the owner's decision of 18.09.2026, and the reason is that a default is a wording
decision taken silently on behalf of applications that do not share a voice: `sp_app` sends
`SokolParking: ####` and nothing else — 446 of 448 messages since 01.08 — while the others are
free text under other names. A person reading a code signed by something they do not recognise
treats it as the fraud it resembles.

Refusing at accept rather than at compose matters for money as much as for tidiness: by compose
time the request has passed the entitlement and the ceiling, and on a ladder it may already have
bought a rung. A missing template is knowable before any of that.

A template SHALL be validated when it is saved: it SHALL carry exactly one placeholder, the
code, and a template carrying none, carrying it twice, or carrying an unknown placeholder SHALL
be refused at save time. A template that silently drops the code sends a person a message with
nothing in it to type.

The template governs the `sms_out` route only. `tg_gateway` has no message body to supply —
`sendVerificationMessage` takes a `code` and no text — and `flash_call` carries no text at all, so an
application without a template SHALL still be served by those rungs. The refusal follows the
rung, not the application.

[unbacked · per-application configuration precedent: the dispatch-route setting in delivery-dispatch]

#### Scenario: An application with no template asks for an SMS-carried verification
- **WHEN** a verification is requested by an application with no template, for a number whose operator is routed `sms_out`
- **THEN** it is refused at accept with a reason naming the missing template, and no message is composed

#### Scenario: The same application on a paid rung
- **WHEN** the same application requests a verification for a number whose operator is routed to a paid ladder
- **THEN** the absence of a template does not refuse it, because neither paid rung carries text of ours

#### Scenario: A template that would drop the code
- **WHEN** a template with no code placeholder is saved
- **THEN** the save is refused with that reason

### Requirement: A verification carried by the modem takes that message's outcome

A verification on the `sms_out` route SHALL own the message it creates: the message SHALL be
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
