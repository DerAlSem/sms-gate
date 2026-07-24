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

## D4 — Classifying a failure

**Decided: an explicit permanent list; everything else is transient.**

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

**Decided: auto-retry only while no part has been transmitted.**

Parts go out sequentially and the message becomes `sent` on the first `+CMGS`. If part 2
fails, part 1 is already on its way to the handset. Re-sending the whole message would
deliver part 1 twice, and the recipient would see a duplicate or a mangled
concatenation — a worse outcome than the failure.

So the eligibility rule is the message's own status: only a `pending` message is
re-attempted. One that reached `sent` and then failed keeps today's behaviour, including
the immediate `failed` webhook and operator alert. Retrying just the missing parts was
rejected: the SMSC may already have timed out the concatenation, so it trades a visible
failure for an invisible corruption.

## D6 — Scheduling without blocking the queue

**Decided: a due-message scheduler, not a sleep inside the sender loop.**

Sleeping in the sender loop would hold up every other message for the length of the
backoff — five minutes of head-of-line blocking on a shared gateway.

Instead a failed-but-retryable message is written back as `pending` with `attempts + 1`
and `next_attempt_at = now + backoff[attempts - 1]`, and leaves the queue. A loop ticking
every 15 seconds re-enqueues messages whose time has come.

This makes retry state durable, which is what lets the same loop close the restart gap:
after a restart the in-memory queue is empty, so any `pending` message is stranded. The
loop picks those up too.

**Avoiding a double-enqueue.** A message accepted by `POST /sms/send` is `pending` and in
the in-memory queue at once, so the scheduler must not also claim it. Two guards, because
one alone leaves a window:

1. The manager tracks the ids it currently holds in the queue or in flight, and the
   scheduler skips them.
2. A never-attempted message is only considered stranded once it is older than 60
   seconds, which covers the microseconds between the `INSERT` and the enqueue.

Both are needed: the id set is empty after a restart (so the age rule does the work), and
the age rule alone would race with a slow first attempt (so the id set does).

## D7 — Feeding the watchdog

**Decided: consecutive transient send failures make the next watchdog step take its
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
