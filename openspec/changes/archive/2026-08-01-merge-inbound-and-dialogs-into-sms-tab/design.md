## Context

The admin console is server-rendered Jinja2 over FastAPI, with no JavaScript build step and
no client framework — every page today is a form submit and a redirect. Data is SQLite
(`aiosqlite`), single writer, `PRAGMA foreign_keys=ON` (`app/db/connection.py:17`), ~1200
outbound rows on the live host today.

Three routes hold the material this change merges:

- `/admin/messages` — `list_messages` / `count_messages`, paginated 50, `ORDER BY m.id DESC`,
  left-joined to `number_operators` for the operator/region column.
- `/admin/inbound` — `list_inbound` / `count_inbound` over `inbound_messages`.
- `/admin/dialogs` and `/admin/dialogs/{phone}` — `dialog_phones` (a `UNION ALL` roll-up)
  and `dialog_for` (the timeline), plus the reply endpoint.

`/admin/stats` reads `status_counts` (all time) and `daily_counts(days=14)`.

This seam has no spec — it predates `openspec/` in this repo. Rather than reverse-engineer a
baseline for code that this change largely replaces, the new `admin-sms-console` spec
describes the merged view directly and becomes the baseline for it. The other admin tabs
stay unspecced.

Timestamps are comparable across the two tables: `messages.created_at` and
`inbound_messages.received_at` are both SQLite `CURRENT_TIMESTAMP`, i.e. UTC in
`YYYY-MM-DD HH:MM:SS`, so they sort correctly as strings. MSK (`+3 hours`) is applied only
for display and for the statistics buckets, as `daily_counts` already does.

Two neighbouring capabilities constrain this one and were read before the decisions below:
`openspec/specs/delivery-dispatch/spec.md` (late reports for `expired` messages, `resent_from`
in every notification, polling as the authoritative recovery path) and
`openspec/specs/outbound-send/spec.md` (blacklist thresholds, failing queued messages whose
destination was blacklisted after acceptance).

## Goals / Non-Goals

**Goals:**

- One table carrying both directions, with the current outbound table's look.
- Expansion in place into the conversation, with the actions attached to it.
- A period that bounds both the SMS table and the statistics view.
- No new runtime dependency, no schema change, no JavaScript build step.

**Non-Goals:**

- Reworking the remaining admin tabs (prefixes, apps, settings, modem).
- Live updating — the view still refreshes on navigation, not by push.
- Changing anything on the modem, HTTP API or webhook paths.
- Full-text search over message bodies. The phone filter stays a `LIKE` on the number.
- **Normalising historical inbound senders.** `inbound_messages.phone` holds whatever the
  network delivered, unnormalised (see D11); this change reads it, it does not rewrite it.
- **Resolving operators for inbound-only numbers** (see D12).
- **Preserving the SMSC timestamp.** Inbound ordering uses `received_at` (see D13).

## Decisions

### D1 — The merged listing is one SQL `UNION ALL`, with a deterministic order

`list_thread_page(period, phone, status, direction, limit, offset)` selects a common shape
from both tables — `direction`, `id`, `phone`, `text`, `status`, `ts`, plus the outbound-only
columns as `NULL` for inbound — `UNION ALL`s them, and orders by
`ts DESC, direction DESC, id DESC`.

The tie-break is not decoration. `CURRENT_TIMESTAMP` has one-second resolution, and multipart
bursts, reconcile sweeps and test runs all produce equal timestamps; `ORDER BY ts DESC` alone
under `LIMIT`/`OFFSET` gives SQLite licence to return a row on two pages or on neither.

`ts` is `created_at` for outbound and `received_at` for inbound, and **the same column bounds
the period** — one column per row, used for ordering, filtering and statistics membership
alike.

*Alternative rejected:* fetching from both tables and merging in Python. Correct pagination
would then need each source over-fetched to `limit + offset` rows and re-sliced, and the
total count computed separately anyway. The `UNION ALL` gets both from one statement, and
`dialog_phones` already establishes the idiom in this file.

`dialog_for` is realigned to the same column (it sorts outbound by
`COALESCE(sent_at, created_at)` today). A table and the panel directly beneath it ordering
the same two messages differently is a defect nobody would report as one.

### D2 — Expansion is server-rendered, addressed by the row key

The row links to the same page with `open=<direction>-<id>` and an anchor at the row. The
template renders the conversation into a spanning row underneath the row whose key matches.
No JavaScript.

