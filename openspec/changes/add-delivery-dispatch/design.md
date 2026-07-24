## Context

`inbound_dispatch` routes an incoming SMS to an application by the **first word of the
text**, because an inbound SMS carries no application identity — only a phone number and
a body. Outbound messages are different: `messages.app_id` already records exactly which
application sent each one (`POST /sms/send` authenticates with a per-app token, and
`create_message(app_id, …)` stores it). So the routing problem is already solved in the
data model; only the transport is missing.

Message statuses in the gateway are `pending → sent → delivered | failed | expired`,
which is already the enum GM+ asked for — no translation layer is needed.

Multipart messages are assembled below this layer: `message_parts` tracks per-part
delivery and `messages` only turns `delivered` when *every* part is
(`message_parts_all_delivered`). A delivery webhook therefore fires per **message**, not
per part.

## Goals / Non-Goals

**Goals:**
- Push every post-creation status change of an outbound message to the owning app.
- Reuse `inbound_dispatch`'s route shape, validation, retry ladder and failure alert, so
  operators configure one kind of thing in two places rather than two kinds of thing.
- Keep the existing HTTP API untouched.

**Non-Goals:**
- Guaranteed delivery of the webhook itself. `GET /sms/{id}` remains authoritative.
- A durable outbox / persistent retry queue (D4).
- Ordering guarantees on the wire (D6).
- Pushing `pending` (D2).

## Decisions

**D1 — Routes keyed by `app_id`, stored in a `delivery_dispatch` setting.**
A JSON list of `{"app_id", "webhook_url", "bearer"}`, mirroring `inbound_dispatch`'s
`{"prefix", "webhook_url", "bearer"}`.
*Alternative considered:* `delivery_webhook_url` / `delivery_bearer` columns on the
`apps` table. That models ownership more honestly (the webhook belongs to the app), puts
it on `/admin/apps` beside the token, and makes an unconfigured app impossible to
overlook. Rejected because it needs a migration plus an admin-UI form, while the
settings route reuses the validation, stripping and JSON editor already written for
`inbound_dispatch`. Revisit if per-app webhook config grows beyond two fields.
*Consequence accepted:* an app with no route is silent by design, and nothing surfaces
that. Task 2.5 covers it with a test, not with UI.

**D2 — Fires on `sent`, `delivered`, `failed`, `expired`; never on `pending`.**
`POST /sms/send` returns `pending` synchronously, so the app already has it; a webhook
would duplicate it and could even arrive before the HTTP response the app is still
reading. The one case where this leaves a gap — a message the app did not create — is
handled by D8 instead.

**D3 — One notification per message, not per part.** Multipart assembly happens below
this layer; the hook sits on `messages.status`, not `message_parts.status`.

**D4 — Best-effort delivery, no durable outbox.**
Same in-process retry ladder as inbound (1 + 4 + 16 s, `inbound_dispatch_retries` /
`inbound_dispatch_timeout`), fire-and-forget task with a strong reference (the same GC
hazard `_spawn_dispatch` documents). A gateway restart mid-ladder loses the
notification.
*Rationale:* unlike the inbound bug this change grew out of, a dropped notification here
is **not** a silent dead end — the receiver polls `GET /sms/{id}` as a floor, so the
true status arrives within one poll interval and the system self-heals. A persistent
outbox (new table, drain loop, its own retry bookkeeping) roughly doubles the size of
the feature to close a hole polling already closes. If a consumer ever drops polling and
needs at-least-once, that is a separate change.
*Alternatives considered:* a `messages.delivery_notified_at` column plus a periodic
sweep — cheaper than a real outbox and survives restart, but only ever carries the
*latest* status, so an intermediate `sent` can still be lost; and a full `delivery_queue`
table with at-least-once semantics.

**D5 — Failures reuse the `dispatch_error` alert.** Same event type as inbound, deduped
on the webhook url, so a dead endpoint alerts once per window instead of once per
message.

**D6 — No ordering guarantee on the wire; `occurred_at` makes it recoverable.**
Notifications are independent fire-and-forget tasks, so `delivered` can reach the
receiver before `sent` — and this is likely, not theoretical: the retry ladder can hold
`sent` for 21 s while a delivery report that lands a second later goes out immediately.
Every body therefore carries `occurred_at` (ISO-8601 UTC, from the status change), and a
receiver can discard an update older than the one it already applied.
*Alternative considered:* serialize per message with a queue, guaranteeing order on the
wire. Rejected: it makes `delivered` wait out the failing `sent`'s full retry ladder,
which defeats the point of a webhook that exists to be faster than polling.
*Note:* GM+ says its receiver is order-insensitive today. "Order-insensitive" is usually
implemented as "last update wins", which is exactly the case where `sent` overwrites
`delivered` — hence the field rather than trust.

**D7 — A conformance test enumerates the status writers.**
The real risk in this design is a *missed* hook: someone adds a new place that writes
`messages.status` and delivery notifications silently stop covering it. A test greps the
codebase for `UPDATE messages SET status` (and the `queries.py` helpers that own them)
and asserts each is covered by a dispatch call, so the omission fails CI rather than
going quiet in production — which is exactly how the inbound `webhook_url` bug survived.

**D8 — `resent_from` links an admin re-send to its original.**
The admin Resend button copies `app_id` but creates a **new** message id
(`admin/router.py`, by design: the failed attempt keeps its error as history, and
delivery reports key off `modem_ref`). Without a link the app receives `sent` for an id
it never created, must ignore it, and leaves the original showing `failed` forever —
even though the person did receive the SMS. A nullable `messages.resent_from` column
carries the source id, and it is included in the body only when set.
*Why a column and not a handler-local value:* the `sent` and `delivered` notifications
fire later, from the modem loops, where the resend handler's context is long gone. The
link has to be persisted to survive to the moment it is needed.

## Risks / Trade-offs

- **Restart loses in-flight notifications (D4).** Mitigated by receiver polling.
  Accepted deliberately; revisit if a consumer drops polling.
- **An app with no configured route is silently untracked (D1).** No UI surfaces it;
  only a test does. The apps-table alternative would have made it visible.
- **A slow or hanging receiver ties up a task per message** for up to
  `timeout × retries` (30 s at defaults). Bounded and non-blocking (the modem loops are
  untouched), but a mass-send to an app with a dead webhook creates a burst of pending
  tasks. Accepted at current volumes; a semaphore is the fix if it ever bites.
- **Bearer tokens live in a settings JSON blob**, like `inbound_dispatch`'s, and are not
  masked in the admin UI (the field is not `is_secret`). Pre-existing trade-off,
  inherited knowingly rather than introduced here.
