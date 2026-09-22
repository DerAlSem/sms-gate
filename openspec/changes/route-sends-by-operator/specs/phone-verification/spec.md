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
- **WHEN** a verification is requested for a МегаФон number while the rule routes МегаФон to `[tg_gateway, flash_call]` and the Gateway declines the subscriber
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

[backed · the refusal is `VerificationCreateRequest.refuse_a_supplied_code` in
`app/api/schemas.py`, which rejects before a row exists; the distinct-code half is
`_new_code(await queries.open_codes_for(phone))` in `app/api/router.py`. Guarded by
`tests/test_the_code_and_who_may_spend_it.py` and four mutations in `bite-code.py`.
🔴 **The distinct-code half was unguarded until 21.09.2026** — the inherited guard asserted
what `open_codes_for` reports and never that the second code differs, so `_new_code(set())`
left the suite green. A guard written the obvious way would have been little better: with ten
thousand codes, two random draws collide once in ten thousand runs, so the source of digits is
scripted and the collision made certain. The state is reachable — measured: `POST
/verifications` refuses only a blocked number and a ladder that can prove nothing, and the
vendors' per-number window is evaluated when a rung is walked, not when a verification is
opened]

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

[partly backed · the matcher is `queries.check_verification` in `app/db/queries.py`, both
halves single conditional updates. Guarded by `tests/test_the_code_and_who_may_spend_it.py`
and six mutations in `bite-code.py`. **The vendor-facing scenarios — the `ttl` handed to
`tg_gateway` and the vendor's own code-checking endpoint — are backed elsewhere and not
here.**

🔴 **Two of the three conditions on the confirming update were held by a second filter below
them.** `status = 'pending'` and `attempts < ?` can each be deleted and nothing reddens,
because a terminal verification has already had its code nulled and the update fails on
`code = ?` instead. The guarantee is real and it is held by one line; the day destruction is
deferred — which is what task 4.30 is about — it would be held by none. The guards therefore
put the code **back** into a terminal row before offering it, which is the only way to assert
about the condition that is not the one already proved.

🔴 **The answer lied in one reachable state, and task 4.10a is what it cost.** The attempt
ceiling is a setting: lowering `verification_max_attempts` while verifications are open leaves
rows pending with more attempts spent than the limit now allows, and such a row answered
`expired` while sitting inside its deadline — the one thing that had not happened, and the
requirement asks the answer to say *which* of the three it is. It now answers
`no_attempts_left`. A row that is both out of time and out of attempts is called `expired`:
the deadline is the older word and the one the application was told at creation. That
precedence is a choice and is guarded as one]

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

**The vendor's refusal is told apart by the presence of an `error`, and SHALL NOT be told
apart by `status` alone.** Measured 22.09.2026: `initCall` for an unreachable subscriber
answers `status: false` carrying no `error` and no numeric error code, and carrying instead
the ordinary payload — an allocated `ucaller_id`, the masked number, and **our own code as a
string under the same `code` key the error envelope uses for its number**. So a reading of
"not `status` → `code` is the error" returns the verification code as an error code, and a
reading of "not `status` → nothing was created" discards an authorisation that exists, is
queryable, costs money on a real number and carries two free repeats.

The gateway SHALL therefore treat an answer as a refusal only when it carries `error`, SHALL
record the `ucaller_id` of any answer that carries one whatever `status` says, and SHALL parse
both envelope shapes. ⚠️ The observation is from the vendor's **test** number, which it serves
as a simulation; whether a live failure to connect answers in the same shape is not
established, which is why both shapes are required rather than the observed one.

