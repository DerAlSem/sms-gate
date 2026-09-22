## Purpose

Which way out the gateway reaches a subscriber. There are three — the local modem, which
carries arbitrary text; Telegram's Gateway API, which carries a verification code to a
subscriber reachable in Telegram; and a vendor flash call, which carries four digits as the
last digits of a calling number. This capability owns the choice between them, the rule that
expresses it, the order in which the paid ones are tried, what a route is capable of carrying,
and what happens when the choice cannot be honoured. It exists because the modem route has
been withdrawn by operators before, at whole-estate scale, and the replacement must be
reachable by configuration rather than by deploying code during an outage.

## ADDED Requirements

### Requirement: Every outbound attempt is assigned exactly one route before it leaves

A message or a verification SHALL be assigned a route — `sms_out`, `tg_gateway` or `flash_call` —
before any transmission is attempted, and that assignment SHALL be recorded against it. It
SHALL NOT be carried by a route other than the one recorded, and SHALL NOT be carried by two
at once.

Where a ladder advances a verification from one paid rung to the next, each rung SHALL be a
recorded attempt of its own, carrying its own route, its own vendor identifiers and its own
cost. The verification SHALL name the route that actually carried the code it is matching
against. A ladder written as one attempt whose route changes underneath it cannot answer what
the second rung cost or why the first was abandoned, and both questions are asked the first
time a bill looks wrong.

The recorded route SHALL be readable afterwards, because the cost, the outcome vocabulary and
the meaning of success all differ by route, and none of them can be reconstructed afterwards
from the message alone. It SHALL be a field of the item it belongs to — of the message for a
send, of the verification for a verification — and SHALL stay readable for that item's whole
life.

The route names the way out. The method an application is told about SHALL be derived from the
route by a mapping this capability owns and states, and no other capability SHALL define a
second vocabulary for the same decision. Two words for one choice agree while there are
exactly two routes and disagree on the day there is a third.

**That day arrived on 18.09.2026**, and the disagreement it predicted was real rather than
hypothetical: the messenger ladder proposed on 12.09.2026 named the same ways out on a second
axis separate from a direction of `outbound`/`inbound`, while a third change named the
subscriber's own incoming call `call` as well — two mechanisms, one word, in which the modem
either does everything or does not participate at all.

