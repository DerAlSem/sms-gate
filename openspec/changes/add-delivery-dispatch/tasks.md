## 1. Confirm the contract

- [ ] 1.1 Get GM+ to confirm the two open questions in `proposal.md` (`pending` is never
      pushed; `occurred_at` is left out) before writing the sender.
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
- [ ] 2.5 Tests: save/normalize/reject routes; unknown `app_id` yields no route.

## 3. The sender

- [ ] 3.1 `app/modem/delivery_dispatch.py`: `find_route(app_id)`, `deliver(route, payload)`
      returning `(ok, reason)`, and `dispatch_delivery(message_id, app_id, status, error)`.
      Factor the retry ladder out of `app/modem/dispatch.py` rather than copying it.
- [ ] 3.2 Fire the `dispatch_error` alert on total failure, deduped on the url, with the
      app id, message id and status in the text.
- [ ] 3.3 Spawn detached with a strong task reference (reuse the `_spawn_dispatch`
      pattern and its GC note).
- [ ] 3.4 Tests: success is silent; non-2xx and transport errors alert once; an app with
      no route neither posts nor alerts; the bearer header is sent.

## 4. Hook the status transitions

- [ ] 4.1 Enumerate every writer of `messages.status`: `mark_sent`, `mark_failed`,
      `set_message_delivered`, `set_message_failed`, the expire sweep, and the resend
      path (which creates a new message rather than reviving the old one).
- [ ] 4.2 Call `dispatch_delivery` from each, reading `app_id` from the message row.
- [ ] 4.3 Conformance test (design D7): enumerate `UPDATE messages SET status` sites and
      the `queries.py` helpers owning them, and fail when one is not covered.
- [ ] 4.4 Test the multipart case end to end: a two-part message notifies `delivered`
      once, after the second part's report — not twice, not on the first.

## 5. Ship

- [ ] 5.1 Full suite green; `README` gains a `delivery_dispatch` section next to
      `inbound_dispatch`.
- [ ] 5.2 Configure the GM+ route in prod admin settings, send one real SMS to a test
      number, and confirm GM+ receives `sent` then `delivered`.
- [ ] 5.3 CHANGELOG entry, minor version bump, tag, `git ship`.
- [ ] 5.4 Archive this change (`openspec archive add-delivery-dispatch`) so
      `openspec/specs/delivery-dispatch/` becomes the living spec.