[backed · live samples 22.09.2026, both outcomes, in `captures/uc-1.3-*.json` with their
findings in `captures/ucaller-samples-1.3.md`; the vendor reference of 08.09.2026 re-read by
layers on 22.09.2026 and captured in `captures/ucaller-reference-2026-09-22.md`. The parser
is `app/verification/ucaller.py` and the rung is `app/verification/flash_carrier.py`, guarded
by `tests/test_ucaller_adapter.py`, `tests/test_flash_call_carrier.py` and
`tests/test_the_call_rung_is_reachable.py`, with 14 and 18 mutations in
`bite-ucaller-adapter.sh` and `bite-flash-call.sh`.
**Still unbacked: the `-1` bound.** `call_status: -1` was not observed once — both outcomes
arrived already resolved — so how long the gateway waits for it rests on the reference alone.
⚠️ **And the bound is the ladder's rather than a number of this rung's own**, which the
reference makes the ordinary case rather than the exotic one: the vendor takes up to a minute
and the ladder ships with ten seconds, because a person is standing in front of a synchronous
request for all of it. An outcome that resolves afterwards is read by nobody today — the rung
keeps its `unresolved` row and its `ucaller_id`, and the verification ends on its own deadline.
Task 4.17e owns closing it]

#### Scenario: The vendor refuses without saying so in `status`
- **WHEN** `initCall` answers `status: false` with no `error` and an allocated `ucaller_id`
- **THEN** the authorisation is treated as placed and followed up by its id, and the `code` field is read as the verification code rather than as an error code

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

[partly backed · the door is `handle_callback` in `app/verification/tg_callback.py` over `callback_verifies` in `app/verification/tg_gateway.py`, guarded by `tests/test_tg_callback.py`: all three endings of this requirement are driven with a real HMAC rather than a stubbed check, and each rejection is asserted to leave both the verification's status and the carrying rung's recorded outcome untouched **and** to be counted. Seven mutations bite — the count dropped, the timestamp window dropped, the signature not compared, the accepted branch not recording, a stale callback recording the rung anyway, and the window narrowed to one direction. Two of those were live holes found by biting a suite that was already green: a rejected callback could write the rung, and a timestamp arbitrarily far in the **future** was accepted, which is a replay window with no far edge. 🔴 **The vendor reference half is unchanged and still unbacked by any observation** — no callback has ever arrived, because no request has yet been made that had one to report. Reference: Telegram Gateway API, callback headers `X-Request-Timestamp` and `X-Request-Signature`, read 18.09.2026 and re-read 20.09.2026, which records the computation the earlier reading left as a name: `data_check_string = X-Request-Timestamp + "\n" + post_body`, `secret_key = SHA256(api_token)`, and the header is `hex(HMAC_SHA256(data_check_string, secret_key))`. ⚠️ **Both rejection kinds are counted under one key** (`signature`), so a run of clock skew is indistinguishable from a run of bad signatures — the module's own docstring says the kinds are counted apart because they mean different things, and here they are not. The requirement does not demand the split; naming it rather than taking it is deliberate. **Owner's**]

#### Scenario: A callback that does not verify
- **WHEN** a callback arrives whose signature does not verify
- **THEN** no verification changes state, and the rejection is counted

#### Scenario: A callback replayed later
- **WHEN** a correctly signed callback arrives with a timestamp outside the configured tolerance
- **THEN** it is rejected on the same terms

#### Scenario: A callback that verifies
- **WHEN** a correctly signed and timely callback reports a delivery outcome
- **THEN** the verification's recorded delivery outcome is updated from it

### Requirement: A callback nobody is told about never arrives

The Gateway takes its reporting address as a `callback_url` **on each request** and holds none
of its own. The gateway SHALL therefore send that address with every message it buys on
`tg_gateway`, and the address it sends SHALL be one this gateway serves — assembled from the
configured public address and the callback door's own path, rather than written a second time
beside it.

Where no public address is configured the gateway SHALL send no address at all rather than a
partial one, SHALL still buy and send the message, and SHALL say once, where the rung is
assembled, that nothing about the message's delivery, expiry or refund will come back. That is
a degraded estate rather than a broken one: the person still receives a code, and the
verification still ends on its own deadline — what is lost is the vendor's half of the ledger,
which is where the delivery-expiry ending and the refund record both live.

🔴 **Measured, and it is why this requirement exists.** Until 21.09.2026 nothing in `app/`
supplied the address: the signed-callback door, the revocation sweep and the delivery-expiry
ending were all built, guarded and green, and none of them could fire in production — a
mechanism whose whole input arrives from outside is invisible to every test that does not ask
what was handed to the vendor. The parameter carrying it had a blank default, and every caller
there had ever been took it.