**The key, not the number.** An earlier draft used `open=<phone>`, which is wrong twice: the
match is true for every row of that number, so a number with twenty rows in the window would
render the conversation twenty times; and a `+`-prefixed number in a query string decodes to
a leading space (see D14). The server resolves the number from the row the key names.

*Alternatives rejected:*

- **`fetch()` of an HTML fragment** — smoother, but adds a JS path to a console that has none,
  and puts the expanded state outside the URL, so every post-action redirect would have to
  reconstruct it anyway.
- **HTMX** — a new dependency for one interaction, on a host that installs from
  `requirements.txt` into a venv and serves templates directly.

The consequence worth naming: expanding costs a page load. On this console — an operator
looking at one conversation at a time, over a local network — that is a fair trade for the
whole feature being testable with the existing `TestClient` render tests, with no browser.

Because expansion lives in the URL, "return to the same conversation after an action" is not
a separate mechanism: every action endpoint redirects back with the same
`period`/`phone`/`status`/`direction`/`page`/`open` query it was given.

### D3 — Periods are rolling windows, and are labelled as rolling windows

`24h` / `7d` / `30d` / `1y` map to `datetime('now', '-1 day' | '-7 days' | '-30 days' |
'-365 days')`; `all` applies no bound. An unknown or missing value falls back to `30d`.

*Alternative rejected:* calendar anchors (today, since Monday, since the 1st, since January).
Closer to how a person speaks, but it makes the **default** view near-empty on the 1st of a
month and on Monday mornings — a default that shows nothing is a worse default.

*What that costs, and how it is paid:* a rolling 30-day window does **not** answer "how much
did we send in August". Calling it "month" would leave the operator comparing a card against
an expectation it never met and concluding the counter is broken. So the labels name the
window — "30 дней", not "месяц". If a calendar month is wanted later it is a sixth option,
not a redefinition of an existing one.

### D4 — Status and direction filters are made consistent, not merely combined

`status` is meaningless for inbound rows. Rather than let `status=delivered&direction=in`
return an unexplained empty table, the handler normalises: a status forces `direction=out`,
and choosing `direction=in` drops the status. As a side effect the `UNION` is skipped
entirely whenever a status filter is active.

### D5 — The conversation panel ignores the period, but not size

`dialog_for(phone)` stays unbounded in time — the period is a lens on the *list*, and a thread
that stops mid-sentence at the period boundary would be unreadable.

It does gain a `LIMIT`. The panel now renders inside the list page and is re-rendered after
every action, so a number on the receiving end of a daily notification would make every
redirect more expensive. Most recent 100, with the earlier ones on request.

### D6 — Statistics bucket by period, count inbound, and key off the same column as D1

One query per view, both period-bounded on `created_at` / `received_at`:

- counts: `status` → `n` over `messages`, plus a `COUNT(*)` over `inbound_messages`;
- breakdown: bucket expression chosen by period —
  `strftime('%Y-%m-%d %H:00', ts, '+3 hours')` for *24 hours*,
  `DATE(ts, '+3 hours')` for *7 days* and *30 days*,
  `strftime('%Y-%m', ts, '+3 hours')` for *a year* and *all time*.

Membership is by creation time and the card is chosen by *current* status — so a message
created before the window and delivered inside it is not counted. This is the only definition
that stays stable as statuses keep moving after the fact, and it is what makes the cards and
the table agree on which messages exist.

This replaces `daily_counts(days=14)`, whose fixed window has no meaning once the period is
chosen by the operator.

### D7 — Deletion is gated by what still depends on the message, not by status alone

Three conditions, all necessary, checked in one transaction:

1. **Status is `delivered` or `failed`.** An earlier draft also allowed `expired`, which was
   wrong: `find_message_by_part_ref` matches `WHERE p.modem_ref = ? AND m.status IN ('sent',
   'expired')` (`queries.py:255`), because `delivery-dispatch` normatively promises that a
   report arriving after expiry corrects the message to `delivered` and notifies again. An
   expired message is not finished; it is waiting.

2. **No re-sent copy still in flight.** `delivery-dispatch` requires `resent_from` in *every*
   notification for the re-sent message, and `get_message_delivery_context` reads that column
   at notification time — after any deletion. Clearing it while the copy is still `sent` would
   silently strip the field the consumer uses to attribute the outcome. So a message is
   undeletable while any message naming it in `resent_from` is not itself `delivered` or
   `failed`; once the copy is finished, no further notification will read the column and
   clearing it is safe.

