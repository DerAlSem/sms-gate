## Why

An application that sends an SMS through the gateway currently learns its fate only by
polling `GET /sms/{id}`. GM+ (gmb_v2) has shipped outbound delivery tracking and polls
today; every other consumer must do the same. Polling is correct but slow and wasteful:
a delivery report arrives at the modem within seconds, and the application finds out on
its next poll tick.

The gateway already pushes *inbound* SMS to applications (`inbound_dispatch`). Outbound
status is the missing symmetric half.

## What Changes

- A new `delivery_dispatch` setting: routes keyed by `app_id`, each with a
  `webhook_url` and a `bearer`. Same shape, validation and normalization as
  `inbound_dispatch`.
- Whenever a message changes status to `sent`, `delivered`, `failed` or `expired`, the
  gateway POSTs to the route of the app that owns the message, with
  `Authorization: Bearer <bearer>` and body:

  ```json
  {"id": 57, "status": "delivered", "error": null,
   "occurred_at": "2026-07-24T09:14:05Z", "resent_from": 42}
  ```

  `occurred_at` is always present; `resent_from` only when the message was created by
  the admin Resend button. Both are additive to the contract GM+ specified — a receiver
  that ignores unknown fields keeps working unchanged.
- `pending` is never pushed: `POST /sms/send` already returns it synchronously.
- Failures reuse the existing `dispatch_error` operator alert and the
  `inbound_dispatch_retries` / `inbound_dispatch_timeout` retry ladder.
- `GET /sms/{id}` is unchanged and remains the source of truth. The webhook is an
  accelerator, not a replacement — polling stays a valid integration and is the
  recovery path for a notification the gateway drops.

## Capabilities

### New Capabilities
- `delivery-dispatch`: push outbound message status changes to the owning application's
  webhook.

### Modified Capabilities
<!-- none: inbound-dispatch is untouched; this change adds a parallel capability -->

## Impact

- `app/settings_store.py` — new `delivery_dispatch` spec key; the route validation and
  stripping added for `inbound_dispatch` becomes shared.
- `app/modem/delivery_dispatch.py` — new module (mirrors `app/modem/dispatch.py`).
- Every site that writes `messages.status` — `app/db/queries.py` writers and their
  callers in `app/modem/manager.py` (send loop, `_handle_cds`, expire loop).
- `app/admin/templates/settings.html` — the settings row needs the same JSON editor
  branch `inbound_dispatch` already has.
- **One migration:** a nullable `messages.resent_from` column. Routing itself needs no
  schema change — it keys off the existing `messages.app_id`.
- No change to `POST /sms/send` or `GET /sms/{id}`.

## Resolved decisions

Settled with the owner before implementation; rationale in `design.md`.

1. **Routes live in the `delivery_dispatch` setting, keyed by `app_id`** — not as
   columns on `apps` (D1).
2. **`pending` is never pushed** (D2).
3. **`resent_from` links an admin re-send to the original message** (D8) — without it
   the app sees `sent` for an id it never created, and the original stays `failed`
   forever on its screen although the person did get the SMS.
4. **`occurred_at` makes ordering recoverable** (D6) — the gateway still gives no
   ordering guarantee, but a receiver can drop an update older than what it holds.
5. **Best-effort delivery, no durable outbox** (D4) — polling is the floor, so a lost
   notification self-heals within one poll interval.

GM+ does not need to change anything to accept this, but should be told the two extra
fields exist (task 1.1) so they can start using them.