[backed · the address is assembled by `tg_callback.url_for` over `tg_callback.PATH`, which is
the same name `app/api/router.py` registers the door under, and is supplied at
`placement.carriers_for`; `tg_carrier.carrier` takes `callback_url` with **no default**, so a
caller that does not decide it fails on the signature rather than silently. Guarded by
`tests/test_where_the_vendor_reports.py`, which reads back what reaches the adapter rather
than what the carrier returns, and checks the path against the live route table rather than
against the source. Reference: Telegram Gateway API, read by layers 21.09.2026 — `callback_url`
is "An HTTPS URL where you want to receive delivery reports related to the sent message, 0-256
bytes", and the *Report delivery* prose phrases every mention around the request ("if you
provided one"). The account side was read the same day and the same way: zero occurrences of
`callback` or `webhook` in the raw HTML of `gateway.telegram.org` or in `/js/gateway.js`, whose
API-settings form enumerates what it submits — `{account_id, ip_list}` — with `ip_list` five
times over as the positive control. · conf: high on our half; **the vendor's half remains
unobserved — no callback has ever arrived**, and it cannot be observed without a paid message
to a real person]

#### Scenario: The vendor is told where to report
- **WHEN** a message is bought on `tg_gateway` and a public address is configured
- **THEN** the vendor is given the address of the callback door this gateway serves

#### Scenario: No public address is configured
- **WHEN** a message is bought on `tg_gateway` and no public address is configured
- **THEN** no address is sent, the message is bought and sent regardless, and the gateway says that nothing will report back

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

The window SHALL be counted **rolling backwards from now** rather than as a calendar day, and
the count SHALL be taken over the rung attempts of both paid routes rather than over
verifications: what the vendor counts is an authorisation placed, and one verification places
more than one — that is what a ladder is.

[backed for the enforcement · `app/verification/limits.py`, guarded by
`tests/test_per_number_limits.py`, with a positive control and seven mutations in
`bite-limits.sh` — counting only the call rung, dropping the gap, dropping either ceiling,
a calendar day instead of a rolling window, hard-coded vendor numbers, and every number
counted as one — each turning a guard red. The **numbers** remain the vendors' reference
rather than a measurement: uCaller read 08.09.2026, Telegram Gateway read 18.09.2026, and no
live sample shows either vendor enforcing anything]

#### Scenario: A second attempt too soon
- **WHEN** a verification is requested for a number eight seconds after the previous one
- **THEN** the request is refused with a reason naming the wait, and no call is placed

#### Scenario: The daily ceiling
- **WHEN** a number reaches the configured daily ceiling
- **THEN** further requests for it are refused until the ceiling resets, and the operator can see that it happened

### Requirement: A repeat uses the vendor's free repeat, and a retried request does not buy a second call

🔴 **The vendor's free repeat is unavailable to this account, and that is measured rather
than assumed.** On 22.09.2026 `initRepeat` answered `405 Method Not Allowed` to a call made
in the same breath as a `getInfo` reporting `repeatable: true` and `repeat_times: 2`, on both
documented call forms, sixty-five seconds after the original — so it is not the window, not
the HTTP method, and not the allowance, none of which the vendor signalled with the codes it
reserves for them (`11`, `12`). Why is not visible from outside: tariff, a cabinet setting,
or a mechanism the vendor is retiring.

**So the operative path is the one below: a repeat request SHALL open a new, paid
verification whose code differs, SHALL close the previous one, and SHALL tell the application
that the identifier changed.** The gateway SHALL NOT call `initRepeat` while it answers `405`,
and SHALL NOT present a repeat to the application as free.

Should the method become available, the gateway SHALL use the vendor's repeat of the existing
verification rather than opening a new one — uCaller documents two repeats per verification at
no charge, no sooner than sixty seconds after the original — and SHALL still withhold it until
the sample condition below is met.

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

