# Changelog

All notable changes to this project are documented here.
This project adheres to [Semantic Versioning](https://semver.org/).

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