3. **At least 24 hours old.** `delivery-dispatch` makes `GET /sms/{id}` the authoritative
   source an application polls to recover a dropped webhook (`delivery_dispatch.py:9-13`),
   and `app/api/router.py:38` answers 404 for a missing row. A day is comfortably past the
   webhook retry ladder and any plausible poll interval.

Order inside the transaction is forced by the schema, not chosen: `message_parts.message_id`
and `messages.resent_from` are real foreign keys and `PRAGMA foreign_keys=ON` is set, so
parts and back-references must go first. The gate is applied as part of the write
(`DELETE ... WHERE id = ? AND status IN (...)`, decided on `rowcount`) rather than as a
separate `SELECT`, so a concurrent `_handle_cds` cannot move the status between the check and
the delete; a refusal rolls back, leaving the part records intact.

`notify_refs` is deliberately untouched: its `message_id` is a **Telegram** message id
(written by `alerting.py:129`, read by `telegram_poll.py:55` to route a Telegram reply back to
a phone), not a gateway message id. Deleting rows there by our id would delete an unrelated
record.

### D8 — Blocking gets its own query; unblocking stops deleting the row

`record_permanent_fail(phone, error, threshold)` blocks a number as a side effect of counting
failures. A manual block is not a failure, so `block_phone(phone)` sets `blocked_at` directly
(upserting the `bad_numbers` row) and leaves `fail_count` alone.

The inverse needs the same treatment, and today it does not have it: `unblock_phone` is
`DELETE FROM bad_numbers` (`queries.py:365-369`). That was tolerable while unblocking was a
rare trip to its own tab; this change puts it in every conversation. `is_phone_blocked` keys
on `blocked_at IS NOT NULL`, so clearing that column is a complete unblock and keeps
`fail_count`, `last_error` and `last_fail_at` — the evidence for the automatic threshold that
`outbound-send` relies on.

### D9 — Blocking must mean the same thing on every send path

