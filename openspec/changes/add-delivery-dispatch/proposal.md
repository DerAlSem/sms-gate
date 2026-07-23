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
- Whenever a message changes status (`sent`, `delivered`, `failed`, `expired`), the
  gateway POSTs `{"id", "status", "error"}` to the route of the app that owns the
  message, with `Authorization: Bearer <bearer>`.
- Failures reuse the existing `dispatch_error` operator alert and the
  `inbound_dispatch_retries` / `inbound_dispatch_timeout` retry ladder.
- `GET /sms/{id}` is unchanged and remains the source of truth. The webhook is an
  accelerator, not a replacement — polling stays a valid integration.

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
- No schema migration: routing keys off the existing `messages.app_id`.
- No change to `POST /sms/send` or `GET /sms/{id}`.

## Open questions (need GM+ to confirm before implementation)

1. **`pending`** — the gateway never pushes it: `POST /sms/send` already returns
   `{"id", "status": "pending"}` synchronously, so a webhook would be redundant. GM+'s
   stated enum includes it. Confirm that "no pending webhook" is fine.
2. **`occurred_at`** — the gateway makes no ordering guarantee (see design D6). GM+ says
   it handles out-of-order (`delivered` before `sent`). If they would rather tie-break
   explicitly, an ISO-8601 `occurred_at` can be added to the body; it is left out for now
   to match the agreed contract exactly.