[unbacked · vendor reference: `initRepeat`, `unique` (UUID v4), read 08.09.2026 and again by
layers 22.09.2026.
🔴 **And the free repeat may not exist for this account at all.** Measured 22.09.2026:
`initRepeat` answered `405 Method Not Allowed` on both documented call forms, GET and POST,
including a call made while `getInfo` still reported `repeatable: true` — where an expired
window is coded `11` and an exhausted allowance `12`, neither of which was ever returned. The
reference marks every free-repeat field `deprecate` while `/limits/` still promises two
repeats. Not yet conclusive: nobody watched the window be open in the same second as the
refusal, and the separating probe is named in `captures/ucaller-samples-1.3.md`.
**The clause above already fails safe** — a repeat is offered only once a live sample
establishes that the vendor repeats from the same number, and no such sample exists — so a
dead `initRepeat` costs this requirement its first paragraph and nothing else: the gateway
opens a new verification and says the digits changed.
⚠️ **`getInfo`'s field set is not stable for one `ucaller_id`**: read again minutes later, the
same authorisation returned `repeatable: false` and **no `repeat_times` at all**. A reader that
treats `repeat_times` as present because `repeatable` once was `true` breaks on an ordinary
expiry rather than on a vendor fault. Both captures are kept side by side]

#### Scenario: The person asks for the call again while the vendor refuses to repeat
- **WHEN** a repeat is requested and the vendor's `initRepeat` is unavailable
- **THEN** a new paid verification with a different code is opened, the previous one is closed, the application is told the identifier changed, and the repeat is never presented as free

#### Scenario: The person asks for the call again once the vendor allows it
- **WHEN** a repeat is requested more than sixty seconds after the original, within the free allowance, and the vendor's repeat is available and established to call from the same number
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

[backed · `push_verification` in `app/verification/dispatch.py`, announced by
`announce_verification_outcomes` and guarded by
`tests/test_verification_outcome_reaches_the_app.py`. 🔴 **Naming the kind was not enough and
the code was fixed here, not the requirement.** The body said `"object": "verification"` and
still carried the verification's number in `id` — the field the message contract names its own
subject in — and `failed` and `expired` are words both bodies use, so a receiver keyed on `id`
and `status`, which is the whole of the older contract, acted on it. The subject now travels in
`verification_id` and `id` is absent. The guard compares a **real** message push against a real
verification push rather than against a remembered description of the message body, and asserts
the verification's number appears in exactly one field; five mutations bite, including one that
moves the message contract underneath it. Measured on a file-backed database: message 1 and
verification 1 collide from the first row of each table]

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

**A paid rung whose floor is not configured SHALL be reported as unwatched rather than read as
satisfied.** An absent or zero floor is how a floor stops existing without anybody deciding
that it should, and a floor that never fires is indistinguishable from a vendor that never
runs out — the same silence, from opposite causes. The failure this guards is the ordinary
one: a third paid vendor is added, its adapter works, and nobody notices that its balance is
watched by nothing until the day it empties.

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
direction that makes the route look worse than it is, and it does so silently — every reader
would have to remember to subtract, and the first one who forgets reports a number that never
existed. What the vendor said SHALL stay recorded in words beside it, because the vendor's own
account of the fee is evidence and our arithmetic is not.

**A refund once recorded SHALL NOT be undone by a later write.** The spend of a refunded
request is settled, and nothing in the ordinary sequence has cause to put a charge back on it:
the fee is recorded between the ability check and the send, and the refund arrives with a
callback long afterwards. The rule belongs at the write rather than in a comment, because a
resurrected charge is a bill with no explanation attached — and the refund is exactly the
event rare enough that nobody would think to look for one.

The gateway SHALL also record, separately from both, what it spent **without getting anything
for it**: an ability check that did not answer within the bound may have been confirmed and
charged at the vendor without our ever learning the `request_id`. Such a fee cannot be spent
and cannot be refunded. It is the only class of spend this design cannot attribute to a
verification, and if it is not counted it appears as a balance that drifts for no reason.

