## 1. Failure classification

- [ ] 1.1 Add `app/modem/errors.py` with `is_permanent_failure(error: str) -> bool`,
      carrying the `+CMS`/`+CME` code tables from D4 and defaulting an unrecognised
      failure to transient.
- [ ] 1.2 Tests: each permanent code classifies permanent; timeout / prompt-timeout /
      bare `ERROR` / an unlisted code classify transient; the message-too-long error
      classifies permanent.

## 2. Schema and queries

- [ ] 2.1 Migration in `app/db/migrate.py`: `messages.attempts INTEGER NOT NULL DEFAULT 0`
      and `messages.next_attempt_at TIMESTAMP`, both via `_add_column_if_missing` so a
      re-run and a rollback are both safe.
- [ ] 2.2 `queries.schedule_message_retry(message_id, delay_seconds, error)` — increment
      `attempts`, set `next_attempt_at`, record the last error, leave status `pending`.
- [ ] 2.3 `queries.due_pending_messages()` — `pending` rows that are due: either
      `next_attempt_at <= now`, or never attempted and older than 60 seconds (D6).
      Returns what `enqueue` needs (id, phone, text, app_id).
- [ ] 2.4 `queries.get_message` and the `GET /sms/{id}` schema gain `attempts` (additive).
- [ ] 2.5 Tests: the migration is idempotent; scheduling advances attempts and time;
      the due query excludes a fresh unattempted message and includes a stranded one.

## 3. Settings

- [ ] 3.1 Add the `send_retry_backoff` spec key (default `30,120,300`, section "Modem"),
      with a parsed accessor returning a list of ints and tolerating blanks.
- [ ] 3.2 Reject a value that is not a comma-separated list of positive integers, at save
      time, naming the offending entry.
- [ ] 3.3 Russian translation for the setting description.
- [ ] 3.4 Tests: parse, reject, empty-disables, hot re-read.

## 4. Retry in the sender loop

- [ ] 4.1 Track the ids currently queued or in flight on `ModemManager` (added on
      `enqueue`, removed when the attempt finishes either way).
- [ ] 4.2 In the failure branch: classify; if permanent, or the message already reached
      `sent`, or attempts are exhausted → today's path (`set_message_failed`,
      delivery webhook, operator alert). Otherwise schedule a retry and log it, emitting
      neither webhook nor alert.
- [ ] 4.3 The final-failure alert names the attempt count so the operator can tell a
      one-shot from an exhausted budget.
- [ ] 4.4 Tests: transient-with-budget defers and stays `pending` with no webhook and no
      alert; exhausted budget fails once with a webhook and one alert; permanent fails on
      the first attempt; a message already `sent` fails without a retry.

## 5. Scheduler loop

- [ ] 5.1 `ModemManager.retry_loop()` — every 15 seconds, enqueue due messages that are
      not already held, and start it alongside the other loops in `app/main.py`.
- [ ] 5.2 Tests: a due message is enqueued; a message already in flight is not enqueued
      twice; a `pending` message left by a restart is picked up.

## 6. Watchdog coupling

- [ ] 6.1 Count consecutive transient send failures on `ModemManager`; at 3, set a flag
      the next `_watchdog_step` reads as a registration failure. Any successful send
      clears the counter and the flag.
- [ ] 6.2 Tests: three transient failures make the next step take the failure branch even
      when registration is fine; a success in between resets; the hard-reset cooldown and
      escalation order are untouched.

## 7. Verify and ship

- [ ] 7.1 Full suite green.
- [ ] 7.2 Mini conformance sweep of the `outbound-send` normative SHALLs touched here,
      plus the `delivery-dispatch` SHALLs about which statuses are pushed.
- [ ] 7.3 Docs: README behaviour note, `CHANGELOG.md` entry, and the settings table.
- [ ] 7.4 Deploy with the owner's confirmation (a restart drops active sends), then a
      prod smoke: send a real SMS, and confirm in `journalctl` that a forced transient
      failure defers rather than failing. Rollback is `send_retry_backoff` = empty.
- [ ] 7.5 Tell GM+ that `failed` now means "the gateway stopped trying", so its
      operator-notification path fires far less often — and let them re-decide whether it
      should fire at all.