`app/telegram_poll.py:62` creates and enqueues a message with no `is_phone_blocked` check,
unlike `app/api/router.py:21` and `app/admin/router.py:95`. That gap exists today; putting a
block button in every conversation makes it reachable in one click ("blocked, and it replied
anyway"). The check is added there.

Messages already queued for a newly blocked number are left to `outbound-send`, which already
fails a message whose destination was blacklisted after acceptance — worth knowing, because
blocking can therefore turn a `pending` message into a `failed` webhook for the owning app.

### D10 — The route stays `/admin/messages`; only the label changes

The tab is labelled *SMS* / *СМС*. Keeping the path avoids churn in the language-switch
referer logic (`router.py:378-392` rebuilds the path and query from the referer) and in
existing bookmarks. The old paths redirect into it: `/admin/inbound` → `/admin/messages`,
`/admin/dialogs` → `/admin/messages`, `/admin/dialogs/{phone}` → the SMS view filtered to
that number over all time, with its most recent row expanded.

That last redirect carries `period=all` on purpose: a deep link names a conversation, and
30-day bounding could land on an empty table with nothing to expand.

### D11 — An inbound sender is not necessarily a phone number

`_decode_address` (`app/modem/pdu.py:74-80`) returns an alphanumeric name when the address
type says so — `Tinkoff`, `MTS-Info` — and returns bare digits without `+` when the type is
not international. `handle_inbound` (`assembler.py:31,47,62`) stores that string in
`inbound_messages.phone` verbatim; only the outbound path normalises
(`api/schemas.py:22`, `admin/router.py:201`).

The merged view therefore cannot assume every row has a repliable counterparty. Reply and
block are offered only when the counterparty parses as a phone number; conversations group on
the stored string exactly as stored.

Renormalising historical rows is a **non-goal** here: it is a data migration on a column three
subsystems write, and it belongs to the inbound seam, not to a console change. The visible
consequence — a sender stored as `89991234567` would form a conversation separate from
`+79991234567` — is recorded in Risks.

### D12 — The operator column stays empty for inbound-only numbers

The `LEFT JOIN number_operators` is applied to both directions, but nothing populates that
table for a number that only ever wrote to us: `record_operator` is called on the outbound
path only, and `list_unresolved_numbers` (`queries.py:632-646`) selects `FROM messages m`.

Extending it is deliberately **not** done here. The upstream lookup is capped at 10 requests
per day per IP, and spending that budget on numbers we never send to would degrade resolution
for the ones we do — for a column that is decoration on an inbound row.

### D13 — Inbound ordering is time of receipt by the gateway

`received_at` defaults to `CURRENT_TIMESTAMP` at insert; the SMSC timestamp is parsed
(`pdu.py`, `scts`) and dropped — `save_inbound(phone, text)` does not take it. So a batch
recovered from modem memory after an outage, or a multipart flushed on timeout, is stamped
"now" and surfaces at the top of the merged stream above outbound messages that really came
first.

This was invisible while inbound had its own tab. It is visible now, and preserving `scts` is
a change to the inbound seam and its schema — out of scope here, recorded in Risks.

### D14 — Every number in a query string is percent-encoded

The number moves from the path (`/admin/dialogs/{phone}`, where `+` is a literal) into the
query, where `+` decodes to a space. Existing templates already concatenate query strings by
hand (`messages.html:61,65`, `inbound.html:40,44`) and are only accidentally correct because
`phone` is a `LIKE` filter; the one place that does it properly is `router.py:108-111`, with
`urlencode`.

Every link, redirect and hidden field that carries a number goes through `urlencode` /
Jinja's `|urlencode`. The tests use an explicitly `+`-prefixed number, since a test written
with a bare `79…` would pass while production failed.

### D15 — Destructive posts check the request origin

The console authenticates with HTTP Basic and carries no per-request token, so a browser
will attach cached credentials to a cross-site form post, and this change introduces the
first irreversible action reachable that way. Delete and block reject a request whose
`Origin`/`Referer` names another site. A header-absent request is allowed, so `curl` and the
existing tests keep working; this is a cheap guard against a browser-driven post, not a full
CSRF token scheme, and saying so is the point.

## Risks / Trade-offs

- **`UNION ALL` + `ORDER BY ts` cannot use an index** → at today's ~1200 rows and a plausible
  ceiling of a few tens of thousands, SQLite sorts this well inside the render budget. If it
  ever bites, the fix is an index on `messages(created_at)` and `inbound_messages(received_at)`
  — additive, no migration risk. Not added now, so this change stays schema-free.

- **Expanding costs a full page load** → accepted (D2). The same `open=` endpoint can be
  enhanced with a `fetch()` later without changing the contract.

- **The default view no longer shows all history** → the *all time* option is one click away
  and the record count states what it is counting. This is the point of the change, but it is
  a behavioural surprise for the first person who opens it looking for an old message.

- **Deletion is irreversible and now reaches outbound messages** → mitigated by the three-way
  gate (D7), a confirmation prompt, an origin check (D15) and a log line naming what went.
  There is no soft delete: a `deleted_at` column would mean every existing query learns to
  exclude it, which is a larger change than the one being asked for.

- **The deletion gate will refuse cases an operator expects to work** → an `expired` message
  and a fresh `failed` one are exactly the rows someone wants to tidy, and both are refused.
  The refusal must say *why*, or it will be read as a bug.

- **Unblocking changes behaviour on the existing Blacklist tab** → a number unblocked there
  now keeps its row and its failure history instead of vanishing from the list. This is the
  intended fix, but it changes what that tab shows.

- **A non-international inbound sender splits a conversation** → a number stored as
  `89991234567` forms a conversation separate from `+79991234567` (D11). Not observed on this
  SIM's traffic, which arrives international, and not fixed here.

- **Inbound rows can jump to the top of the stream out of true order** → reconcile sweeps and
  multipart flushes stamp `received_at` at insert (D13). Only visible after an outage.

- **Offset pagination over a stream that grows at the top** → a message arriving between the
  count and the render shifts every subsequent page by one. Pre-existing, but more noticeable
  now that both directions land in one list.

- **Removing three templates and two routes touches tests** → `test_admin_dialogs_tz.py`,
  `test_admin_reply_phone.py`, `test_admin_resend.py` and `test_i18n_completeness.py` all
  exercise the old locations. `test_i18n_completeness.py` breaks twice over: it asserts 200
  for `/admin/inbound`, `/admin/dialogs` and `/admin/dialogs/+79995550011` (lines 41-47), and
  it asserts the Russian string `За 14 дней` that D6 retires (line 62). These are rewritten
  against the new locations, not deleted — the behaviour they guard is still required.

## Migration Plan

No schema change, so no data migration. Deploy is the ordinary unit restart.

Rollback is a revert of the code — the previous version reads the same tables and the same
columns. The one asymmetry: rows deleted through the new action do not come back, and numbers
unblocked after this ships keep a `bad_numbers` row that the old Blacklist tab will display as
an unblocked entry rather than omitting.