[partly backed · the floor is `app/verification/balance.py`, held per vendor from `tg_gateway_balance_floor` and `flash_call_balance_floor`, read by the carrier from a **confirming** ability check and from nowhere else; guarded by `tests/test_balance_floor.py`, which drives the carrier through a check reporting 2.5 and a send reporting 9999 and asserts the floor fires on the check's number. The refund lowering the spend is `record_rung_delivery` in `app/db/queries.py`, guarded by `tests/test_refund_lowers_spend.py`. **uCaller half: the reading is now backed, the number is not.** `getInfo` answers `cost` and `balance` on every enquiry — live samples 22.09.2026 — and `balance` is the balance **before** this operation is charged, so `app/verification/ucaller.Info.balance_after` subtracts `cost` and the carrier watches that rather than the vendor's figure; watched as it stands the floor would fire one verification late, which mutation 9 of `bite-flash-call.sh` turns red. What stays unbacked is the **number**: every authorisation captured was a free test one at `cost: 0.00`, no charge has been observed, and the floor ships at zero because any other value would be a guess dressed as a setting. **The refund half remains backed by no observation at all**: `is_refunded` has been absent from ten captures running, no message has been left to expire unread (task 1.8), and the path cannot be reached by a probe — a confirming check states the subscriber is reachable, so only a subscriber confirmed reachable and then not reached gets there. The tests drive the recording directly and claim nothing about having seen one]

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

**A single verification SHALL be readable by an operator beside the messages for the same
number**, showing every rung attempted, each rung's vendor outcome and identifier, whether the
verification was confirmed and by which method, the cost recorded against each rung and whether
it was refunded. The counters answer "how much"; a support call is always about one person, and
it arrives with that person's number rather than with a verification id.

**The cost shown SHALL be the cost as recorded, and no gross figure SHALL be shown beside it.**
A refund lowers the recorded spend to nothing rather than leaving an asterisk next to it, and a
screen that helpfully prints what was originally charged restores the asterisk it replaced.

[partly backed · the console half is `queries.verifications_for_phone` and
`queries.rungs_for_verifications`, rendered under the conversation in the expanded row of
`/admin/messages`; guarded by `tests/test_admin_verifications.py` and five mutations in
`bite-verif-view.sh` — the query starring its columns, the number ceasing to filter, no rung
reaching the page, the block never populated, and the row losing the anchor the guard finds it
by. `verifications_for_phone` lists its columns rather than starring them, and that is the
guarantee rather than a style: the code must reach no screen. The storage itself is
`verify-by-inbound-contact`'s.

**The retention half is backed** by `queries.prune_verifications`, called last in
`announce_verification_outcomes` and therefore from the sixty-second verification tick,
under `verification_retention_days` (30). Guarded by `tests/test_verification_store.py`
and `tests/test_verification_outcome_reaches_the_app.py`, over the tick rather than over
the announcer, and by ten mutations.

🔴 **Two holes, both invisible to a green suite, measured 21.09.2026.** The prune could be
deleted from the announcer outright and nothing reddened: the query was guarded and its
*placement* was not, which is how a retention rule becomes a comment on a gateway that
stays up. And the prune removed the verification while leaving its rungs — `verification_
rungs` carries no foreign key and no retention of its own, so the surviving half was the
vendor's reference for a message placed to a subscriber, kept for the life of the database
and reachable by nothing, since every reader of that table goes through a live
`verification_id`. The rungs now go with the verification, in `prune_verifications` and
nowhere else, together with the orphans a database written by the old code already holds.

**The ownership half is backed** — `queries.get_verification` and every conditional update in
`check_verification` are scoped by `app_id`, so a stranger's call is answered as a missing
verification and spends nothing. Guarded by `tests/test_the_code_and_who_may_spend_it.py` over
all three verbs with a **valid** token of another application, paired with the positive control
that the owner's own three calls answer, and by two mutations in `bite-code.py`. **The
secret-destruction half is backed** by the same file, over all three terminal endings in one
run rather than one of them: the rung-failure ending is the one the inherited guards missed,
though it is where every walked ladder arrives when nothing carried the code]

#### Scenario: The state outlives the process
- **WHEN** the gateway restarts while a verification awaits the vendor's outcome
- **THEN** the verification is still there and is resolved or recorded as unknown, not silently dropped

#### Scenario: Another application asks about a verification
- **WHEN** an application that did not create a verification asks for it or checks a code against it
- **THEN** it is answered as if no such verification exists, and no attempt is spent

#### Scenario: One person's verification, beside their messages
- **WHEN** an operator opens the conversation with a number that has verifications
- **THEN** each of them is shown with every rung attempted, the vendor's outcome and reference for each, what it is recorded as costing and whether that cost was refunded

