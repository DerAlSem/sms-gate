# Design — add-send-retries

## D1 — When may `failed` reach the app?

**Decided: only once the gateway has stopped trying.**

`delivery-dispatch` pushes `failed` to the owning app, and GM+ turns that into an SMS to
an operator (prod id 977). If every intermediate attempt were pushed, a three-minute
network blip would produce operator SMS for a message that goes out fine a minute later —
strictly worse than today.

Rejected: a new `retrying` status. It buys observability the operator already gets from
logs and alerts, at the cost of widening the `delivery-dispatch` contract and requiring
every consumer to learn a status. If retry visibility is wanted later, the additive
`attempts` field on `GET /sms/{id}` covers it without touching the webhook vocabulary.

Consequence: a message can now sit `pending` for minutes. That is the intended meaning —
`pending` has always meant "accepted, not yet transmitted", and it stays accurate.

## D2 — Retry in place, not a new row

**Decided: the same message id spans every automatic attempt.**

The id from `POST /sms/send` is the app's handle; it polls `GET /sms/{id}` and matches
webhooks on it. Creating a new row per attempt would leave that id `failed` forever while
a different row succeeded — which, combined with D1, would contradict itself.

The admin Resend keeps creating a new row with `resent_from`, and that stays right: it is
a human decision taken after a message has finally failed, and it deserves its own
audit trail. Two mechanisms, two different intents.

## D3 — Budget and backoff

**Decided: `send_retry_backoff = "30,120,300"` — four attempts within about 7.5 minutes.**

Sized from the incident: the deregistration lasted around three minutes, and the delays
straddle it so an attempt lands both during and well after. The upper bound is set by
what the message is *for* — a booking payment link that arrives half an hour late has
lost most of its value.

One setting rather than two: the number of attempts is `len(backoff) + 1`, so the delays
and the count cannot disagree. An empty value disables retries, which is also the
rollback switch if the change misbehaves in production.

Stored as a setting, re-read per use like `delivery_timeout_seconds`, so it can be tuned
without a restart.

## D4 — Classifying a failure, by phase as well as by text

**Decided: an explicit permanent list; everything else that happened *before* the PDU
was written is transient.**

The phase half was missed in the first draft and is the more important one. The text
`no response from modem (timeout)` is produced at two points in `send_sms_pdu`: waiting
for the `> ` prompt, where nothing has been transmitted, and waiting for `OK` after the
PDU and its Ctrl-Z, where the SMSC may already hold the message. The bytes on the wire
are identical; only the caller knows which. So `ATCommandError` carries `pdu_submitted`,
set at the moment of the write, and a failure carrying it is never retried.

Six of the 30 never-`sent` prod failures are `Timeout waiting for b'OK', got: b''` —
exactly this shape. A text-only classifier would have sent all six twice.

The code tables below still decide the *pre-transmission* cases.

Permanent — retrying cannot help:

- over the `max_sms_parts` budget (never reaches the modem);
- `+CMS` 1, 21, 28, 50, 69, 96 — the network refuses this message or this destination;
- `+CMS` 301–305, 321, 330 — a malformed request or misconfiguration on our side, which
  will fail identically next time;
- `+CMS`/`+CME` 310, 311, 313 — the SIM is missing, locked or broken; a retry in eight
  minutes will not fix hardware, and the watchdog is the right responder.

Everything else — no response, a prompt timeout, `+CMS` 38/41/42/331/332/350/500, a bare
`ERROR`, an unparseable reply — is transient.

The default leans toward retrying because the failure modes are asymmetric: a wasted
retry costs a few seconds inside a bounded budget, while a missed one loses the message
and pulls a human in. The classifier lives in its own module with the code tables next to
it, so an unrecognised code seen in production is a one-line change with a test.

Deliberately separate from `_is_permanent_status`, which classifies a TP-status on a
*delivery report* — a different layer answering a different question.

## D5 — Multipart is all-or-nothing

**Decided: auto-retry only while no part has been transmitted, tracked in-process.**

Parts go out sequentially and the message becomes `sent` on the first `+CMGS`. If part 2
fails, part 1 is already on its way to the handset. Re-sending the whole message would
deliver part 1 twice, and the recipient would see a duplicate or a mangled
concatenation — a worse outcome than the failure.

