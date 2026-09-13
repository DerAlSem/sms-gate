## Why

Since 06.09.2026 ~18:30 MSK МегаФон has been refusing this gateway's outbound SMS.
Measured on the production ledger on 08.09: of 55 messages sent to МегаФон since the
outage began, 49 came back `failed` and 6 were delivered — roughly one in nine gets
through. Six probes that day differed in wording, in alphabet and in whether they
carried a code at all, and all six were rejected identically. The cause is the sender's
route to that operator. Nothing in the message and nothing in this codebase changes it.

The gateway has exactly one way to reach a subscriber: the modem. That was never a
design decision, it was the absence of one.

**Owner's decision, 12.09.2026:** the second way out is not another way to send SMS and
not a paid vendor. It is a pool of **user accounts** in Telegram and MAX, owned by the
gateway, which write to a person's private chat. They carry verification codes and
payment links — everything an SMS carries — and they are addressed by phone number, so
no prior link between a phone and a chat is needed.

⚠️ **`upper()` and `LIKE` in SQLite are ASCII-only.** `number_operators` holds МегаФон
under two spellings — `МЕГАФОН` (120 numbers) and `МегаФон` (57) — and a
case-insensitive match silently counts only one. Every figure here matches both
spellings explicitly.

## What Changes

- **A send acquires a ladder of routes.** The modem stops being the only way out. The
  gateway tries routes in a configured order and stops at the first that accepts the
  message; a route that cannot be used is skipped, not retried forever.
- **Two new routes exist: `tg_user` and `max_user`** — user accounts, addressed by the
  recipient's phone number. Telegram resolves the number by contact import; MAX resolves
  it by `search_by_phone`. Neither needs the person to have met us inside the messenger.
- **The route that carried a message becomes observable.** The message row records it,
  `GET /sms/{id}` returns it, and the delivery webhook carries it, so the consuming
  application can tell the person where the code went.
- **The gateway can be asked when a number was last reached.** A read-only door reports,
  per route, when that route last carried a message to a number, whether the delivery was
  reported or inferred, and the blacklist state — built from records this change already
  requires, contacting no vendor. It answers about a channel and never about an identity:
  the applications each see only their own traffic, and only the gateway sees the number
  across all of them.
- **An application can force the ladder lower.** A request may name routes to skip, which
  is how a "it never arrived — send me an SMS" button is served without the gateway
  owning any timer.
- **The sender identity is derived from the caller's credential**, and a brand it is not
  permitted to use is refused rather than substituted.
- **Per-sender rate limits** bound how fast one account writes to strangers, because the
  account is limited by the recipient's spam report, not by our own volume.

Explicitly **not** in this change, by the owner's decisions:

- **no paid route, and therefore no spend ceiling.** The rungs are the application's own
  bot, `tg_user`, `max_user`, and the modem. Nothing in this ladder escalates into a paid
  channel, so the 07–08.09 decision against automatic failover is not touched. A ceiling
  becomes mandatory for whichever change adds a paid route.
- **no phone↔chat registry, and no bot route in the gateway.** The top rung is the
  consuming application's own bot, and the application owns it: the gateway holds no
  foreign bot token and no foreign `chat_id`.
- **no code generation in the gateway.** The application keeps generating and checking
  its own code. `POST /verifications` belongs to whichever change needs a route whose
  code is born at the vendor.
- **authorization stays in the application.** This change is about delivery.

## What the critique circle changed

One circle, both critics, run on 12.09.2026 against the first redaction of these deltas.
Thirty-two findings; the consolidation is here rather than in a design document because a
resolution that lives in prose does not bind.

The structural answer to most of them is one decision: **the ladder sits above the
existing modem path and the modem is always its last rung.** Every requirement of that
path then applies to a modem attempt exactly as before — the part budget, the hold while
the modem is off the network, the retry budget, `failed` written in one place — so the
ladder cannot short-circuit them and none of them needed rewriting.

The findings that changed behaviour rather than wording:

- **A messenger acceptance is `delivered` with delivery inferred, never `sent`.** The
  expiry sweep selects on `status = 'sent'` with no route predicate, so every messenger
  delivery would have been reported to its application as `expired` five minutes later.
  Verified in code, not accepted on a critic's word.
- **An attempt has a fourth outcome, `indeterminate`.** With three, a connection lost
  after the frame was written had to be called "unavailable", and the ladder would send
  the same code down the next rung: two different codes, neither working.
- **An absent route list means the modem alone.** Settings are seeded from code defaults
  for any key with no row, so an empty default would have failed every message on the
  first restart after deployment, on a host carrying live customer traffic. Verified in
  code.
- **Delivery evidence that suppresses a blacklist count must be modem evidence.**
  `has_delivered_to` has no route predicate, so one messenger delivery would have made a
  number with a dead SIM permanently immune to blacklisting. Verified in code.
- **Every path that creates an outbound message must offer it to the ladder.** There are
  four today, and an invariant placed on one of them is not an invariant. Verified by
  reading all four call sites.
- **The class of a message must be a stated, recorded rule.** The whole configuration is
  keyed on it, and the live parking template is `SokolParking: ####` — a rule keyed on
  "the text is four digits" would have excluded 446 of the 448 messages this change was
  measured on from the ladder it was built for.
- **Rate bounds must be durable and claimed atomically, and bounded per recipient too.**
  This process exits by design; an in-memory window would hand an account a fresh
  allowance inside the same hour on every restart, and doubling the rate to strangers is
  the documented route to a permanent limit.