#### Scenario: A refunded rung on the screen
- **WHEN** a rung whose charge was refunded is shown
- **THEN** its cost reads as the nothing it now is, with no charged figure beside it

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

[backed · the response half is enumerated from the router rather than from a list — every
response model on a `/verifications` path, so that the next door added to this capability is
covered by the guard that exists rather than by one nobody wrote. `RouteSelectResponse` is the
single sanctioned exception and it belongs to a **rung**. The destruction half is `code = NULL`
on all three terminal endings, in `check_verification`, `fail_verification` and
`expire_due_verifications`. Guarded by `tests/test_the_code_and_who_may_spend_it.py` and seven
mutations in `bite-code.py`, driven over a path where the code genuinely travelled to the
vendor.

🔴 **A field-shaped guard cannot hold this requirement, and task 4.22a is what it cost.**
`reason` is free text on both the verification and its rungs, it is filled from a vendor's
error string and from an exception's message, and neither is ours to write. Measured
21.09.2026: a reason carrying the code reached `GET /verifications/{id}` and the console's
expanded row with the whole suite green. The remedy is `_without_the_code` at the **write**
border in `app/db/queries.py` — the readers are many and a census of readers is never complete,
while there is exactly one place such text becomes stored. The code is replaced visibly rather
than removed, so an operator can tell something was taken out.

⚠️ One of the three writers, `record_verification_rung`, has no caller that reaches it with a
reason today — `ladder.walk` writes that row before it has anything to say. It is guarded by
calling the border directly, because an unreachable scrub with no guard on it is the shape that
gets deleted as dead code]

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

### Requirement: Selecting a rung the gateway places walks the ladder inside that selection

A route SHALL NOT be offered, selected, recorded, and then left unplaced. Where the selected
rung is one **this gateway** acts on — as opposed to one where the subscriber acts — the
ladder SHALL be walked before the selection is answered, and the answer SHALL state what
became of it.

**The ladder walked SHALL be the routing rule's answer for this subscriber's operator, from
the selected rung onwards.** Rungs ahead of the selected one SHALL NOT be attempted: they
were offered and not taken, or were never offered, and attempting one would place a route
nobody chose — on this ladder, a paid one. Rungs behind it are the ladder continuing, which
is what a ladder is; and because it settles inside the one answer, the person is never told
to watch Telegram and then moved somewhere else.

**A selected rung the rule does not name for that operator SHALL be carried alone.** The
owner's decision of 21.09.2026. The offer has already stated that this rung can prove it
will carry this number, and the rule is a statement about an operator's traffic rather than
about a verification whose route a consumer chose by hand — so the choice is honoured, and
the rule contributes only the continuation, which in that case is none.

**The route SHALL be claimed before anything is spent, and the rung that carried SHALL then
replace the claim.** The claim is what makes two simultaneous selections unable to both buy
the same code, so it cannot wait until after the vendor has been paid; and a claim left
standing would leave the verification naming a rung that declined it, which is the defect
this capability names by hand — an application told to expect a Telegram message for a person
the Gateway declined puts the wrong instruction on the screen. A verification that has stopped
being open SHALL NOT be moved at all: on a paid rung that is money spent on a verification
nobody is waiting for any more, and it SHALL be reported rather than recorded as a delivery.

**A gate's refusal SHALL end the verification with that reason and SHALL be answered as a
refusal.** Nothing was contacted and nothing was charged, so no rung SHALL be recorded — a
row saying otherwise would put a refusal of ours into the count of what the vendors did. But
the route was claimed before the walk, so a verification left open after a refusal is a route
claimed with nothing placed: the same defect, one door further in. It is emphatically not a
vendor failure and SHALL NOT be reported as one.

**The gateway's own bookkeeping SHALL NOT count as vendor spend.** The spend ceiling and the
per-number limits count every recorded rung on a paid route whatever its outcome —
deliberately, because an ability check that never answered may have been charged without our
learning its `request_id`. A second row written for the gateway's own convenience is
therefore money: it halves both ceilings for the one rung that actually spends, and, being a
paid attempt aged zero seconds against a minimum gap of fifteen, it refuses the very
selection that wrote it while looking exactly like a gate doing its job.

