# Changelog

All notable changes to this project are documented here.
This project adheres to [Semantic Versioning](https://semver.org/).

## [0.8.1] - 2026-07-24

### Documentation
- Delivery dispatch shipped in 0.8.0 but only `docs/api.md` and
  `docs/delivery-webhook.md` described it — the rest of the docs still read as if the
  gateway only ever *received* webhooks and never sent them. Now covered in:
  - **README** (RU+EN) — a Features entry for outbound status webhooks (what the body
    carries, that routing is by `app_id`, that `GET /sms/{id}` stays authoritative), and
    Configuration names both `inbound_dispatch` and `delivery_dispatch`.
  - **`docs/architecture.md`** — the system diagram never showed the gateway calling out
    at all; adds that arrow plus a *Webhook Dispatch* component explaining why the two
    directions route differently (an inbound SMS carries no application identity, so it
    routes by prefix; an outbound message already knows its owner, so it routes by
    `app_id`).
  - **`docs/database.md`** — `messages.resent_from` was missing from the schema.
  - **`docs/project-structure.md`** — `delivery_dispatch.py` and `webhook.py` were absent,
    and the send/report flow did not mention the status push.

## [0.8.0] - 2026-07-24

### Added
- **Delivery dispatch** — the outbound counterpart of `inbound_dispatch`. When a message
  changes status (`sent`, `delivered`, `failed`, `expired`) the gateway POSTs
  `{id, status, error, occurred_at, resent_from?}` to the owning application's webhook,
  routed by `messages.app_id`. Configure routes under `delivery_dispatch` on
  `/admin/settings`; `pending` is never pushed (the API already returns it). Best-effort
  with the same retry ladder and `dispatch_error` alert as inbound — `GET /sms/{id}`
  stays authoritative, so a dropped notification self-heals on the next poll. Full
  receiving-side contract in [`docs/delivery-webhook.md`](docs/delivery-webhook.md).
- `messages.resent_from` (nullable) links an admin re-send to the message it replaces, so
  an application can attribute the outcome of a re-sent SMS to its original id.

### Changed
- Settings of type `json` are now typed `routes` with a `route_key`, shared by
  `inbound_dispatch` (`prefix`) and `delivery_dispatch` (`app_id`); the "Inbound
  dispatch" section is now "Dispatch". The webhook retry/timeout transport moved to a
  shared `app/modem/webhook.py`.
- `expire_stale_messages` returns the ids it expired, so the bulk sweep notifies each
  affected app instead of changing status silently.

## [0.7.0] - 2026-07-23

### Added
- **Alert on a failed inbound webhook.** A dispatch that never reached the receiving
  application was visible only as WARNING lines in `journalctl` — the SMS is stored and
  the modem is fine, so nothing raised the alarm. A `dispatch_error` notification now
  carries the prefix, url, phone, text and the reason for the last failure, deduplicated
  on the url so a dead endpoint alerts once per window rather than once per message.
  Toggle `notify_dispatch_errors`, default **on**. An SMS with no matching prefix stays
  silent — that is not a gateway fault.
- First `openspec/` change in the repo: `add-delivery-dispatch` specifies the outbound
  counterpart of `inbound_dispatch` (push message status to the owning app's webhook,
  routed by `messages.app_id`). Spec only — not implemented yet.

## [0.6.0] - 2026-07-23

### Added
- **Resend** button on failed/expired rows in the outbox. It queues a *new*
  message rather than reviving the old one: the failed attempt keeps its error as
  history, and delivery reports key off `modem_ref`, which a re-send changes anyway.

### Fixed
- **Inbound dispatch silently dropped messages when `webhook_url` held stray
  whitespace.** A leading space made httpx raise `UnsupportedProtocol` before the
  request left the box — three retry warnings in the log and nothing else. Routes
  are now validated on save (each entry must be an object with a non-empty `prefix`
  and an `http://`/`https://` `webhook_url`), stripped before storing, and stripped
  again on read so rows written earlier start routing without a manual edit.
- The dialogs list rendered last activity as raw UTC while every other page shows
  Moscow time; it now goes through the same `msk` filter.

### Changed
- Dropped the 160-char cap on the dialog reply form — an artificial GSM-7
  single-part limit. The sender already splits long texts into parts (UCS2 for
  Cyrillic) and the manager rejects anything over `max_sms_parts` with a clear error.

## [0.5.0] - 2026-06-20

### Added
- **Modem diagnostics** — `/admin/modem` (page, in the nav) and `/admin/modem.json`
  show live registration, signal, operator and SMSC (`CEREG/CREG/CGREG/CSQ/COPS/CSCA`
  plus Quectel `QNWINFO/QCSQ`), collected under the existing serial lock with an `AT`
  liveness short-circuit.
- **Modem registration watchdog** — a loop checks `AT+CEREG?` every 60 s and
  auto-recovers a modem that lost the network: soft recovery (`CFUN=4→1` + `COPS=0`)
  after 3 failures, escalating to a hard reset (`CFUN=1,1`) + service restart, gated to
  at most one hard reset per 30 min. Toggle `modem_watchdog_enabled` (default on).

### Changed
- `describe_at_error` now names `+CMS ERROR 350` and gives a generic
  "network/SMSC rejection" description for other unrecognised CMS 300-511 codes.

## [0.4.0] - 2026-06-16

### Added
- Reply-to-SMS over Telegram: reply to a notification post in the channel and the
  gateway sends that text back as an SMS to the number the notification was about.
  Uses long polling (`getUpdates`, CGNAT-friendly), a `notify_refs` message_id→phone
  map, and a `telegram_replies_enabled` toggle (default off; takes effect after
  restart). Replies are accepted only from the configured `alert_chat_id`.

## [0.3.2] - 2026-06-15

### Changed
- Delivery-failure status is now human-readable everywhere it surfaces
  (Telegram notification, `messages.error` / admin, blacklist `last_error`):
  e.g. `service rejected (temporary, st=99)` instead of a bare `st=99`.
  Decoded via the new `describe_tp_status` (GSM 03.40 TP-Status).

## [0.3.1] - 2026-06-14

### Changed
- Telegram notifications are now HTML-formatted: a bold title line
  (`📨 Inbound` / `🔴 Send failed` / `🚫 Delivery failed`) and a clean
  `+phone: text` body, removing the previous doubled event type. Sent with
  `parse_mode=HTML`; all dynamic fields are escaped and truncated before
  wrapping so the markup is always well-formed.

### Added
- `instance_name` setting (section "Alerting", blank = server hostname) — the
  label shown in notifications, e.g. `sms.deralsem.ru`.

## [0.3.0] - 2026-06-14

### Added
- Per-type Telegram notifications, each toggled in the admin UI (section
  "Alerting"): system errors (default on), send failures, delivery
  failures / blacklist, and inbound SMS (the last three default off).
- `notify(event_type, text, dedup_extra=None)` for typed event notifications,
  sharing the Telegram delivery machinery with the log handler.

### Changed
- Refactored alerting: delivery (bounded queue + daemon worker + windowed
  dedup + truncation) extracted into a reusable `TelegramNotifier`;
  `TelegramAlertHandler` is now a thin ERROR-level adapter over it.
- Send-failure logs downgraded ERROR→WARNING so they no longer also fire the
  system-error alert (the typed `send_error` notification covers them).

## [0.2.0] - 2026-06-14

### Added
- Outbound Cyrillic and Unicode SMS via PDU-mode sending, with automatic
  GSM 7-bit / UCS2 encoding (`app/modem/pdu_encode.py`, `app/modem/gsm7.py`).
- Multipart (UDH-concatenated) outbound SMS, reassembled into one message on
  the recipient's handset.
- Per-part delivery tracking via the new `message_parts` table; a message is
  marked `delivered` only when every part's `+CDS` report arrives.
- `max_sms_parts` setting (default 6) capping multipart length.

### Changed
- Outbound send path moved from AT text mode to PDU mode (`send_sms_pdu`).
- API `text` field limit raised from 160 to 1000 characters.
- `+CMS`/`+CME` errors are now surfaced as clean, human-readable messages
  instead of raw byte dumps, and no longer block for the full send timeout.
- Admin UI gained a favicon.

## [0.1.0]

- Initial release: HTTP SMS API, delivery tracking, inbound PDU decoding with
  multipart reassembly, admin UI, operator/region lookup, auto-blacklist.