- **A rung ledger, an aggregate alert, disclosure records, a reply path, an opt-out, a
  sender presentation, and the session treated as a credential.** Each closes a way this
  design could have failed silently or left a person unanswerable.

Deliberately **not** resolved, and named instead:

- **Whether the blacklist should gate the messenger routes at all.** It is built from SMS
  failures, so a number blacklisted for a dead SIM is also denied the messenger route
  that would reach it. The specification keeps today's behaviour — the blacklist gates
  every route — and says so explicitly rather than by accident. Narrowing it to the modem
  rung is the owner's decision and has not been taken.
- **The legal standing of a cross-application reachability answer.** The owner decided on
  13.09.2026 that the door answers across every application's traffic — the narrow
  alternative would tell an application only what it already knows — and the specification
  is normative on it. What is **not** settled is what that makes this gateway: answering
  one application with evidence produced by another's traffic links the customers of two
  brands through one service, which is a different object than delivering on each
  application's behalf separately. The design keeps the answer to routes, times, evidence
  strength and blacklist state, and forbids application identity, text and counts, which
  narrows the exposure but does not decide the question. It goes to a lawyer in the same
  package as the messenger user accounts, and no agent's reading substitutes for it.

## Measured, not quoted

Messages per month, by originating application, read from the production ledger 08.09:

| App | Jun | Jul | Aug | 01–08.09 |
|---|---|---|---|---|
| `sp_app` (parking) — total | 314 | 276 | 265 | 183 |
| `sp_app` → МегаФон | 55 | 94 | 46 | 77 |
| `gmp_app` — total | 29 | 178 | **297** | 71 |
| `gmp_app` → МегаФон | 6 | 36 | **63** | 18 |

Half the МегаФон traffic is not the parking app: in August МегаФон received 111 messages,
46 from `sp_app` and 63 from `gmp_app`, and the latter is growing (6 → 36 → 63).

**Three classes of message, not two** (448 `sp_app` and 368 `gmp_app` messages since
01.08):

| Class | What it is | Who sends it | Volume |
|---|---|---|---|
| four-digit code | one template, `SokolParking: ####` | `sp_app` | 446 of 448 |
| longer code | five digits or more | `gmp_app` | 237 |
| free text | wording and links, up to 472 characters | `gmp_app` | 19 carry links |

A messenger route carries all three. A flash call carries only the first, which is why
the classes are named here: a later paid route will not serve the other two, and the
configured order is per class for that reason.

## External contracts — reference or captured sample, never a guess

- **Telegram**, user account: `Telethon` 1.45.0 (MTProto). A phone number becomes an
  addressable entity through contact import. ⚠️ **Unproven here:** unlike the MAX side,
  this mechanism is cited to no file and no captured sample, and nothing captured shows
  what an import returns for a hidden or a non-existent number — which is exactly the
  fact the "no account exists on that number" scenario is written on. Tasks 3.1 and 4.1
  capture both before the classifier is written.
- **MAX**, user account: `MaxApiTeam/PyMax` (MIT). Method names read from its source, not
  from its description: `src/pymax/infra/user.py:55 search_by_phone(phone) -> User`,
  `:75 add_contact`, `src/pymax/infra/message.py:19 send_message`,
  `src/pymax/api/users/payloads.py:26 ImportContactsPayload  # phone -> contact`.
  Login is phone + SMS code, the session persists in SQLite, transport is TCP or
  WebSocket — an outbound connection, so CGNAT does not block it.
- ⚠️ **PyMax talks to an unofficial internal API** and says so: "may change without
  notice", and the responsibility for account blocks is ours. It proves the mechanism
  exists; it does not prove we are permitted. The vendor's own surface for clients is the
  Open Client API programme (`go.max.ru/openclient`), whose technical terms are invisible
  until admission. This is why the library is required to live behind the route interface.
- ⚠️ **The permission asymmetry is ours, not the vendors'.** The paragraph above says of
  MAX that the library proves the mechanism and not the permission. No equivalent
  statement is made for Telegram, and none is available: no cited term permits an
  automated user account to carry transactional traffic. Treat both routes as
  mechanism-proven and permission-unproven until a lawyer says otherwise.
- ⚠️ **"The limit lands on the account, not the SIM" is our inference** from a FAQ that
  speaks about accounts. Its load-bearing corollary — that a lost account can be replaced
  on the same number — is supported by nothing we have read.
- 🔴 **Not to be repeated: "MAX cannot address a phone number".** True of the Bot API,
  where only `user_id`/`chat_id` exist and `chat_id` arrives solely from a `bot_started`
  event. False of a client. The claim was made in this line of work on 12.09 from bot
  documentation and withdrawn the same day.
- **The risk that comes with the route:** `telegram.org/faq_spam` — an account is limited
  when a recipient presses "Report spam"; "if you have been sending unwanted messages to
  random strangers… you lose the ability to do so", a few days first, "forever" on
  repetition, and **links are named among the reasons**. The class of traffic that makes
  this route valuable is also the one that carries the risk. The limit lands on the
  account, not on the SIM: SMS is unaffected.
- **Both messengers let a person hide from lookup by phone** (Telegram's privacy setting;
  MAX's `search_by_phone` privacy access). Such a recipient is a route miss that cannot
  be predicted, only observed — which is what the ladder is for.
