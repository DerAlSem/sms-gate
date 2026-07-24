## Why

A message gets one transmission attempt. If the modem is briefly unreachable, the
message is `failed` forever and a human has to notice and press Resend.

That is not hypothetical. On 2026-07-24 the modem lost registration for about three
minutes (`Modem re-registered` at 17:42:03). Message 976 was attempted at 17:39:59, got
no response, and was declared `failed`. GM+ reacted to the `failed` webhook by sending an
operator an SMS about it (977) — which itself failed, because the timeout had left the
serial port desynced. An operator then pressed Resend, and the identical text went out on
its **first** attempt at 17:50 (978, `resent_from=976`). Every part of that sequence was
avoidable by trying again.

Over 30 days: 365 `delivered`, 13 `failed`, 6 `expired` — around 5% of traffic does not
arrive, and `gmp_app` carries most of it (10 `failed` + 6 `expired` of 106). The manual
Resend has already become routine (975←969, 976←970, 978←976), which is an operator
doing by hand what the gateway should do itself.

The transport-level cascade (a timeout desyncing later commands) is already fixed in
`1c95cad`. What remains is that the gateway gives up after one try, and that a modem
which answers `AT+CEREG?` while refusing to send is never recovered.

## What Changes

- **Transient failures are retried.** A send failure is classified transient or
  permanent. A transient one schedules another attempt instead of failing the message;
  the message stays `pending` and keeps its id.
- **`failed` means "we stopped trying".** The status — and therefore the
  `delivery-dispatch` webhook and the operator alert — is only written once the retry
  budget is exhausted or the failure is permanent. Consumers see no new statuses and need
  no change; they simply stop being told about failures that resolve themselves.
- **A bounded, configurable budget.** A new `send_retry_backoff` setting holds the delays
  before each retry (default `30,120,300` — four attempts inside roughly eight minutes,
  covering the observed deregistration window while a payment link is still fresh). Empty
  disables retries.
- **Retries are scheduled, not blocking.** A message waiting for its next attempt leaves
  the queue, so it never holds up other traffic.
- **A partly-transmitted multipart message is never auto-retried.** If any part reached
  the modem, retrying would re-send that part and the recipient would get it twice; the
  message fails as it does today and the operator decides.
- **Repeated send failures drive modem recovery.** Three consecutive transient failures
  make the watchdog treat the modem as unhealthy, so its existing soft→hard ladder runs
  even while registration polls succeed.
- **Queued messages survive a restart.** The scheduler also picks up messages left
  `pending` by a restart, closing the gap the adoption sweep found: today the queue is
  in-memory only, so a restart between acceptance and transmission strands a message
  forever.

## Capabilities

### Modified Capabilities
- `outbound-send`: retry policy, failure classification, restart recovery, and the link
  from send outcomes to modem recovery. Supersedes the two `descriptive` requirements
  recorded at adoption (single attempt; send outcomes not feeding recovery).

### Unchanged
- `delivery-dispatch`: same statuses, same body, same routes. Only the moment `failed` is
  emitted changes, which its spec does not constrain.

## Impact

- `app/db/migrate.py` — two nullable/defaulted columns on `messages`: `attempts` and
  `next_attempt_at`. Additive, so old rows and a rollback both stay valid.
- `app/db/queries.py` — schedule-a-retry and due/stranded-message queries.
- `app/modem/manager.py` — the sender loop's failure branch, a retry-scheduler loop, and
  the send-failure signal into the watchdog.
- `app/modem/errors.py` — new: transient/permanent classification of AT failures.
- `app/settings_store.py` + `app/admin/templates/settings.html` — the
  `send_retry_backoff` setting and its translation.
- `POST /sms/send` and `GET /sms/{id}` keep their contract; `GET /sms/{id}` gains an
  additive `attempts` field.
- No change to the admin Resend, which stays the operator's post-final-failure tool.

## Resolved decisions

Settled with the owner before implementation; rationale in `design.md`.

1. **`failed` is pushed only after the budget is exhausted** (D1) — GM+ reacts to
   `failed` by SMS-ing an operator, so a transient failure must not reach it.
2. **A retry keeps the message id** (D2) — the app already holds that id and polls it;
   attempts are an implementation detail of one delivery intent.
3. **Four attempts across roughly eight minutes** (D3).
4. **Unrecognised failures count as transient** (D4) — the budget is bounded, so a
   pointless retry is cheap while a missed one loses a message.
5. **Delivery-report failures and `expired` are out of scope** (D5) — those messages
   reached the SMSC, so re-sending risks a duplicate rather than recovering a loss. A
   separate change if wanted.
