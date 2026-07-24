## 1. Failure classification

- [x] 1.1 `app/modem/errors.py` — `is_permanent_failure(error)` with the `+CMS`/`+CME`
      tables from D4, defaulting an unrecognised failure to transient.
- [x] 1.2 `ATCommandError.pdu_submitted`, set by `send_sms_pdu` at the moment message
      bytes are written, and `is_retryable(error, pdu_submitted, already_sent)` as the
      single veto point.
- [x] 1.3 Tests: every permanent code; timeout / prompt-timeout / bare `ERROR` / an
      unlisted code / an unparseable reply classify transient; too-long is permanent.

## 2. Schema and queries

- [x] 2.1 Migration: `messages.attempts`, `messages.next_attempt_at`,
      `messages.last_attempt_error`, all via `_add_column_if_missing`.
- [x] 2.2 `begin_message_attempt` — count the attempt and clear the schedule, before any
      byte goes out; returns the attempt number so no caller can miscount.
- [x] 2.3 `schedule_message_retry` — set `last_attempt_error` and the next time, leaving
      `status` and `error` alone.
- [x] 2.4 `due_pending_messages(max_age, limit)` and `stale_pending_messages(max_age)`.
- [x] 2.5 `create_message` stamps a recovery time so a restart cannot strand a message.
- [x] 2.6 `GET /sms/{id}` gains an additive `attempts`.
- [x] 2.7 Tests: migration idempotent; a claimed message is never due however old; the
      deadline and the batch cap both hold; finished messages are never claimed.

## 3. Settings

- [x] 3.1 `send_retry_backoff` (default `30,120,300`, section "Sending") with a `delays`
      value type and a parsed accessor.
- [x] 3.2 Reject anything that is not a comma-separated list of positive integers.
- [x] 3.3 Tests: parse, reject, empty-disables, hot re-read.
- [x] 3.4 ~~Russian translation for the setting description~~ — setting descriptions are
      not translated (babel extracts templates only).

## 4. Retry in the sender loop

- [x] 4.1 Track held ids on `ModemManager`, added before the queue put and released in
      `finally` down every path.
- [x] 4.2 Failure branch: veto on `pdu_submitted`, on a part already accepted, on a
      permanent failure, or on an exhausted budget; otherwise schedule and log.
- [x] 4.3 The final alert names the attempt count; deferrals raise one alert per window.
- [x] 4.4 Wrap the loop body so a non-AT error fails the message and the loop survives.
- [x] 4.5 Tests: defer-with-budget emits no `failed` webhook; exhausted budget fails once;
      permanent fails on the first attempt; `pdu_submitted` is never retried; a partly
      transmitted multipart is never retried; a non-AT error fails the message, keeps the
      loop alive and releases the held id.

## 5. Scheduler loop

- [x] 5.1 `ModemManager.retry_loop()` — every 15 seconds sweep overlong `pending`, then
      re-queue due messages that are neither held nor blacklisted. Started in `app/main.py`.
- [x] 5.2 Tests: a due message is re-queued; a held one is skipped; a blacklisted one is
      failed; an overlong one is failed; a failing pass does not stop the loop.

## 6. Operator visibility

- [x] 6.1 Retry state on the admin message list: attempt count and last error on a
      `pending` row, translated.
- [ ] 6.2 Consider a `pending, attempts > 0` figure on the stats page so the effect of
      retries can be measured. Deferred — not needed to ship.

## 7. Verify and ship

- [x] 7.1 Full suite green.
- [ ] 7.2 Mini conformance sweep of the `outbound-send` normative SHALLs touched here,
      plus the `delivery-dispatch` SHALLs about which statuses are pushed.
- [ ] 7.3 Docs: README behaviour note, `CHANGELOG.md` entry, settings table.
- [ ] 7.4 Deploy with the owner's confirmation (a restart drops active sends), then a
      prod smoke. Rollback is `send_retry_backoff` = empty.
- [ ] 7.5 Tell GM+ that `failed` now means "the gateway stopped trying", so its
      operator-notification path fires less often — and let them re-decide whether it
      should fire at all.

## 8. Carved out — not in this change

- Feeding send failures to the modem watchdog (D7). Needs sending quiesced across
  recovery and a counter over distinct messages; own change.
- Linking permanent send failures to the blacklist, as delivery reports already do.
- Operator control over a message mid-ladder (cancel / try now).
