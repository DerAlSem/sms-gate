## Why

A message gets one transmission attempt. If the modem is briefly unreachable before the
message reaches it, the message is `failed` forever and a human has to notice and press
Resend — which has already become routine (prod 975←969, 976←970, 978←976).

**What the numbers actually say.** Of 61 failures over three months:

| | |
|---|---|
| Already partly transmitted (`sent_at` set) | 31 — of which 29 are delivery-report failures, out of scope |
| Never reached the modem | 30 |

Inside those 30, the genuinely recoverable slice is about **12**: 5 prompt timeouts, 4
`+CMS ERROR 350`, 2 `timeout waiting for '> ', got: 'OK'`, and a handful of ambiguous
ones. The rest are `message too long`, `+CMS 305` from the Cyrillic bug fixed in 0.2.0,
and — importantly — 6 timeouts that must **not** be retried (below).

So this is worth roughly a dozen messages a quarter, not the "5% of traffic" an earlier
draft of this proposal claimed by conflating `expired` and delivery-report failures with
this slice. They are payment links and login codes, so a dozen is worth having; the
honest scale just is not dramatic.

**The incident that prompted this would not have been fixed by retries.** On 2026-07-24
the modem lost registration for about three minutes. Message 976 has `sent_at` set: part
1 of a two-part SMS *was* accepted, and part 2 timed out — so under this proposal's own
rules it is not eligible for an automatic retry, because resending would deliver part 1
twice. What retries do address is 977, the follow-up notification, which failed on the
prompt and never reached the modem at all. The cascade that made 977 fail is already
fixed in `1c95cad`.

## What Changes

- **Failures are classified by phase, not just by text.** `no response from modem
  (timeout)` means two different things depending on where it happened. Before the `> `
  prompt, nothing was transmitted and a retry is safe. After the PDU and its Ctrl-Z, the
  SMSC may hold the message even though the confirmation never came — and the wire
  cannot tell us which. Those are never retried. Six historical prod failures have
  exactly this shape.
- **Transient failures are retried.** A retryable failure schedules another attempt
  instead of failing the message; the message stays `pending` and keeps its id.
- **`failed` means "we stopped trying".** The status — and therefore the
  `delivery-dispatch` webhook and the operator alert — is written only once the budget is
  exhausted or the failure is not retryable. Consumers see no new statuses.
- **A bounded, configurable budget.** `send_retry_backoff` (default `30,120,300`) holds
  the delays; the count of delays fixes the count of retries. Empty disables retrying and
  is the rollback switch.
- **Retries are scheduled, not blocking.** A deferred message leaves the queue.
- **An attempt is counted before any byte goes out.** `next_attempt_at` doubles as the
  claim marker and is cleared at that moment, so a message whose attempt was cut short by
  a crash, a hard reset or a `SIGKILL` has no schedule and is never resent.
- **A partly-transmitted multipart message is never auto-retried**, independently of the
  above: if any part reached the modem, resending would duplicate it and reuse its
  concatenation reference.
- **`pending` is swept.** Nothing looked at it before; a message past its deadline now
  becomes `failed` and its app is told, instead of sitting there forever.
- **The sender survives an unexpected error.** It caught only `ATCommandError`, so an
  encoder or SQLite error killed the loop silently — which with a scheduler running would
  fill the queue forever.
- **Queued messages survive a restart**, via the same scheduler.

## Not in this change

- **Feeding send failures to the modem watchdog.** Reviewed and carved out: as designed
  it either never escalated, or produced a loop where recovery switches the radio off,
  the sends it interrupts feed the counter, and the service exits every 30 minutes. It
  needs sending to be quiesced across recovery and the counter to track distinct
  messages, which is its own seam.
- **Retrying delivery-report failures and `expired`.** Those messages reached the SMSC;
  re-sending risks a duplicate rather than recovering a loss.
- **Linking permanent send failures to the blacklist.** The symmetric layer does it for
  delivery reports; doing it here needs its own threshold analysis.

## Capabilities

### Modified Capabilities
- `outbound-send`: retry policy, phase-aware failure classification, `pending` sweeping,
  sender robustness, and restart recovery. Supersedes the `descriptive` single-attempt
  requirement recorded at adoption.

### Unchanged
- `delivery-dispatch`: same statuses, same body, same routes. Only the moment `failed` is
  emitted changes, which its spec does not constrain.

## Impact

- `app/db/migrate.py` — three additive columns on `messages`: `attempts`,
  `next_attempt_at`, `last_attempt_error`.
- `app/db/queries.py` — claim, schedule, due and stale queries; `create_message` stamps a
  recovery time.
- `app/modem/errors.py` — new: failure classification.
- `app/modem/at_commands.py` — `ATCommandError.pdu_submitted`.
- `app/modem/manager.py` — sender loop rework, `retry_loop`, held-id tracking.
- `app/settings_store.py`, `app/admin/templates/settings.html` — the `send_retry_backoff`
  setting and a `delays` value type.
- `app/admin/templates/messages.html` — retry state visible on a `pending` row.
- `GET /sms/{id}` gains an additive `attempts`; `POST /sms/send` is unchanged.

## Resolved decisions

1. **`failed` is pushed only after the budget is exhausted** (D1) — the calling application reacts to
   `failed` by SMS-ing an operator, so a transient failure must not reach it.
2. **A retry keeps the message id** (D2).
3. **Four attempts across roughly eight minutes** (D3).
4. **Classification is phase-aware; unrecognised *pre-transmission* failures count as
   retryable** (D4).
5. **Anything transmitted is never retried** (D5) — the duplicate-SMS veto.
6. **`next_attempt_at` is the claim marker** (D6).
7. **Delivery-report failures and `expired` are out of scope** (D8).