✅ **The owner settled it on 18.09.2026: one flat field, names disambiguated.** The values are
`sms_out` (the gateway's SIM sends), `sms_in` (the subscriber texts the gateway), `call_in`
(the subscriber calls the gateway's SIM), `flash_call` (the vendor dials), `tg_gateway`,
`tg_user`, `max_user` and `app_bot`. **`call` is retired outright** and `modem` is retired in
favour of `sms_out`, which states the direction the old name left to be inferred. The gateway
SHALL hold exactly this vocabulary, and SHALL NOT carry a second one for the same choice.

[partly backed · the vocabulary is `app/verification/routes.py` (the eight names, `call`
absent and named as retired), and the verification half is `verification_rungs`, one row
per rung with its own route, vendor reference and cost. **The message half arrived
20.09.2026 with task 4.4a**: `messages.routed_route` and `messages.routed_operator`,
written by `ModemManager._refuse` and by the passing branch of
`_refuse_what_the_rule_routes_elsewhere` — that is, by the sender, before it hands
anything to the modem, and on both outcomes. Guarded by
`tests/test_send_path_operator_lookup.py` and two mutations reasoned for `bite-lookup.sh` — **a script never written, see task 4.60**
(the decision not recorded on the passing branch, and not on the refusing one).
🔴 **Still unbacked: "SHALL NOT be carried by a route other than the one recorded" is not
enforced for a message** — the column records what was decided, and nothing reads it back
to check what carried it. Reading it back needs a second route to carry a message at all,
and today only the modem does. Also unbacked: the mapping from route to the method an
application is told about, which belongs to the verification door]

#### Scenario: A route is decided and recorded before transmission
- **WHEN** a send or a verification is accepted
- **THEN** its route is decided and stored before any transmission is attempted

#### Scenario: The recorded route is the one used
- **WHEN** an item carries a recorded route of `flash_call`
- **THEN** the modem sender does not pick it up, and the reverse for `sms_out`

### Requirement: The route is chosen by a configured rule keyed on the recipient's operator

Route selection SHALL be expressed as configuration read at send time, keyed on the
recipient's operator as recorded in `number_operators`. Adding, changing or removing an
operator's route SHALL NOT require a code change or a deploy.

An entry's value SHALL be an **ordered list** of routes rather than a single one, and the
gateway SHALL try them in the order written. A single-route entry is the list of length one,
so the modem's own entries are unaffected. The order is the thing being configured: which
paid way out is attempted first is a money decision, it changes as vendors' prices and
reachability change, and it is precisely the decision that must not need a deploy.

No operator name SHALL appear in a branch in the sending path. The rule's initial content —
МегаФон to `[tg_gateway, flash_call]`, everything else to `[sms_out]` — is data, and the change that
introduces it is not permitted to hard-code it, because the event this capability exists for
is the next withdrawal rather than this one. Nor SHALL the ladder's order be hard-coded: an
implementation that tries Telegram first because the code says so, rather than because the
entry says so, satisfies the letter of this requirement and defeats it.

The rule SHALL NOT be keyed on the originating application. An `app_id` in the rule is the
same hard-coding moved into configuration, and it would route by who is asking rather than by
what is reachable. Who is allowed to spend on a paid route is a separate question from which
route reaches a subscriber, and it is answered below rather than by the rule.

The rule SHALL be held in `settings` as a typed setting of its own, validated when it is
saved: each entry SHALL name an operator and a non-empty ordered list of routes drawn from the
known routes, entries SHALL be stripped of surrounding whitespace on write as well as on read,
and an entry naming an unknown route, or naming the same route twice, SHALL be refused at save
time rather than discovered at send time. It SHALL NOT be carried by the existing
dispatch-route setting, which requires a webhook URL on every entry and would reject this rule
outright.

**`settings` rather than `.env`, by the owner's decision of 18.09.2026**, and the code had
already shown why: `seed_from_env()` copies an environment variable into `settings` only for a
key that has no row yet, so `.env` is a one-time seed and never the place a value lives. A
rule kept in `.env` would also need a restart to change, and a restart drops sending sessions
— which is the deploy this requirement exists to avoid, merely spelled differently.

A stored rule that cannot be parsed SHALL raise an operator alert and SHALL NOT be treated as
an empty rule. Read as empty, a broken rule sends the whole of an operator's traffic back to
the route that is rejecting it, and does so without a single line in the log — the one failure
mode of this capability that is both total and silent.

The default route SHALL be an entry of the same rule, changeable by the same means. A default
compiled into the sending path is the hard-coding this requirement forbids, merely spelled
differently.

Two entries name no operator and are spelled with characters an operator name cannot contain,
so that neither can ever be shadowed by a real network. `*` answers for an operator the rule
does not mention. `?` answers for an operator that could not be resolved at all, and it is
separate from `*` on purpose: the numbers most likely to lack an operator row are the ones
never messaged before, and a first-time recipient is exactly who a confirmation code is usually
for, so the unknown case is one the owner configures rather than one arrived at by accident.

A third reserved word, `refuse`, is not a way out but the absence of one, and it is expressible
for the reason the rule is configuration at all: refusing is sometimes the correct answer and
must not need a deploy either. It SHALL stand alone in an entry — a ladder that continues past
a refusal is not a refusal.

A rule that is readable but cannot answer for this operator — no entry, no `*`, no `?` — SHALL
refuse rather than fall back to a route of the implementation's choosing. A default arrived at
by accident is the silent failover this capability refuses by name elsewhere, and it would be
arrived at exactly when the rule is half-configured.

Two entries whose operator names normalise to the same thing SHALL be refused at save time.
Which of the two wins would otherwise be decided by the order of the list, invisibly, and the
data already holds one operator under two spellings.

[backed · `app/verification/rule.py`, guarded by `tests/test_routing_rule.py`; eight mutations
reasoned for `bite-rule.sh` — **a script never written, see task 4.60** — exact-string
matching, a hard-coded ladder order, an accepted unknown route, a broken rule read as empty,
an unanswerable rule guessing the modem, an accepted `app_id`, two spellings of one operator,
and a `refuse` continuing into a ladder; each *would* turn a guard red. **Reasoned, not run**]

#### Scenario: An operator with a configured route
- **WHEN** the rule routes МегаФон to `[tg_gateway, flash_call]` and a verification is requested for a МегаФон number
- **THEN** the verification is routed `tg_gateway` first, and `flash_call` only if that rung declines it

#### Scenario: The ladder's order is data, not code
- **WHEN** the entry for an operator is rewritten as `[flash_call, tg_gateway]` while the service is running
- **THEN** subsequent verifications for that operator try `flash_call` first, with no restart and no code change

#### Scenario: An operator with no entry in the rule
- **WHEN** an item is addressed to an operator the rule does not mention
- **THEN** it is routed `sms_out`, the configured default

#### Scenario: An entry naming a route that does not exist
- **WHEN** a rule entry naming an unknown route is saved
- **THEN** the save is refused with that reason, and the rule in force is unchanged

#### Scenario: The rule changes without a deploy
- **WHEN** a second operator is added to the rule while the service is running
- **THEN** subsequent items for that operator take the new route, with no restart and no code change

#### Scenario: An operator that could not be resolved at all
- **WHEN** a verification is requested for a number whose operator the lookup could not resolve
- **THEN** it takes the rule's `?` entry rather than its `*` entry, and either may be set to `refuse`

#### Scenario: A rule that cannot answer for this operator
- **WHEN** the rule holds neither an entry for the operator nor a `*` entry
- **THEN** the item is refused rather than routed to a way out the implementation chose

### Requirement: A route's credentials live in `settings`, marked secret, and never in the environment

A route that needs credentials SHALL read them from `settings`, and each SHALL be its own
setting marked secret. The admin console SHALL be able to say whether a credential is
configured and SHALL NOT render its value; changing one SHALL NOT require a restart. The
gateway already holds a secret on exactly these terms — `alert_bot_token` — and this is that
precedent, not a new mechanism.

**`.env` is not where such a value lives, and this is a fact about the code rather than a
preference.** `seed_from_env()` copies an environment variable into `settings` only for a key
that has no row yet: placed before the first run it is copied once and lives in `settings`
afterwards, and placed after, it is read by nobody. The gateway SHALL NOT read a vendor
credential from the environment at send time. Owner's decision of 18.09.2026, confirming what
the code had already shown on 11.09.2026.

There are two vendors behind the ladder and therefore two credentials: uCaller's and Telegram
Gateway's. They SHALL be separate settings, and a route whose credential is absent SHALL NOT be
attempted and SHALL NOT be called unauthenticated to find out.

**uCaller's credential is a pair, and SHALL be stored as two settings rather than as the joined
bearer.** The vendor takes the same two values — a per-service secret key and a service id —
three interchangeable ways: as `key` and `service_id` query parameters on a GET, as the same
two fields in a JSON body, or as the header `Authorization: Bearer <key>.<service_id>`. The
bearer is therefore a *derived* form of the pair, and the cabinet hands the two values over
separately. The gateway SHALL assemble the header itself from the two settings, and SHALL treat
either half missing as no credential at all.

This replaces an earlier reading of "a single bearer string carrying both an API key and a
service id" — correct about the header form and wrong about what to store. A joined value puts
the separator in the operator's hands, and a bearer whose dot is missing or doubled is
**indistinguishable from a configured one** on the settings page, which reports only whether a
row is blank; it announces itself as the vendor's `401` on the first live call, and on this
rung a live call is one somebody paid for. Two rows are each pasted verbatim, and a missing
half reports itself as unset.

[backed · vendor reference read by layers 22.09.2026 and captured verbatim in
`captures/ucaller-reference-2026-09-22.md`, which supersedes the 08.09.2026 reading]

A rung skipped for a missing credential SHALL raise an operator alert on the configuration the
gateway ships with, and the ladder SHALL then advance past it as it would past a decline. This
is deliberately the lesser of two bad outcomes: refusing an operator's traffic outright because
the *cheap* rung is unconfigured means nobody on that network logs in, while advancing means
paying more than intended — bounded by the spend ceiling, and loudly. It is the one place in
this capability where a configuration gap costs money rather than traffic, and it is written
down so that it is a decision rather than a discovery.

**A ladder every one of whose rungs was skipped SHALL fail the verification with a reason
naming the missing credentials, and SHALL NOT fall back to `sms_out`.** Advancing past the last
rung leaves nothing to advance to, and the quiet answer — sending it over the modem — is the
silent fallback this capability forbids everywhere else, reached here by exhausting a list
rather than by deciding anything.

[partly backed · the console half is `tg_gateway_token` declared `is_secret` in `app/settings_store.py`, rendered by `_settings_view_rows` (app/admin/router.py) as `configured`/`not set` with no value and no `value=` attribute, guarded by `tests/test_vendor_credentials.py` in both locales and by four mutations reasoned for `bite-credentials.sh` — **a script never written, see task 4.60** — the credential declared not secret, the view handing its value on, the page rendering a `value=` attribute, and the page ceasing to distinguish configured from unset. The guard enumerates credentials by the shape of the key (`_token`, `_key`, `_secret`, `_password`) rather than by name, so uCaller's covers itself when it arrives.

**The environment half is backed** by `tests/test_credentials_do_not_live_in_the_environment.py` and seven mutations: precedence asserted at the `Authorization` header that leaves for the vendor rather than at the store attribute, paired with the control that a key with no row *is* seeded, and with the blank row — the state every estate ships in, written by the first start, so that from the second start `.env` has already lost even where nobody configured anything.

🔴 **The boundary has two surfaces and the obvious census sees one.** "Never in the environment" is a claim about every line in `app/`, so the readers are enumerated off the syntax tree — and that census reports a single sanctioned reader while `app/config.py` reads `.env` on every start through `BaseSettings(env_file=".env")`, with no `os.environ` anywhere in it for a census to find. A vendor credential declared there is the defect in its purest form: read from `.env` at every start, absent from the settings page, unchangeable without a restart. Both surfaces are asserted, the second as a whitelist of one — `admin_password` is the console's own door, kept in `.env` deliberately so that a bad settings write cannot lock an operator out of the page they would fix it from, and that is a gateway credential rather than a vendor's.

uCaller's half now has a home: `ucaller_key` (secret, and covered by the guard above through the shape of its name) and `ucaller_service_id`, declared 22.09.2026, with the bearer assembled in `app/verification/ucaller.py` from both halves or from neither. Guarded by `tests/test_ucaller_credentials.py` and eight mutations in `bite-ucaller.sh` — the dot dropped, the halves swapped, one half accepted as a whole credential, the paste left unstripped, the reader taking the key twice, the secret declared not secret, the row shipped with a value, and the second half never declared. ⚠️ **Nothing in production reads the bearer yet**: the settings page reads the rows, but the vendor is called by nobody until the adapter lands (task 4.17), and `flash_call` has no probe registered and is therefore never offered.

Still unbacked: every rung-skipping clause below, which needs the door]

#### Scenario: A credential placed in the environment after the first run
- **WHEN** a vendor credential is written to `.env` for a key that already has a row in `settings`
- **THEN** the running gateway does not use it, and the value in `settings` remains the one in force

#### Scenario: A secret is not rendered
- **WHEN** an operator opens the settings page
- **THEN** it says whether each vendor credential is configured, and shows neither value

#### Scenario: Half of uCaller's credential
- **WHEN** one of the two settings holding uCaller's key and service id is blank
- **THEN** the rung has no credential, and nothing is sent to the vendor to find out

#### Scenario: A rung with no credential
- **WHEN** the first rung of a ladder has no credential configured
- **THEN** it is not attempted, the operator is alerted on stock settings, and the ladder advances to the next rung

#### Scenario: A ladder with no credential anywhere
- **WHEN** no rung of an operator's ladder has a credential configured
- **THEN** the verification fails with a reason naming them, and nothing is sent over the modem instead

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
usually for.

🔴 **Where the waiting happens is the whole of this requirement, and the owner settled it on
20.09.2026.** The application's answer SHALL NOT wait for the lookup: the enrichment is not
the application's business and an unreachable lookup must not show up as a slow API. **The
send path MAY resolve a missing operator under a short bound of its own**, and SHALL treat
the bound expiring as the unknown-operator case.

That division is forced rather than chosen. Since the route is read from the operator, "the
lookup has not answered yet" and "the lookup will not answer" are different facts with
different right answers, and only the send path is in a position to tell them apart without
making the application wait. Were the door to stop waiting and the sender not to start, the
first message ever addressed to a diverted operator's subscriber would be routed on an empty
cache — it would take the unknown-operator entry and go out over the modem, which is the
route that operator has been rejecting. **The entry `?` therefore means "the lookup did not
answer", never "the lookup has not been asked."**

The bound SHALL be spent only where the cache holds no operator at all. A stale row still
names one, and refreshing it changes no routing decision this rule can make: operators move
numbers on a scale of years and the rule is reviewed on a scale of months, so waiting on a
refresh would buy nothing and cost every send behind it in the queue.

Nothing SHALL be failed when the bound expires or the lookup raises. The unknown-operator
entry answers, whatever it is configured to be, and the item is recorded as having been
routed without a known operator so the case stays countable.

[normative · evidence: app/lookup/operator.py:23-45 · app/api/router.py:36 (`record_operator`
spawned, not awaited) · app/modem/manager.py (`_operator_for`, bounded by
`operator_lookup_bound`) · app/db/migrate.py (`messages.routed_route`,
`messages.routed_operator`) · tests/test_send_path_operator_lookup.py · conf: high]

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

Each route SHALL declare what it can carry. The `sms_out` route carries arbitrary text. The
`flash_call` route carries a verification code and nothing else: the code is the last four digits of
the calling number, so there is no field in which words, a link or a second sentence could
travel. The `tg_gateway` route carries a verification code and nothing else either, for a
different reason — `sendVerificationMessage` accepts a `code` and a `code_length` and no
message body at all, the wording being Telegram's rather than ours.

**Adding the third route therefore does nothing for the applications that are not sending
codes.** `gmp_app`, which sent 63 of August's 111 МегаФон messages and is growing, sends free
text with links, and neither paid route has a field to put it in. The ladder widens how a
*code* reaches a МегаФон subscriber; it does not narrow what this change costs the other
applications, and that cost is stated in the proposal unchanged.

An item whose assigned route cannot carry it SHALL NOT be handed to that route, SHALL NOT be
rerouted to another, and SHALL NOT be attempted. It SHALL be refused with a reason naming the
route and what it cannot carry.

The alternative — quietly sending such a message over the modem instead — is the automatic
failover this change refuses, arrived at by accident rather than by decision.

**The route an item is assigned is the first one its entry names, and only it.** The
requirement forbids rerouting in the same sentence as it forbids attempting, so an entry
reading `[tg_gateway, sms_out]` does not hand free text to the modem: it refuses it, out
loud, counted. Nothing in the rule in force distinguishes the two readings — no entry
names a modem route behind a paid one — so the narrower one costs nothing today, and it
is the one that cannot put the modem back underneath a paid rung by accident. ⚠️ **This
is a reading of the requirement rather than something the requirement said**, taken
20.09.2026 because an implementation had to take one; the owner may widen it, and the
cost of having taken the narrow side is a refusal an operator sees on the first message
rather than a silence they find out about later.

**A route this gateway has not declared able to carry an item carries nothing.** The
three messenger ways out are named in the vocabulary with no adapter behind them and no
wire contract anybody here has read; "not a paid rung" is not "mine", and a sender that
read it that way would put free text out over a route the rule did not name.

[normative · evidence: app/verification/routes.py:74-111 (`_CARRIES`, `carries`) ·
app/modem/manager.py:558-653 (`_refuse_what_the_rule_routes_elsewhere` and `_refuse`,
called at the head of `_send_one` before `encode_submit` and before the modem gate) · app/verification/refusals.py:49 (counted and
alerted on `routing`, which ships on) · tests/test_send_path_refuses_an_uncarryable_route.py
· the scenario below in which the modem **does** carry a code is backed from 21.09.2026 by
app/verification/sms_carrier.py and app/verification/probes.py (`_sms_out_probe`), tasks
4.17b and 4.17c; before them the rung was named everywhere and could carry nothing
· conf: high]

#### Scenario: Free text addressed to an operator routed to the call route
- **WHEN** an application sends arbitrary text to a number whose operator is routed `flash_call`
- **THEN** the message is refused with a reason naming the route, and no AT command is issued

#### Scenario: A verification addressed to an operator routed to the modem
- **WHEN** a verification is requested for a number whose operator is routed `sms_out`
- **THEN** it is carried as an SMS, because the modem route can carry a code

### Requirement: A paid ladder tries its rungs in order, and nothing is bought before every gate that could refuse has been passed

An operator's entry may name more than one route. The gateway SHALL attempt them in the order
written, SHALL attempt each rung of a verification's ladder at most once, and SHALL advance to
the next rung only when the current one **declines to carry** the verification — not when it
carries it and then fails.

That makes three classes of outcome rather than two, and the third is the expensive one: a rung
that **carried and then failed** SHALL stop the ladder and fail the verification with that rung
named. Advancing there would buy the same code at the second vendor while the first vendor's
fee cannot be refunded until its `ttl` runs out — paying twice for one login, which is the
single most expensive mistake this ladder can make.

A rung that cannot carry **this particular item** SHALL be recorded as such and SHALL NOT be
counted as a decline. The case that exists today is a verification with less life left than the
vendor's `ttl` floor of thirty seconds: inflating the `ttl` to reach the floor would hand the
vendor a message outliving the verification it belongs to, while the automatic refund on
non-delivery is tied to that same `ttl`. A decline is a statement about the **subscriber**, and
a rung that appears to decline everyone is a rung that will be taken out of the rule for the
wrong reason.

Each rung's attempt SHALL be recorded **before** its vendor is contacted, and completed
afterwards. The ordering is the money's: a process that dies between a vendor's confirmation
and our record leaves a fee that belongs to nothing, and the only symptom of that is a balance
that drifts.

A route named by the rule that nothing is configured to carry SHALL NOT be attempted, SHALL
raise an operator alert, and the ladder SHALL advance past it. This is the one configuration
gap that costs money rather than traffic — every verification still completes, by the dearer
rung — and it is therefore the one that must be loud on stock settings.

On `tg_gateway`, declining is `checkSendAbility` reporting that the subscriber cannot be
reached, or not answering within the acceptance bound. On `flash_call`, there is no declining rung
below it; a ladder SHALL end in a route that either carries or fails.

🔴 **`checkSendAbility` is not a free probe, and the design must not be built as though it
were.** The vendor's reference is explicit: *"If the ability to send is confirmed, a fee will
apply according to the pricing plan."* What is free is the **second** call — *"Within the scope
of a `request_id`, only one fee can be charged. Calling `sendVerificationMessage` once with the
returned `request_id` will be free of charge, while repeated calls will result in an error"* —
and what is returned is an undelivered message: *"If a message is not delivered within the
specified `ttl`, the request fee will be refunded automatically."*

So the ladder is cheap for exactly two reasons, and neither is "the check is free": an
**unreachable** subscriber costs nothing, and a **confirmed but undelivered** one is refunded.
Against that, the `flash_call` rung is charged for a call that was *placed*, whether or not anyone
read the digits.

Two consequences follow, and both are normative:

1. **Every gate that can refuse a verification SHALL be evaluated before the first rung is
   contacted** — the blacklist, the number's normalisation, the per-number limits, the
   application's entitlement to spend and the spend ceiling. A gate evaluated after a confirmed
   ability check refuses something already paid for, and no refund path exists for a fee whose
   message was never sent: the refund is tied to non-delivery within a `ttl`, and a `ttl` only
   starts when a message is sent.
2. **A confirmed ability check SHALL be followed by exactly one `sendVerificationMessage`
   carrying its `request_id`.** It SHALL NOT be abandoned, and SHALL NOT be repeated with the
   same `request_id`, which the vendor answers with an error rather than a second message.

An ability check that does not answer within the bound SHALL be recorded as **possibly
charged** and counted separately from both outcomes. A confirmation we never saw is a fee that
cannot be spent and cannot be refunded, and without a count an unexplained fall in the vendor's
reported balance has no name to look for.

🟢 **The decline this whole ladder is built on is spelled `PHONE_NUMBER_NOT_AVAILABLE`, and
that spelling comes from a captured refusal rather than from any document.** The vendor's
reference names exactly one error string — `ACCESS_TOKEN_INVALID` — and for "this subscriber
is not in Telegram" says only that "an appropriate error will be returned". Task 1.7, run
20.09.2026 against a real working number whose owner has no Telegram, is what closed the gap:
`{"ok": false, "error": "PHONE_NUMBER_NOT_AVAILABLE"}`, on HTTP 200, charged nothing. The
gateway SHALL recognise it as a decline of the **subscriber**.

⚠️ **One capture fixes the spelling and does not bound the meaning.** Whether the vendor
answers the same string for a number that is malformed, unallocated or merely unroutable is
not established, and SHALL NOT be assumed in either direction. Nothing turns on it while both
readings send the ladder the same way; what will turn on it is the decline count, because a
rung that appears to decline everyone is a rung taken out of the rule for the wrong reason.

An `ok: false` the gateway still cannot place SHALL be treated as **unclassified**: the ladder
SHALL advance past it as it would past a decline, **and** the operator SHALL be alerted. Both,
because the two ways of guessing fail in opposite directions and each is invisible. Read as a
decline, a rotated token would advance every verification to the dearer rung and tell nobody —
the bill would be the only symptom. Read as a failure, an ordinary unreachable subscriber
would raise an alert per verification and the noise would bury the real one. Advancing and
alerting is wrong in neither direction; it is merely loud, and with the ordinary decline now
named it is no longer loud about the ordinary case.

An error string the gateway *can* place — today only `ACCESS_TOKEN_INVALID` — SHALL be
recorded as a refusal of **us** rather than of the subscriber, and SHALL NOT be counted as a
decline against the rung: a rung that appears to decline every subscriber is a rung that will
be taken out of the rule for the wrong reason.

**Whether a message the Gateway accepted and then failed to deliver within its `ttl` escalates
to the `flash_call` rung is not decided by this change.** Until the owner decides it, such a
verification SHALL fail with that reason and SHALL NOT be escalated. The safe default is the
one that cannot spend money on a decision nobody has taken; the argument for the other is that
the fee is refunded anyway, and it is a real argument, which is why this is an open question
and not an omission.

[backed · live samples captured 20.09.2026 by task 1.7 and kept in `captures/`: `probe-1.7-check-declined.json` (the decline, free), `probe-1.7-check-able.json` (the confirmation, `request_cost: 0.01`, `remaining_balance: 99.99`) and `probe-1.7-send.json` (the send carrying the returned `request_id`). Guarded by `tests/test_tg_gateway_adapter.py`. Two halves remain on the vendor reference and are marked where they are asserted: that a second call with the same `request_id` is refused rather than billed, and that an undelivered message is refunded at the end of its `ttl` — no sample shows either, and `is_refunded` has now been absent from ten captures running. The driver itself —
`app/verification/ladder.py` and `app/verification/tg_carrier.py` — is guarded by
`tests/test_ladder_walk.py` and `tests/test_tg_gateway_carrier.py`. **`bite-ladder.sh` (nine)
and `bite-carrier.sh` (eight) exist and run since 22.09.2026**, task 4.60, and between them turn
all seventeen red: gates that do not run first and a gate's refusal ignored, the order held in
the code as "Telegram first", silence recorded as a decline, the bound handed to each rung
again, the rung's row not saying it is in flight, a rung that carried and then failed advancing,
the verification named after the first rung tried, the last rung's silence failing the
verification instead of leaving it in flight — and on the carrier, the rung bought below the
vendor's `ttl` floor, that refusal counted against the subscriber, the fee recorded only after
the send, a constant `ttl` handed to the vendor, a failed send advancing, the outcome map
collapsing a refusal of *us* into a decline, both loud refusals passing silently, and the
control that a carrier which never carries is caught.

⚠️ **Two of the seventeen had to be re-aimed, and both lessons generalise.** Mutating the
*value* of an outcome constant (`REFUSED = "declined"`) proves nothing: the guard compares the
outcome against that same constant, so the mutation is the identity on the test's own data. The
place that distinguishes a refusal of us from a decline is the carrier's `_OUTCOME` map, and
that is where the mutation now lives. And a script that ran only its own file's tests reported
"carried and then failed advances the ladder" as a survivor, because the guard for it lives in
the *other* file — so both scripts run both files, since the property crosses the boundary]

#### Scenario: The subscriber is not reachable in Telegram
- **WHEN** `checkSendAbility` answers `ok: false` with `PHONE_NUMBER_NOT_AVAILABLE`
- **THEN** nothing is charged for it, the ladder advances to `flash_call`, and the decline is recorded against the `tg_gateway` rung

#### Scenario: The vendor refuses with an error string the gateway cannot place
- **WHEN** `checkSendAbility` answers `ok: false` with an error the gateway does not recognise
- **THEN** the ladder advances to `flash_call` as it would past a decline, and the operator is alerted

#### Scenario: The vendor refuses us rather than the subscriber
- **WHEN** `checkSendAbility` answers `ok: false` with `ACCESS_TOKEN_INVALID`
- **THEN** it is recorded as a refusal of the gateway, is not counted as a decline against the rung, and the operator is alerted

#### Scenario: The subscriber is reachable in Telegram
- **WHEN** `checkSendAbility` confirms the subscriber
- **THEN** the code is sent with that `request_id`, no call is placed, and the one fee already incurred is recorded against the verification

#### Scenario: The ability check does not answer in time
- **WHEN** `checkSendAbility` has not answered within the acceptance bound
- **THEN** the ladder advances to `flash_call` and the check is counted as possibly charged rather than as a decline

#### Scenario: A gate that would refuse is reached after the money
- **WHEN** a verification would be refused by the spend ceiling or by the application's entitlement
- **THEN** it is refused before any rung is contacted, and no ability check is made

#### Scenario: A rung that carried and then failed
- **WHEN** a confirmed ability check is followed by a send the vendor refuses
- **THEN** the ladder stops rather than advancing, the verification fails naming that rung, and the fee already incurred stays recorded

#### Scenario: A rung that cannot carry this verification
- **WHEN** a verification has less life left than the vendor's `ttl` floor
- **THEN** the rung is not bought at all, and the outcome recorded is not a decline

#### Scenario: A route nothing is configured to carry
- **WHEN** the rule names a route for which no carrier is configured
- **THEN** it is not attempted, the operator is alerted on stock settings, and the ladder advances to the next rung

#### Scenario: The Gateway took the message and did not deliver it
- **WHEN** a message the Gateway accepted is not delivered within its `ttl`
- **THEN** the verification fails with that reason, no call is placed, and the refund is reflected in the recorded cost

### Requirement: Spending on a paid route is an entitlement of the application, and it is off by default

Whether an application may have its verifications carried by a paid route SHALL be an
entitlement recorded against that application. An application whose entitlement is absent or
off SHALL be refused, with a reason naming the entitlement.

It SHALL default to off, including for a newly issued token. Today any active token can open a
paid verification, and three of the four applications on this gateway never send codes at all:
`gmp_app`, `mprz_bot` and `turbo_route_bot` between them account for none of the traffic this
route exists to carry. A default of on would mean that the first mistake in any of them is
billed rather than logged.

**The default SHALL also apply to every application that already exists when the entitlement
arrives**, and not only to applications created afterwards. Recorded as a norm because it is
the half a schema change silently gets wrong: a default written to take effect for new rows
leaves the guarantee empty on exactly the installations that have the defect, which are the
ones already running. The change that introduces the entitlement SHALL therefore switch every
existing application off, and SHALL be reversible by deploying the previous code rather than
by removing what an operator has since decided — a column dropped on the way back revokes that
decision silently the next time the newer code is deployed.

**Being active remains the stronger switch.** An application an operator has deactivated SHALL
NOT spend, whatever its entitlement says. The two answer different questions — whether an
application may talk to this gateway at all, and whether it may spend money doing so — and a
deactivated application that went on buying verifications because a second switch was left on
from before would be the deactivation failing to mean anything.

A refusal for want of the entitlement SHALL place no vendor call and make no ability check,
SHALL NOT be reported to the application as a vendor failure, and SHALL NOT be quietly carried
over the `sms_out` route instead — for a МегаФон subscriber that is the route that has been
refusing, so the fallback would read as a delivery and behave as a silence.

The entitlement SHALL NOT be part of the routing rule. The rule answers what reaches a
subscriber and stays keyed on the operator alone; this answers who is allowed to pay for it,
and the two questions have different answers that change at different times. It SHALL be
changeable without a restart, by the same means as the rule.

**Owner's decision of 18.09.2026.** It was raised by the critic round of 11.09.2026 as a
finding left for the owner rather than written as a norm; it is now written as one.

[backed · `apps.may_spend`, added by `app/db/migrate.py` as an `ALTER` so that its default reaches the rows already there; the gate is `gates.entitlement_gate` in `app/verification/gates.py`, read per call so that no restart is needed; operated at `POST /admin/apps/entitlement`. Guarded by `tests/test_paid_entitlement.py` and `tests/test_admin_apps.py`, including a test that builds the table in its pre-change shape, populates it and then migrates. ⚠️ **Implemented is not reachable**: the gate has no production caller, because the door that walks the paid ladder belongs to `verify-by-inbound-contact` and does not exist yet]

#### Scenario: An application without the entitlement
- **WHEN** an application whose entitlement is off requests a verification for an operator routed to a paid ladder
- **THEN** it is refused with a reason naming the entitlement, no vendor is contacted, and nothing is sent over the modem instead

#### Scenario: A newly issued token
- **WHEN** a new application token is created and immediately requests a paid verification
- **THEN** it is refused, because the entitlement defaults to off

#### Scenario: An entitled application
- **WHEN** an application whose entitlement is on requests the same verification
- **THEN** the ladder is attempted normally

#### Scenario: An application that existed before the entitlement did
- **WHEN** the change that introduces the entitlement is deployed onto an installation whose applications predate it
- **THEN** every one of them is switched off, and none of them can open a paid verification until an operator grants it

#### Scenario: A deactivated application that still holds the entitlement
- **WHEN** an application an operator has deactivated requests a paid verification
- **THEN** it is refused, whatever its entitlement says

### Requirement: A route that cannot be used fails loudly and does not silently fall back

If the assigned route cannot carry an item it is capable of carrying — the vendor is
unreachable, unauthenticated, or out of credit — the item SHALL NOT be transmitted over the
other route. It SHALL follow the retry and expiry rules already governing its kind, and the
operator SHALL be alerted.

Automatic failover between routes is deliberately absent. Escalating into a paid channel
without a spend ceiling turns a modem fault into an unbounded bill, and escalating out of one
turns a vendor outage into traffic on a route an operator has already refused.

🔴 **That holds even where a rule names the modem behind a paid rung, and the owner settled
it on 20.09.2026.** A ladder written `[tg_gateway, sms_out]` is configuration rather than
failover, and the gateway honours it — but not on a refusal of **us**. When a vendor refuses
this gateway rather than the subscriber, a modem rung later in the same ladder SHALL NOT be
attempted: it SHALL be recorded as withheld, with the rung whose vendor refused named in the
log, and the ladder SHALL continue past it.

The two cases are separated by whom the vendor refused, and nothing else. A **decline of the
subscriber** is a statement about one person — that person is not in Telegram — and a modem
rung behind it is an ordinary fallback that goes on working. A **refusal of us** is
gateway-wide: a rotated token or an empty account refuses every verification, and refuses them
all inside the same minute. Carrying those over the modem is precisely the flood the paragraph
above forbids, arriving through the one door a rule can open.

Withholding SHALL NOT raise a second alert. The refusal that caused it already woke the
operator with the vendor named, and two lines about one event is how the first one is buried.

That argument applies to the paid route itself, not only to escalation into it. A paid route
SHALL have a configured ceiling on how many paid items it may carry per rolling hour and per
rolling day, counted across every number and every application. A request that would exceed it
SHALL be refused with a reason naming the ceiling, no vendor call SHALL be placed, and the
operator SHALL be alerted on the first refusal within the dedup window. A ceiling reached SHALL
NOT be reported to the application as a vendor failure.

The vendor's own limits do not provide this: they are per number — four a minute, thirty a day
— and a loop over five hundred numbers violates none of them while spending four hundred
roubles. A balance floor is not a ceiling either; it reports money already gone.

**The ceiling SHALL count across all paid routes together, not per vendor.** There are two
prepaid accounts behind the ladder now, and a ceiling counted per rung lets a run of
verifications spend twice the intended amount by advancing from one rung to the other — which
is exactly what the ladder does by design. What is being bounded is the bill, and the bill is
one.

**The ceiling SHALL count every attempt on a paid route, including the ones that turn out to
cost nothing.** A ceiling counted over confirmed charges would be blind to exactly the
attempts most likely to have cost money in silence: an ability check that never answered may
have been confirmed and billed at the vendor without our ever learning its `request_id`, which
is the one class of spend this design cannot attribute to anything. Counting attempts also
makes the ceiling decidable before a vendor is contacted, which is what lets it refuse without
spending.

**Its windows SHALL roll rather than reset on a clock**, for the reason the per-number limits
do: this database stores naive UTC and both vendors are Russian, and a calendar window read in
the wrong zone resets early and spends confidently in the gap.

**Its numbers SHALL be settings, and SHALL be set against observed traffic rather than
chosen.** A ceiling below the busiest hour this gateway has really had stops being a guard
against a runaway and becomes a refusal of legitimate work — and that failure is the harder of
the two to attribute, because it presents as a gateway that has quietly stopped verifying
anyone.

Every alert this requirement raises SHALL name **which** vendor it is about. With one paid
route "the vendor is out of credit" was unambiguous; with two it is the question the operator
has to answer before they can act, and answering it by reading a log is the difference between
a two-minute top-up and an outage.

[partly backed · the spend ceiling is `gates.ceiling_gate` in `app/verification/gates.py`, counting `verification_rungs` over `routes.PAID_ROUTES` in rolling windows, with `verification_paid_per_hour` and `verification_paid_per_day` as its settings; guarded by `tests/test_spend_ceiling.py`. 🔴 The shipped numbers are measured rather than chosen — read from this gateway's own live database on 20.09.2026: 2391 messages between 17.04.2026 and 20.09.2026, 601 of them to МегаФон (both spellings matched by hand, since `upper()` is ASCII-only in this build and counts 397 of the 601). The busiest МегаФон hour in five months held 20 messages and the busiest day 47; a verification may consume two paid rungs, so the worst load ever observed is about 40 attempts an hour and 94 a day, and the ceilings of 100 and 300 sit above that with room while stopping a runaway in minutes. The vendor-credential and out-of-credit halves stay unbacked on the uCaller side, which has no adapter (task 4.17, blocked on task 1.1). 🔴 **"SHALL NOT be transmitted over the other route" is guarded as the absence of *automatic* failover, and measurement is what fixed that reading** (task 4.14, `tests/test_vendor_failure_spares_the_modem.py`, five mutations reasoned for `bite-modem.sh` — **a script never written, see task 4.60**): driven directly, `ladder.walk` does carry a verification over an `sms_out` rung when the rule names one behind a paid rung, and that is configuration with an operator's name on it rather than a fallback. What the gateway guarantees, and what is now guarded, is that the rungs attempted are exactly `rule.route_for`'s answer — nothing is appended when a vendor refuses us for credentials or for want of credit, and when every rung the rule named has refused, the verification fails rather than finding its way onto the modem. 🟢 **The owner settled on 20.09.2026 that a rule naming `sms_out` behind a paid rung is not honoured on a refusal of *us*, and that is now implemented** (task 4.14a, `ladder._MODEM_ROUTES` and the withholding branch of `ladder.walk`, `WITHHELD` recorded as the rung's outcome). Guarded by the same file and by six further mutations reasoned for `bite-withhold.sh` — **a script never written, see task 4.60**, among them the norm reaching too far — withholding the modem after a decline of the *subscriber* turns the positive control red, which is what keeps the rule narrow enough to leave a working modem working]

#### Scenario: The vendor rejects our credentials
- **WHEN** a vendor answers with an authentication error
- **THEN** nothing is sent over the modem instead, the operator is alerted with that vendor named, and the existing retry rules apply

#### Scenario: The vendor is out of credit
- **WHEN** a vendor reports insufficient balance
- **THEN** the operator is alerted with that reason and that vendor's name, and nothing is rerouted

#### Scenario: A rule names the modem behind the rung whose vendor refused us
- **WHEN** an operator's ladder is `[tg_gateway, sms_out]` and the Telegram rung answers with a refusal of this gateway
- **THEN** the modem rung is recorded as withheld rather than attempted, the verification fails naming it, and no second alert is raised

#### Scenario: A rule names the modem behind a rung the subscriber declined
- **WHEN** the same ladder's Telegram rung declines the subscriber rather than refusing this gateway
- **THEN** the modem rung carries the verification as the rule configured it

#### Scenario: The ceiling counts the ladder, not the rung
- **WHEN** verifications advance from the first rung to the second often enough that the two rungs together reach the configured ceiling
- **THEN** the next request is refused by the ceiling, even though neither rung reached it alone

### Requirement: What the rule costs is countable per operator

The gateway SHALL record, per operator, how many items it refused because the operator's
configured route could not carry them, and that count SHALL be visible to an operator without
reading the database.

A rule set during an outage outlives the outage. When МегаФон starts accepting traffic again,
the rule will still be in force, and the applications that do not send codes will still be
refused — with nothing on any screen to say so. A count is the difference between a rule that
is reviewed and a rule that is forgotten.

[backed · `app/verification/refusals.py`, counting rows of `route_refusals` grouped on the
folded operator name (`rule.fold` — NFKC + casefold, in Python, never in SQL), reachable at
`/admin/stats` beside the message counters and under the same period control. Guarded by
`tests/test_route_refusals.py` and by thirteen mutations reasoned for `bite-refusals.sh` — **a script never written, see task 4.60**. ⚠️ **Counted is
not produced:** the only caller today is `ladder.walk`, which has no production caller of its
own — the send-path refusal that produces the measured seventy a month is task 4.6 and calls
`refusals.record` the same way]

The count SHALL be answerable per application as well as per operator: it decides whether to
call the developer of a particular application or to drop the rule, and "seventy refusals"
answers neither.

The count SHALL NOT be relied upon as evidence that the route has recovered. Once a rule is in
force, the modem route to that operator receives no attempts at all — codes leave by the other
route and text is refused before any AT command — so the one source of proof that the refusal
has ended is the thing the rule switches off. The gateway SHALL therefore retain a way to
observe recovery: either a rate-bounded probe send to that operator over the `sms_out` route,
counted separately, or an alert once a rule entry has been in force longer than a configured
review period.

**The entries that name no operator are outside that report.** `*` and `?` are the gateway's
baseline rather than a diversion — they answer for an operator with no entry and for one that
could not be resolved — and a rule holding only them has diverted nothing to review. Reporting
them every review period would teach an operator to ignore the channel that also carries the
entries that did divert. Either set to `refuse` remains audible: every item it refuses is
counted and alerted as a refusal.

**When an entry's routes change, its review period SHALL start again**, because the decision
was revisited and that is what the period measures. An entry removed from the rule SHALL stop
being reported: a rule that no longer names an operator is not one anybody needs reminding
about.

A refusal SHALL reach the operator on the configuration the gateway ships with. It SHALL NOT
depend on a notification toggle that is off by default — `notify_send_errors` is such a toggle
— and it SHALL be deduplicated on the operator and the route rather than raised once per
refused message, since the measured traffic is about seventy refusals a month and rising.

[backed · `refusals.record` raises it on the `routing` category, which `notify_routing_errors`
carries and which ships **on** — `notify_send_errors` is untouched by this path — with
`dedup_extra=f"refused:{folded operator}:{route}"`. The review report is `refusals.review_step`,
hourly from `main.py` as the non-essential `routing-review` loop, bounded by the
`operator_route_review_days` setting (30) and raised at most once per period per operator.
Guarded by `tests/test_route_refusals.py`, which drives the real `notify` over a fake notifier
so the toggle is exercised rather than stepped over, and by the mutations above — the alert
moved to the default-off toggle, the dedup key losing the route, losing the operator, and
dropped entirely; the review reported on every tick; the baseline entries reported; and the
review period hard-coded]

#### Scenario: Refusals accumulate against an operator
- **WHEN** three applications are refused for one operator over a day
- **THEN** the count for that operator shows three, attributable to that operator rather than to the gateway as a whole

#### Scenario: The refusals are attributable to an application
- **WHEN** an operator asks which applications the refusals came from
- **THEN** the count answers per application as well as per operator

#### Scenario: A rule outlives the outage that justified it
- **WHEN** an operator's entry has been in force longer than the configured review period
- **THEN** the operator is alerted that the rule is still in force and has not been reviewed, once per period rather than once per check, and the alert names what the entry has cost since it came into force

#### Scenario: An entry that was revisited
- **WHEN** an entry's routes are rewritten
- **THEN** its review period starts again, and it is not reported until the new period has passed

#### Scenario: The rule holds only its baseline entries
- **WHEN** the rule holds `*` and `?` and no operator entry, for longer than the review period
- **THEN** nothing is reported, because neither entry diverts anything to review

#### Scenario: The refusal alert arrives on the shipped configuration
- **WHEN** a message is refused for want of a usable route on a gateway whose settings are untouched
- **THEN** the operator is alerted, once per operator and route within the dedup window
