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
delivery and `messages` only turns `delivered` once *every* part is
(`message_parts_all_delivered`). A delivery webhook therefore fires per **message**, not
per part.

## Goals / Non-Goals

**Goals:**
- Push every post-creation status change of an outbound message to the owning app.
- Reuse `inbound_dispatch`'s route shape, validation, retry ladder and failure alert, so
  operators configure one kind of thing in two places rather than two kinds of thing.
- Zero change to the existing HTTP API and zero schema migration.

**Non-Goals:**
- Guaranteed delivery of the webhook itself. `GET /sms/{id}` remains authoritative.
- A durable outbox / persistent retry queue (see D4).
- Ordering guarantees between concurrent notifications (see D6).
- Pushing `pending` (see proposal, open question 1).

## Decisions

**D1 — Routes keyed by `app_id`, stored in a `delivery_dispatch` setting.**
A JSON list of `{"app_id", "webhook_url", "bearer"}`, mirroring `inbound_dispatch`'s
`{"prefix", "webhook_url", "bearer"}`.
*Alternative considered:* add `delivery_webhook_url` / `delivery_bearer` columns to the
`apps` table. That models ownership more honestly (the webhook belongs to the app) and
would make an unconfigured app impossible to miss. Rejected for now because it needs a
migration and an admin-UI change on the apps page, while the settings route gives the
operator one familiar editor and reuses the validation written for `inbound_dispatch`.
Revisit if per-app webhook config grows beyond two fields.

**D2 — Fires on `sent`, `delivered`, `failed`, `expired`; never on `pending`.**
`POST /sms/send` returns `pending` synchronously, so the app already has it.

**D3 — One notification per message, not per part.** Multipart assembly happens below
this layer; the hook sits on `messages.status`, not `message_parts.status`.

**D4 — Best-effort delivery, no durable outbox.**
Same in-process retry ladder as inbound (1 + 4 + 16 s, `inbound_dispatch_retries` /
`inbound_dispatch_timeout`), fire-and-forget task with a strong reference (the same GC
hazard `_spawn_dispatch` documents). A gateway restart mid-ladder loses the
notification.
*Rationale:* the receiving app is expected to keep polling as a floor — GM+ already
does, and the spec says so. A persistent outbox is a much larger change (new table,
drain loop, its own retry/backoff bookkeeping) bought for a failure mode that polling
already covers. If a consumer ever needs at-least-once, that is a separate change.

**D5 — Failures reuse the `dispatch_error` alert.** Same event type, deduped on the
webhook url, so a dead endpoint alerts once per window instead of once per message.

**D6 — No ordering guarantee.** Notifications are independent fire-and-forget tasks, so
`delivered` can reach the receiver before `sent` (a fast delivery report racing a slow
first POST, or the retry ladder holding `sent` for 21 s). GM+ has confirmed its receiver
is order-insensitive and idempotent. The gateway states this as a contract rather than
serializing per message, which would mean a per-message queue for no benefit to a
receiver that is already idempotent.

**D7 — A conformance test enumerates the status writers.**
The real risk in this design is a *missed* hook: someone adds a new place that writes
`messages.status` and delivery notifications silently stop covering it. A test greps the
codebase for `UPDATE messages SET status` (and the `queries.py` helpers that own them)
and asserts each is covered by a dispatch call, so the omission fails CI rather than
going quiet in production — which is exactly how the inbound `webhook_url` bug survived.

## Risks / Trade-offs

- **Restart loses in-flight notifications (D4).** Mitigated by the receiver polling
  `GET /sms/{id}`. Accepted deliberately; revisit if a consumer drops polling.
- **A slow or hanging receiver ties up a task per message** for up to
  `timeout × retries` (30 s at defaults). Bounded and non-blocking (the modem loops are
  untouched), but a mass-send to an app with a dead webhook creates a burst of pending
  tasks. Accepted at current volumes; a semaphore is the fix if it ever bites.
- **Bearer tokens live in a settings JSON blob**, like `inbound_dispatch`'s. Not
  masked in the admin UI (the field is not `is_secret`). Pre-existing trade-off,
  inherited knowingly rather than introduced here.
