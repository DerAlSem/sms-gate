## Why

One conversation with one number is currently spread across three tabs. **Outbound** shows
what was sent, **Inbound** shows what arrived, **Dialogs** stitches them back together —
and the operator has to do that stitching by eye, tab by tab, to answer the only question
that ever comes up: *what did we say to this number, what did they answer, and did it
arrive?*

The split is an artifact of how the features were built (outbound first, inbound later,
dialogs bolted on to reconcile them), not of how the gateway is used.

The second gap is time. Every view is all-time: the outbound table opens on 1154 records
going back to the first message ever sent, and the statistics cards count the same
unbounded history. "How much did we send in the last month" is not answerable without
exporting the database.

## What Changes

- **`Inbound` and `Dialogs` disappear as tabs.** Their content moves into a single **SMS**
  tab. `/admin/inbound` and `/admin/dialogs` stop being canonical URLs and become redirects,
  so existing bookmarks and the deep links in Telegram alerts keep working.

- **The SMS table lists messages of both directions in one stream**, ordered by time, with
  the layout the outbound table has today plus a direction marker. An inbound message is
  findable by its text in the same place an outbound one is — which is what makes losing
  the `Inbound` tab a simplification rather than a removal of function.

- **A row expands in place into the conversation with that number.** The expanded panel is
  today's dialog timeline — inbound and outbound bubbles, statuses, errors — plus the
  actions that were previously scattered: reply, re-send a failed or expired outbound,
  delete a message, block or unblock the number.

- **Deleting an outbound message is new, and is hedged.** It is permitted only for a
  `delivered` or `failed` message that is at least a day old and has no re-sent copy still
  in flight. Each of those conditions protects a promise the gateway has already made:
  `expired` messages still accept a late delivery report, a fresh message is still
  answerable through `GET /sms/{id}`, and a re-sent copy still owes its `resent_from` to
  every notification it sends.

- **Unblocking a number stops deleting its failure history.** Blocking becomes a routine
  in-conversation action, so its inverse must stop wiping the automatic failure counter —
  otherwise a number that earned its blacklist threshold gets a fresh budget every time an
  operator lifts a block. **This changes the existing Blacklist tab's unblock behaviour.**

- **A Telegram reply to a blacklisted number is refused.** That path creates outbound
  messages without checking the blacklist today; putting a block button in every
  conversation makes the hole reachable in one click.

- **A period selector — 24 hours, 7 days, 30 days, a year, all time — governs the SMS
  table**, defaulting to **30 days**. The options are labelled by the window they apply:
  these are rolling windows, and a control labelled "month" over a rolling 30 days would
  answer a different question from the one it appears to answer.

- **Statistics stays its own tab and gains the same selector.** Its cards count the chosen
  period instead of all time, its breakdown is bucketed to suit the period rather than
  always by day, and it counts **inbound messages too** — with the `Inbound` tab gone,
  nothing else reports how much arrived.

## Capabilities

### New Capabilities

- `admin-sms-console`: the merged SMS view **and the statistics view that shares its
  period** — the two-direction message table, the period selector, the in-place
  conversation panel, the actions available from it and their preconditions, and what
  statistics counts. The remaining admin tabs (prefixes, apps, settings, modem) stay
  unspecced and are untouched.

### Modified Capabilities

None. `outbound-send` and `delivery-dispatch` are load-bearing here — deletion must not
break either — but the change adapts to their requirements rather than altering them, and
the conditions that keep them whole are stated as requirements of the new capability.

The blacklist has no spec today; the unblock change above is called out in *What Changes*
rather than as a delta, and the new capability states only what blocking means from a
conversation.

## Impact

- `app/admin/router.py` — `/admin/messages` gains period, direction and expansion
  parameters; `/admin/inbound` and `/admin/dialogs*` collapse into redirects; `/admin/stats`
  gains the period; new delete and block/unblock endpoints with an origin check.
- `app/admin/templates/` — `messages.html` absorbs the expandable row; `inbound.html`,
  `dialogs.html` and `dialog.html` are removed; `base.html` loses two nav entries and gains
  the period selector.
- `app/db/queries.py` — a combined two-direction listing with period bounds and a
  deterministic order, period-bounded statistics, deletion of an outbound message, a manual
  block, and an unblock that preserves history. `daily_counts`, `list_inbound`,
  `count_inbound` and `dialog_phones` retire.
- `app/telegram_poll.py` — a blacklist check before a reply becomes an SMS.
- `app/admin/translations/{ru,en}` — new strings, and dead ones removed;
  `test_i18n_completeness.py` enforces both catalogues stay complete and needs its path
  list and its Russian assertion updated.
- `docs/api.md`, `docs/project-structure.md`, `README.md`, `CHANGELOG.md`, and the two
  admin screenshots under `docs/img/`.
- No schema change. No modem, API or webhook path is touched.