**The one bound SHALL be handed to each rung as what is left of it, and each carrier SHALL
apply it to its own vendor calls.** The ladder does not abandon a rung by force, and that is
deliberate: cancelling a carrier between a confirmed ability check and the record of its
`request_id` would leave a fee nobody can attribute. The guarantee therefore rests on the
carriers, and a carrier that omits the bound SHALL NOT silently fall back on a vendor
method's own default — which on this vendor is five seconds for the check and ten for the
send, fifteen against a bound that may be one.

[backed · the door is `select_verification_route` over `app/verification/placement.py` in
`app/api/router.py`, the re-pointing is `queries.set_carrying_route`, and the bound is the
setting `verification_ladder_bound` (10 s, a ceiling: the Gateway answers in 178–285 ms over
the wired path and times out at fifteen seconds on the failed-over one). Guarded by
`tests/test_the_door_that_walks_the_ladder.py`, sixteen tests, and by the verify run described
in `HANDOFF.md` — a file-backed database with real migrations driven through the real router,
41 claims provoked rather than read. **Twenty mutations bite**, among them the four an
implementation naturally writes: the claim winning over the rung that carried, the bound
hardcoded instead of read, the gates handed in empty, and the ladder started at the top of
the rule. 🔴 **The second rung is `flash_call` and nothing carries it** (task 4.17, blocked on
1.1), so today a declined subscriber ends in the loud-skip path rather than in a call; that
path is itself guarded, at the door and one layer down]

#### Scenario: The rung the consumer chose is actually placed
- **WHEN** a consumer selects the Telegram rung for a subscriber the Gateway will confirm
- **THEN** the vendor is asked and the code is sent, and the answer names that rung as the method

#### Scenario: The rung that carried is not the rung that was chosen
- **WHEN** the Gateway declines the subscriber and the next rung of the rule carries the verification
- **THEN** the answer and the stored verification both name the rung that carried, not the one selected

#### Scenario: A rung the rule does not name for this operator
- **WHEN** a consumer selects the Telegram rung for a subscriber the rule routes to the modem
- **THEN** that rung is carried alone, and the route the rule named is not attempted

#### Scenario: The ladder does not reach behind the consumer's choice
- **WHEN** the rule names a dearer rung ahead of the one the consumer selected
- **THEN** the dearer rung is not attempted at all

#### Scenario: A gate refuses before any rung
- **WHEN** the application holds no entitlement to spend and a paid rung is selected
- **THEN** the selection is refused with that reason, no vendor is contacted, no rung is recorded, and the verification is ended rather than left open

#### Scenario: One attempt is counted once
- **WHEN** a paid rung is selected and attempted once
- **THEN** the spend ceiling and the subscriber's own allowance each count it once

#### Scenario: The bound reaches the vendor
- **WHEN** the ladder's bound is narrower than the vendor methods' own defaults
- **THEN** both vendor calls are made under the bound rather than under those defaults

#### Scenario: A verification that ended while the vendor was being asked
- **WHEN** a rung carries a verification that has since stopped being open
- **THEN** the verification is not re-pointed at that rung, and the discrepancy is reported

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

An application named by two entries SHALL be refused at save time. Which of the two wins
would otherwise be decided by the order of the list, invisibly — the same argument the routing
rule makes about two spellings of one operator.

A stored value that cannot be read SHALL NOT be read as an absence of templates. Absent refuses
the application, which is loud and recoverable; read as empty, the gateway would compose around
whatever an empty string means to the compose step, and a person would receive a message with
nothing in it to type. The unreadable case SHALL raise an operator alert and SHALL refuse.

Composing SHALL substitute the code and SHALL NOT interpret the rest of the template. A
template is operator-supplied text, and a formatter would read every brace in it as a field —
`{0}` reaches into the arguments and `{a.b}` into attributes — so a wording typo would become a
failed send at the moment a person is waiting for a code.

The template governs the `sms_out` route only. `tg_gateway` has no message body to supply —
`sendVerificationMessage` takes a `code` and no text — and `flash_call` carries no text at all, so an
application without a template SHALL still be served by those rungs. The refusal follows the
rung, not the application.

