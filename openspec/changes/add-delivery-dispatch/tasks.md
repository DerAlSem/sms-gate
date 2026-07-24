## 1. Confirm the contract

- [ ] 1.1 Tell GM+ that the body carries two fields beyond the agreed
      `{id, status, error}`: `occurred_at` (always) and `resent_from` (re-sends only).
      Both are additive — confirm their receiver ignores unknown fields, and that
      `pending` is never pushed.
- [ ] 1.2 Capture one real request/response pair against
      `https://gmplus.ru/webhooks/sms-gate/delivery` (a valid bearer, a throwaway id) so
      the body shape is verified against the live receiver, not assumed.

## 2. Configuration

- [ ] 2.1 Extract the route validation and stripping added for `inbound_dispatch` in
      `app/settings_store.py` into a shared helper parameterized by the key field
      (`prefix` vs `app_id`).
- [ ] 2.2 Add the `delivery_dispatch` spec key (type `json`, section "Inbound dispatch"
      renamed to "Dispatch", default empty) and its validation.
- [ ] 2.3 Add a `delivery_dispatch_parsed` accessor mirroring `inbound_dispatch_parsed`,
      dropping entries without an `app_id` or `webhook_url`.
- [ ] 2.4 Extend the `inbound_dispatch` JSON-editor branch in
      `app/admin/templates/settings.html` to cover `delivery_dispatch`; add the Russian
      translation for the new description.
- [ ] 2.5 Tests: save/normalize/reject routes; an app with no route neither posts nor
      alerts (the silent-by-design case from D1).

## 3. Migration

- [ ] 3.1 Add a nullable `messages.resent_from INTEGER REFERENCES messages(id)` column
      in `app/db/migrate.py`, following the existing idempotent style.
- [ ] 3.2 Set it in the admin Resend handler (`create_message` gains the source id) and
      expose it on the row read by the dispatcher.
- [ ] 3.3 Test: an API-created message has `resent_from` NULL; a re-sent one carries the
      source id; the migration is idempotent on an existing DB.

## 4. The sender

- [ ] 4.1 `app/modem/delivery_dispatch.py`: `find_route(app_id)`, `deliver(route, payload)`
      returning `(ok, reason)`, and `dispatch_delivery(message_id, app_id, status, error,
      occurred_at, resent_from)`. Factor the retry ladder out of `app/modem/dispatch.py`
      rather than copying it.
- [ ] 4.2 Build the body: always `id`, `status`, `error`, `occurred_at` (ISO-8601 UTC);
      `resent_from` only when set.
- [ ] 4.3 Fire the `dispatch_error` alert on total failure, deduped on the url, with the
      app id, message id and status in the text.
- [ ] 4.4 Spawn detached with a strong task reference (reuse the `_spawn_dispatch`
      pattern and its GC note).
- [ ] 4.5 Tests: success is silent; non-2xx and transport errors alert once; the bearer
      header is sent; `occurred_at` parses as UTC ISO-8601; `resent_from` is absent for
      API-created messages.

## 5. Hook the status transitions

- [ ] 5.1 Enumerate every writer of `messages.status`: `mark_sent`, `mark_failed`,
      `set_message_delivered`, `set_message_failed`, and the expire sweep.
- [ ] 5.2 Call `dispatch_delivery` from each, reading `app_id` and `resent_from` from the
      message row. Note `expire_stale_messages` is a bulk `UPDATE` with no `RETURNING`:
      select the affected ids before updating, so every expired message notifies.
- [ ] 5.2a `expired` is not terminal — `find_message_parts_by_ref` accepts it, so a late
      report moves `expired → delivered` and notifies twice. Test that sequence.
- [ ] 5.3 Conformance test (design D7): enumerate `UPDATE messages SET status` sites and
      the `queries.py` helpers owning them, and fail when one is not covered.
- [ ] 5.4 Test the multipart case end to end: a two-part message notifies `delivered`
      once, after the second part's report — not twice, not on the first.
- [ ] 5.5 Test that a delivery report arriving while `sent` is still retrying is not
      queued behind it (D6).

## 6. Ship

- [ ] 6.1 Full suite green; `README` gains a `delivery_dispatch` section next to
      `inbound_dispatch`, documenting the body including both extra fields.
- [ ] 6.2 Configure the GM+ route in prod admin settings, send one real SMS to a test
      number, and confirm GM+ receives `sent` then `delivered`.
- [ ] 6.3 Verify the re-send path on prod: fail a message, re-send it from the admin,
      confirm GM+ receives `resent_from` pointing at the original.
- [ ] 6.4 CHANGELOG entry, minor version bump, tag, `git ship`.
- [ ] 6.5 Archive this change (`openspec archive add-delivery-dispatch`) so
      `openspec/specs/delivery-dispatch/` becomes the living spec.
