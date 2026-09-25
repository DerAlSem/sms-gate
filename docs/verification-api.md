# Phone verification — integration contract

How an application asks this gateway to prove that a person holds a phone number, and how
it learns the answer. Four HTTP calls and one optional push.

Nothing here changes `POST /sms/send`, `GET /sms/{id}` or the delivery webhook. A
verification is not a message you send: you never compose the text, you never choose the
carrier, and on most routes no text exists at all.

> **Status.** The doors below are built and tested. Which routes a given deployment can
> actually carry is configuration and is stated under
> [What a deployment can carry today](#what-a-deployment-can-carry-today) — read that
> section before you plan a release date.

## The shape

```
POST /verifications              → id + the routes that can carry it right now
POST /verifications/{id}/route   → you pick one; the person is told what to do
   … the person acts: types the code back, calls us, or texts us …
POST /verifications/{id}/check   → only when the person types the code back to you
GET  /verifications/{id}         → the truth, at any moment
```

Two things about that shape are load-bearing.

**You do not choose a mechanism — you choose from what we offer.** You never tell us an
operator, a vendor or a SIM, and you never hold a table of which networks work. You send
the number; we answer with the routes that can prove *at that moment* that they can carry
it, cheapest first. Take the first one silently, or show the person the list. Both are
served by the same answer.

**Never hard-code a route name.** The set of routes is configuration and grows. Code
against the list you were given, in the order you were given it; render whatever
`instruction` you were handed. An application written that way needs no change when a
route is added, removed or reordered.

## Authentication

Same as the rest of the API: `Authorization: Bearer <token>`, one token per application,
issued by the operator at `/admin/apps`. Base URL is the deployment's own.

A verification belongs to the application that created it. Another application asking for
it by id gets `404`, not `403` — it must not be able to learn that the id exists, still
less spend its attempts.

## POST /verifications

Open a verification. **Nothing is placed, sent, called or charged by this call.** All it
costs is the set of precondition probes, and those are bounded as a whole.

```http
POST /verifications
Authorization: Bearer <your token>
Content-Type: application/json

{
  "phone": "<the subscriber's number — E.164, or national; we normalise it>"
}
```

`phone` is the only field. A request naming a route, a vendor, an operator — or supplying
its own code — is refused rather than partly honoured.

### Response 200

```json
{
  "id": 9,
  "status": "pending",
  "routes": [
    {
      "route": "call_in",
      "instruction": "Call <number> from the number being verified. The call is not answered and costs you nothing; hang-up is ours.",
      "number": "<number>"
    },
    {
      "route": "sms_in",
      "instruction": "Text the code you were shown to <number> from the number being verified.",
      "number": "<number>"
    },
    {
      "route": "flash_call",
      "instruction": "Wait for a call to the number being verified and read the code off the calling number: it is the last four digits. Do not answer the call.",
      "number": null
    }
  ]
}
```

| field | meaning |
|---|---|
| `id` | the verification id. Use it in every later call. **It is not a message id** — the two spaces overlap from the first row of each table |
| `status` | `pending` |
| `routes` | what can carry it right now, **cheapest first**. Never empty on a `200` |

`instruction` is what the person must do, in words they can act on. It names an address
and never an identity: which SIM answers, which vendor account paid, which modem is in the
rack — none of that is yours or theirs to see. See
[The instruction is English](#the-instruction-is-english) before you build a screen on it.

`number` is that same address **as data**, and it is what you should read if you write your
own wording. It carries the number the subscriber must dial or text on the routes that ask
them to reach us (`call_in`, `sms_in`), and is `null` on every route where the gateway is the
one that acts — there is nothing for the person to dial on those, and a number would be an
address to somewhere that is expecting nothing.

The field is **additive**: it was added 22.09.2026, it has a default, and an application
written before it is unaffected.

Routes whose instruction is empty are the ones where the person only has to wait: a
message or a call comes to them.

### Refusals

| status | body | when |
|---|---|---|
| `422` | `{"detail": {"error": "no_route_available", "message": "…"}}` | nothing can prove it can carry this number now. **No verification is opened** — we do not hand you a session whose only possible ending is to expire |
| `422` | `{"detail": {"error": "number_blacklisted", "phone": "…"}}` | the number is on the gateway's blacklist |
| `422` | `{"detail": [ … ]}` | ordinary validation: unparseable number for the configured region, or a field we forbid |
| `503` | `{"detail": {"error": "no_code_available", "message": "…"}}` | too many verifications are open on this number at once to give this one a distinct code |
| `401` | `{"detail": "Invalid or missing token"}` | |

`no_route_available` is an answer, not an outage. Treat it as "not now, by this gateway" —
the routes it would have offered are the ones whose precondition failed to prove itself in
the last few seconds.

## POST /verifications/{id}/route

Choose a route. **This is the only moment a verification acquires one**, and it acquires
exactly one: a list to choose from is not a licence to hop.

```http
POST /verifications/9/route
Authorization: Bearer <your token>
Content-Type: application/json

{ "route": "sms_in" }
```

The offer is re-proved here rather than trusted from the creation answer — a proof decays,
and the gap between offering and selecting is exactly where it decays.

### Response 200

```json
{
  "id": 9,
  "route": "sms_in",
  "status": "pending",
  "reason": null,
  "code": "4821"
}
```

🔴 **`route` is the rung that actually carried it, which is not always the one you asked
for.** Where the gateway carries the verification itself — `tg_gateway` today — it walks the
ladder configured for that subscriber's operator before answering you, starting at the rung
you chose. If that rung declines the subscriber and a later one carries it, this field names
the later one, and it is the one your screen must describe: told to watch Telegram for a
person Telegram declined, someone waits in the wrong place while the phone in their hand
rings. The ladder settles **inside this answer** — you are never moved to a different route
after we have replied.

**`status` and `reason` are the other half of the same sentence.** If the ladder ran and
nothing carried the verification, this answer says `"status": "failed"` with a `reason`
naming the rungs and what each of them did, rather than `pending` you would have to poll to
see through. `reason` is `null` whenever there is nothing to say.

**`code` is non-null on `sms_in` and on nothing else.** That route is the one where the
person is the sender: they read the code off your screen and text it to us from the number
being verified, so you have to be able to display it. On every route the gateway itself
carries, `code` is `null` — a code handed back there would let you confirm a verification
without the person ever having been reached, which is the whole of what a verification is
for.

Show that code. Do not log it, do not store it past the verification, and do not send it
anywhere yourself.

### Refusals

| body | when |
|---|---|
| `{"detail": "Verification not found"}` (`404`) | no such id for your application |
| `{"detail": {"error": "verification_failed" \| "verification_expired" \| "verification_confirmed", "reason": …, "message": …}}` (`422`) | this verification has ended. **Failure is terminal** — open a new verification to try again |
| `{"detail": {"error": "already_selected", "route": "…", "message": …}}` (`422`) | it is already being carried by that route |
| `{"detail": {"error": "route_not_offered", "route": "…", "message": …}}` (`422`) | that route was not offered, or can no longer prove itself |
| `{"detail": {"error": "expired", "route": "…"}}` (`422`) | it ran out between your two calls |
| `{"detail": {"error": "refused", "route": "…", "reason": …, "message": …}}` (`422`) | a rung the gateway pays for was refused **before any vendor was contacted** — the application is not entitled to spend, the gateway's own spend ceiling is reached, or this number has had too many paid attempts too recently. Nothing was placed and nothing was charged; this is not a vendor failure. `reason` names which of them it was |

## POST /verifications/{id}/check

Only for the routes where the person reads a code and types it back into **your**
application. On `call_in` and `sms_in` the person acts on the network instead and you
never call this door.

```http
POST /verifications/9/check
Authorization: Bearer <your token>
Content-Type: application/json

{ "code": "4821" }
```

### Response 200

```json
{
  "id": 9,
  "status": "confirmed",
  "outcome": "confirmed"
}
```

| `outcome` | meaning |
|---|---|
| `confirmed` | it is proven. `status` is `confirmed` |
| `wrong_code` | one attempt spent |
| `no_attempts_left` | the attempt that reached the ceiling ended the verification. `status` is `failed` |
| `expired` | the window closed |
| `already_confirmed` | it was already proven. Idempotent, and cheap |

A bare "no" is not an answer here on purpose: you are a barrier with a person standing at
it, and "expired" and "wrong" mean different things to them.

The ceiling on wrong codes is the operator's setting `verification_max_attempts`, which
ships at **5**. `404` if there is no such verification for your application.

## GET /verifications/{id}

The truth, at any moment, and the source of truth for everything below.

```json
{
  "id": 9,
  "phone": "<the number being verified, normalised>",
  "status": "confirmed",
  "route": "call_in",
  "method": "call_in",
  "reason": null,
  "routes": [],
  "attempts": 0,
  "created_at": "2026-09-21T09:14:05Z",
  "expires_at": "2026-09-21T09:19:05Z",
  "confirmed_at": "2026-09-21T09:14:41Z"
}
```

| field | meaning |
|---|---|
| `status` | `pending` \| `confirmed` \| `failed` \| `expired` |
| `route` | the route you selected, or `null` if you have not selected one |
| `method` | **what actually proved it**, on a confirmation. Not always the route it was carried by — see below |
| `reason` | free text on a failure, `null` otherwise. Written for a human; do not branch on it |
| `routes` | **what is left to try, and only on a `failed` one.** Empty while it is still being carried, and empty on a confirmation |
| `attempts` | wrong codes spent |
| `created_at` | when it was opened, ISO-8601 UTC |
| `expires_at` | the deadline. A route may bring it in; nothing may push it out |
| `confirmed_at` | when it was proven, or `null` |

The code is in no field of this answer, ever, and neither is it in `reason`: text coming
back from a vendor or an exception has the code taken out of it at the moment it is
stored, not at the moment it is read.

### `method` is not `route`

`route` is how the gateway carried it. `method` is what proved it, and the two vocabularies
are different because the proofs are not equally strong.

| `method` | what happened | strength |
|---|---|---|
| `call_in` | a call arrived from the number being verified | the caller number is asserted by the network, and a network can be lied to |
| `sms_in` | a message arrived from the number being verified, carrying the code | an arriving event **and** a secret the attacker would also have to hold |
| `check` | the person typed the code back into your application | the code reached the person over whichever route carried it |

An application whose stakes do not tolerate the weakest of these can see what it got and
refuse it. That is the reason the field exists; if your stakes are ordinary, ignore it.

### `routes` on a failure is the way on

A rung that failed ends the verification, and the gateway does **not** move to another by
itself. Moving on is your act, and an act needs something to act on — so a `failed`
verification carries the remaining ladder, freshly proved at the moment you read it, with
the failed route dropped by name. Open a new verification and select from that list.

## The push

Optional. The gateway can call your endpoint when a verification reaches a terminal state,
so you learn the outcome without waiting for your next poll. It rides on the same
`delivery_dispatch` configuration as the SMS status webhook — one URL and one bearer per
application — and is documented for that side in
[`delivery-webhook.md`](delivery-webhook.md).

```http
POST <your webhook url> HTTP/1.1
Content-Type: application/json
Authorization: Bearer <your token>

{
  "object": "verification",
  "verification_id": 9,
  "status": "confirmed",
  "method": "call_in",
  "reason": null,
  "occurred_at": "2026-09-21T09:14:41Z"
}
```

| field | always? | meaning |
|---|---|---|
| `object` | yes | always the string `verification` |
| `verification_id` | yes | the id `POST /verifications` returned |
| `status` | yes | `confirmed` \| `failed` \| `expired`. Never `pending` |
| `method` | yes | as above; `null` unless confirmed |
| `reason` | yes | free text on a failure, else `null` |
| `occurred_at` | yes | ISO-8601 UTC |

🔴 **The subject is in `verification_id`, and there is no `id` field at all.** This is not
an accident of naming. The status webhook for an outbound SMS carries *its* subject in
`id`, both bodies arrive at the same URL, and both use the words `failed` and `expired` —
so a receiver keyed on `id` and `status`, which is the whole of the older contract, would
read a verification as a message and mark an unrelated one. Reply `200` to anything you
accept; we do not read the body.

## Things that will bite you

### Polling is the recommended path, and for a confirmation it is also the fast path

`GET /verifications/{id}` is authoritative. The push is an accelerator on top of it, and it
is **not instant**: terminal states are swept out to applications on a **one-minute tick**,
so a confirmation that happened a second ago can be up to a minute from reaching your
endpoint. The poll sees it immediately.

If a person is standing in front of a barrier waiting to be let through, poll. Use the push
to reconcile, not to open the gate.

**So poll is what we recommend, and the push is the option.** Both are supported and neither
is deprecated; this is our judgement about which to reach for first, settled 22.09.2026.
Polling needs nothing from you — no public address, no signature check, no handling of a
delivery that arrives twice — and the screen is already open in front of the person, so a
poll each second inside a five-minute window is tens of requests rather than load. Take the
push when you have an endpoint already and want the outcome without waiting for your next
tick.

Delivery of the push is best-effort on the same terms as the SMS one: up to 3 attempts
(configurable), 10 s timeout each, 1 s then 4 s between them, then dropped. A restart
mid-retry drops it. Nothing is persisted and there is no queue.

### Five minutes, and the clock is ours

A verification's default life is **five minutes** (`verification_ttl_seconds`, 300 s). A
route may hold a **shorter** window of its own and the deadline is brought in to match; no
configuration can push it out past what you were told at creation. Read `expires_at` and
believe it rather than computing your own.

### Failure is terminal

A verification that failed is over. It does not reopen, it does not re-arm, and its attempt
counter is not refilled. The next attempt is a **new** verification — which is also how the
person gets a fresh code and a freshly proved ladder.

### `expired` says the clock ran out, and it is not the only way to wait in vain

`expired` means the clock ran out. Its `reason` is `window_expired` and there is nothing
to say beyond the clock — the word names the field it came from, because a **delivery**
expiry reported by a carrier is a different fact about a different thing, and one of the
two is about money.

What is **not** reported as an expiry is a route that died under an open verification: the
sweep ends such a verification as `failed` with a reason naming the route that lost its
precondition. Told to a person who did call, on time, from the right number, "expired"
would be the gateway reporting the one thing that did not happen.

### Be idempotent, and ignore what you do not recognise

An outcome may reach you twice — once by push and once by your poll, or twice by push
after a restart. Applying it twice must be a no-op. We may add fields to any body here;
ignore the ones you do not know rather than rejecting the request.

### The instruction is English

`instruction` is written in English and the gateway does not translate it. If your
application speaks to the person in another language, you will want to compose your own
wording per `route`.

✅ **The number the subscriber must dial or text is handed to you as data**, in `number`
beside `instruction`, since 22.09.2026. Read it from there and write your own sentence.

🔴 **Do not recover the digits from `instruction` with a regular expression.** That would
make our English wording an unwritten part of the contract, and it would break on the day
somebody improves a sentence — silently, on your side, in front of a person at a barrier.

## What a deployment can carry today

Stated for the production deployment as of **25.09.2026**. The vocabulary of routes is
fixed and flat. Every name the gateway knows:

| route | who acts | carried today? |
|---|---|---|
| `call_in` | the subscriber calls the gateway's number; the call is not answered | **yes** — the gateway's number is configured and handed to you in `number` |
| `sms_in` | the subscriber texts the code to the gateway's number | **yes**, offered only when nothing cheaper proved itself (the subscriber pays for one SMS) |
| `sms_out` | the gateway texts the code to the subscriber | **only for an application with a verification template** configured by the operator — none is configured today; ask for one if you want this route |
| `flash_call` | a vendor calls; the last four digits of the calling number are the code | **wired and configured**; the first paid call on production has not been observed yet |
| `tg_gateway` | the code arrives in Telegram | **yes** — carried a code on production on 22.09.2026 |
| `tg_user`, `max_user`, `app_bot` | messenger accounts | named, and carried by nothing |

Which of these a particular number is offered is decided per request, by what can prove
itself for that number at that moment — you learn it from `routes`, never from this table.

**Telegram, then a call — inside one selection.** When you select a rung, the gateway walks
the routing rule for the subscriber's operator **from that rung onwards**. For МегаФон the
rule reads `tg_gateway`, then `flash_call`: select `tg_gateway`, and if Telegram declines the
number when we ask it to send, the gateway moves to `flash_call` within the same
`POST /verifications/{id}/route`. The answer's `route` names the rung that carried, and its
`instruction` is what to show the person. A rung the rule does not name for that operator is
carried alone, with no continuation.

If Telegram **accepted** the message and it then went undelivered, or the person says
nothing arrived while the verification is still `pending`, there is no automatic second
rung: open a **new** verification and select the next route you are offered (see
[Failure is terminal](#failure-is-terminal)).

The vendor is told where to report delivery (since 21.09.2026), so a Telegram message it
accepted and then failed to deliver ends the verification with a reason instead of waiting
out the clock.

## Why this matters for МегаФон subscribers — today

Since **22.09.2026** the gateway does not send arbitrary text to МегаФон numbers:
`POST /sms/send` to such a number is accepted and then ends `failed`, with `error` reading
*"the route the rule names for МегаФон is tg_gateway, which cannot carry arbitrary text"*.
The operator rejects our SMS route, and before that date such messages looked delivered to
you and never reached the person. A login code sent through `/sms/send` therefore reaches
**no** МегаФон subscriber. Through the doors in this document it can — by Telegram, then by
a call. That is the whole reason to move code delivery here.

## What we need from you

| | |
|---|---|
| `app_id` | your application id in the gateway (the one your API token maps to) |
| `webhook_url` | full absolute `https://…` URL, **only if** you want the push |
| `bearer` | the token we send as `Authorization: Bearer <token>` on the push |

The operator configures these. There is nothing to deploy on your side beyond the endpoint,
and the endpoint is optional — an application that polls needs no configuration from us at
all beyond its API token.