The first draft made the eligibility rule "the message's status is still `pending`".
That is wrong: the status is written *after* the modem acknowledges, so a message can be
`pending` with part 1 already on its way — a DB error in the part callback, or the
watchdog's `os._exit(1)` landing during the 30-second response window, both leave exactly
that. The rule is therefore a flag set by the part callback in-process, which is
authoritative and needs no DB read, backed by `pdu_submitted` from D4 for the window
before any status exists at all.

Retrying just the missing parts was rejected: the SMSC may already have timed out the
concatenation, so it trades a visible failure for an invisible corruption. The
concatenation reference is `message_id % 256`, so a resend would also reuse it.

## D6 — Scheduling without blocking the queue, and `next_attempt_at` as the claim marker

**Decided: a due-message scheduler, not a sleep inside the sender loop; and the schedule
column doubles as the record of who owns the message.**

Sleeping in the sender loop would hold up every other message for the length of the
backoff — five minutes of head-of-line blocking on a shared gateway.

Instead a failed-but-retryable message is written back as `pending` with `attempts + 1`
and `next_attempt_at = now + backoff[attempts - 1]`, and leaves the queue. A loop ticking
every 15 seconds re-enqueues messages whose time has come.

This makes retry state durable, which is what lets the same loop close the restart gap:
after a restart the in-memory queue is empty, so any `pending` message is stranded. The
loop picks those up too.

**The claim marker.** `next_attempt_at` is stamped at `INSERT` (a minute out, so a
restart can still recover the message) and **cleared the moment the sender claims it**,
before any byte reaches the modem. That single rule buys three things:

- a message being transmitted is not selectable, however long a six-part send takes;
- a message whose attempt died mid-flight has no schedule, so nothing ever resends it —
  the crash case that D5's status check could not see;
- "due" is one predicate, `next_attempt_at <= now`, instead of an inference over two
  columns.

The in-memory set of held ids remains as a second guard for the live path, and is added
to *before* the queue put so no gap exists.

**Bounds.** The due query is capped by age and by batch size. Without the age cap the
first tick after a deploy would resurrect every message ever stranded in `pending` —
ordered oldest-first, ahead of live traffic. Prod happens to have none today, which was
checked rather than assumed, but the bound is what makes that safe rather than lucky.

**Sweeping.** Nothing looked at `pending` before — `expire_stale_messages` covers only
`sent`. A message past `sum(backoff) + 120` seconds is failed and its app told, so every
failure mode above ends in a terminal status rather than an eternal `pending`.

## D7 — Feeding the watchdog — withdrawn from this change

**Decided: not here.** Review found the proposed coupling is either inert or harmful, so
it is carved out rather than shipped.

- **One-shot**: `_watchdog_step` needs three consecutive failure branches to soft-recover
  and resets its counter on any success. One forced step per burst never escalates, so
  the coupling would change the spec and do nothing.
- **Sticky**: it escalates into a loop. `soft_recover` cycles the radio off and on for
  tens of seconds; every send interrupted by that feeds the counter that triggered it,
  and the ladder ends at `os._exit(1)`. The 30-minute hard-reset gate bounds it to a
  cycle rather than a spiral, which is not much comfort.

Two structural fixes it needs, and neither belongs in a change to the send path itself:
sending must be quiesced while recovery runs, and the counter must track *distinct
messages*, not attempts of one message — otherwise a single bad destination timing out
three times triggers modem recovery.

The original reasoning is kept below, because it is still the right shape for that change.

**Original: consecutive transient send failures make the next watchdog step take its
failure branch.**

The watchdog owns escalation — three strikes, soft recovery, then a hard reset gated to
once per 30 minutes. Duplicating that ladder for send failures would produce two
independent recovery paths racing each other on one modem.

So the sender only contributes evidence: three consecutive transient failures raise a
flag, and the watchdog's next step treats the modem as unregistered regardless of what
`AT+CEREG?` says. Any successful send clears the counter and the flag. Escalation,
cooldown and the hard-reset gate keep working exactly as specified, and `AGENTS.md`'s
"don't defeat the 30-minute gate" holds.

## D8 — What is *not* retried

Delivery-report failures (`+CDS` negative) and `expired` are out of scope. Both mean the
message was accepted by the SMSC — it may have arrived without a report, or arrived late.
Re-sending risks a duplicate on the recipient's handset rather than recovering a loss,
and the right response differs per case (a permanent TP-status already feeds
blacklisting). If the `expired` count matters later, it deserves its own change with its
own duplicate analysis.