**The refusal at accept SHALL be keyed on the rungs this verification has left, and SHALL
NOT be keyed on the routing rule.** A verification is refused at accept when no rung still
available to it can carry a code without wording of ours, and the application has none —
because then the code could never be written down, whichever rung the consumer picks.

⚠️ **This narrows what this requirement said until 21.09.2026**, which was that a
verification is refused when its operator is *routed* `sms_out`. Read that way it refuses
requests the gateway can in fact fulfil, and the reason is the owner's decision of the same
day that a rung the rule does not name is still carried alone: a consumer offered the
Telegram rung may pick it for a number the rule sends to the modem, and be carried with no
text of ours anywhere. Refusing that at accept is the same requirement's other half — "SHALL
NOT accept a request it already knows it cannot fulfil" — read backwards into a request it
can.

[partly backed · the save-time half is `app/verification/template.py`, reached as the typed
setting `verification_templates` through `validate_raw`/`normalize_raw` in
`app/settings_store.py` and rendered as a textarea on the settings page; guarded by
`tests/test_verification_template.py` and by nine mutations in `bite-template.sh` — a template
with no placeholder, with two, with an unknown one, a blank one, one application named twice, an
unreadable setting read as absent, a formatter interpreting the template, and each of the two
wirings into the settings layer removed — each turning a guard red. The shipped default is
**empty**, so an estate that configures nothing refuses every `sms_out`-carried code rather than
sending wording nobody chose.
🟢 **The refusal at accept is backed from 21.09.2026** (task 4.47): `app/verification/routes.py`
(`needs_our_words` and `carries_a_code_without_our_words`, beside `_CARRIES` because it is a
property of the route) and the door in `app/api/router.py`, which asks it of the offers that
are left rather than of the rule. Guarded by `tests/test_verification_api.py` with three
positive controls — the same estate with a template, the same estate with a paid rung
available, and the inbound rungs — and by seven mutations, among them the conjunction losing
its `carries` half, which is unreachable through the door and held directly in
`tests/test_send_path_refuses_an_uncarryable_route.py`]

#### Scenario: An application with no template asks for an SMS-carried verification
- **WHEN** a verification is requested by an application with no template, and every rung still available for that number carries a code only inside wording of ours
- **THEN** it is refused at accept with a reason naming the missing template, no verification is opened and no message is composed

#### Scenario: The same application while a rung that needs no wording is still available
- **WHEN** the same application requests a verification and a paid rung, or a rung on which the subscriber reaches the gateway, is still available for that number
- **THEN** the absence of a template does not refuse it, because neither the paid rungs nor the inbound ones carry text of ours — even where the routing rule sends that operator to the modem

#### Scenario: A template that would drop the code
- **WHEN** a template with no code placeholder is saved
- **THEN** the save is refused with that reason

#### Scenario: One application with two templates
- **WHEN** a list naming the same application twice is saved
- **THEN** the save is refused, because which of the two wins would be decided by the order of the list

#### Scenario: The stored templates cannot be read
- **WHEN** the stored setting is not a readable list of templates
- **THEN** an operator alert is raised and every application is refused an `sms_out`-carried code, rather than the setting being read as no templates at all

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

[backed · evidence: app/verification/sms_carrier.py (the rung itself — it composes from
the application's template, creates the message with `verification_id` set, and hands it
to the sender) · app/db/migrate.py (`messages.verification_id`, additive and NULL for
every existing row) · app/modem/delivery_dispatch.py
(`_the_verification_takes_this_outcome`, on `dispatch_delivery`, which is the one door
all eight of the sender's status writers pass through) · app/modem/manager.py (the sender
does not re-read the rule for a message the ladder placed) · tests/
test_the_modem_rung_carries_a_code.py and test_a_verification_owns_its_message.py,
sixteen mutations bitten, none surviving ·
app/verification/probes.py (`_sms_out_probe`, so the rung can be chosen — the owner's
decision of 21.09.2026) · conf: high]

#### Scenario: The SMS carrying a code fails
- **WHEN** the message carrying a verification's code is failed or expired by the sender
- **THEN** the verification fails with that reason and the application is notified under the verification's id

#### Scenario: A verification's message does not notify as a message
- **WHEN** the status of a message belonging to a verification changes
- **THEN** no message-status push is sent for it; the verification's own notification carries the outcome
