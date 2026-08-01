Slices are vertical on purpose: each one carries its queries, its route and its template
together, so its tests can go green before the next slice starts. Cutting by layer would leave
the router tests red until the templates landed three sections later.

## 1. Period, end to end

- [x] 1.1 Test: each of `24h`/`7d`/`30d`/`1y`/`all` resolves to its lower bound; `all` to none; missing, empty and unrecognised values all resolve to `30d`
- [x] 1.2 Implement the period vocabulary and resolver
- [x] 1.3 Add the period selector to `base.html`, and carry the current period on the SMS and Statistics nav links (defaulting where a page has none)
- [x] 1.4 Test: the nav links rendered on the SMS view carry the selected period through to the statistics view

## 2. The merged listing

- [x] 2.1 Test: `list_thread_page` returns both directions in one result ordered by `ts DESC`, with an inbound row of lower id sorting above an older outbound row
- [x] 2.2 Test: rows sharing one timestamp page deterministically — every row appears exactly once across pages, none twice
- [x] 2.3 Test: the period bound excludes an out-of-window message in both directions; `all` includes it; the bound applies to `created_at`/`received_at`
- [x] 2.4 Test: phone, status and direction filters compose with the period; a status forces the outbound direction and choosing inbound clears the status
- [x] 2.5 Implement `list_thread_page` / `count_thread_page` as one `UNION ALL` over `messages` and `inbound_messages`, ordered `ts DESC, direction DESC, id DESC`, left-joined to `number_operators`
- [x] 2.6 Rewire `admin_messages` to take `period`, `direction`, `open` alongside `phone`, `status`, `page`, applying the status/direction normalisation
- [x] 2.7 `messages.html`: direction column, direction filter, row keys `out-<id>` / `in-<id>`, row links to `?…&open=<key>#row-<key>`
- [x] 2.8 Test: `/admin/messages` with no query renders the 30-day period selected and lists both directions; the record count matches the filtered set

## 3. Encoding numbers into URLs

- [x] 3.1 Test: a `+`-prefixed number survives paging — the next-page link filters on `+7…`, not on a space-prefixed number
- [x] 3.2 Route every number that enters a query through `urlencode` / `|urlencode`: pagination links, row links, hidden form fields, action redirects
- [x] 3.3 Fix the hand-built query strings already in the templates while passing through them

## 4. The conversation panel

- [x] 4.1 Test: `?open=out-<id>` renders the conversation with that row's number once, including a message older than the selected period
- [x] 4.2 Test: a number holding several rows in the period renders the conversation once, under the selected row only
- [x] 4.3 Test: an `open` key naming a row that does not exist renders the table with nothing expanded
- [x] 4.4 Test: a thread longer than 100 messages shows the most recent 100 and offers the rest
- [x] 4.5 Implement the expansion: resolve the number from the row key, load `dialog_for` with a limit, render into a spanning row
- [x] 4.6 Realign `dialog_for` to order outbound by `created_at` (it uses `COALESCE(sent_at, created_at)` today) so the panel and the table agree
- [x] 4.7 Reuse the existing `.timeline` / `.bubble` styles; add styling for the spanning row and the period selector
- [x] 4.8 Test: a row whose counterparty is an alphanumeric sender (`Tinkoff`) expands without a reply field and without a block action, and its messages group into one conversation

## 5. Reply and re-send from the panel

- [x] 5.1 Move the reply endpoint off `/admin/dialogs/{phone}/reply`, keeping phone normalisation, the blacklist refusal and `admin` ownership (the guarantees `tests/test_admin_reply_phone.py` covers); point that test at the new location
- [x] 5.2 Extend the re-send endpoint to carry period, filters, page and `open` through its redirect; its `failed`/`expired` gate and blacklist refusal are unchanged; update `tests/test_admin_resend.py`
- [x] 5.3 Test: reply and re-send each return to the same period, filters, page and expanded conversation they were called from

## 6. Deletion

- [x] 6.1 Test: deletion is refused for `pending`, `sent` and `expired`, and for a `delivered` message younger than 24 hours
- [x] 6.2 Test: deletion is refused while a message re-sent from it is not yet `delivered`/`failed`, and permitted once that copy is terminal
- [x] 6.3 Test: a refused deletion leaves the message, its `message_parts` rows and every `resent_from` reference untouched
- [x] 6.4 Test: an eligible delete removes the message and its `message_parts` in one transaction, clears `resent_from` on any message naming it, and leaves `notify_refs` alone
- [x] 6.5 Implement `delete_outbound(message_id)` — gate applied inside the write (`DELETE … WHERE id = ? AND status IN (…)`, decided on `rowcount`), FK-forced order, rollback on refusal
- [x] 6.6 Add the delete endpoint taking direction explicitly; inbound reuses `delete_inbound`
- [x] 6.7 Log every deletion with number, direction, id and the beginning of the text
- [x] 6.8 Test: the refusal reaching the operator names the reason, rather than failing anonymously

## 7. Blocking

- [x] 7.1 Test + implement `block_phone(phone)` — upserts `bad_numbers` with `blocked_at` set, leaving `fail_count` alone
- [x] 7.2 Test: unblocking a number with recorded failures lifts the block and preserves `fail_count`, `last_error`, `last_fail_at`
- [x] 7.3 Change `unblock_phone` from `DELETE FROM bad_numbers` to clearing `blocked_at`; check the Blacklist tab still reads correctly with unblocked rows present
- [x] 7.4 Test: a Telegram reply addressed to a blacklisted number creates and enqueues nothing
- [x] 7.5 Add the `is_phone_blocked` check to `app/telegram_poll.py` before it creates the message
- [x] 7.6 Add the block/unblock endpoint reachable from the conversation; log a manual block
- [x] 7.7 Test: block then unblock from a conversation leaves the number off the blacklist

## 8. Origin check on destructive posts

- [x] 8.1 Test: a delete or block carrying a foreign `Origin` is refused and changes nothing; one with no `Origin`/`Referer` is allowed; a same-origin one succeeds
- [x] 8.2 Implement the check as a dependency on the delete and block endpoints

## 9. Statistics

- [x] 9.1 Test: status counts are bounded by the period and keyed on creation time — a message created before the window and delivered inside it is not counted
- [x] 9.2 Test: the inbound count is reported for the period
- [x] 9.3 Test: bucketing follows the period (hourly / daily / monthly) and falls on MSK days — the boundary case moved from `tests/test_stats_day.py` into `tests/test_stats_period.py`, and the old file went with `daily_counts`
- [x] 9.4 Implement `status_counts(period)`, `inbound_count(period)`, `period_buckets(period)`
- [x] 9.5 `stats.html`: period selector, inbound card, bucketed breakdown with a heading naming the period
- [x] 9.6 Retire `daily_counts`

## 10. Redirects and removal

- [x] 10.1 Test: `/admin/inbound` and `/admin/dialogs` redirect to the SMS view
- [x] 10.2 Test: `/admin/dialogs/+79995550011` redirects to the SMS view filtered to that number over all time with its most recent row expanded, and the `phone` parameter decodes back to `+79995550011`
- [x] 10.3 Replace the three route bodies with redirects
- [x] 10.4 Delete `inbound.html`, `dialogs.html`, `dialog.html`; drop the `Inbound` and `Dialogs` nav entries and rename `Outbound` to SMS in `base.html`
- [x] 10.5 Retire the now-dead queries: `count_inbound`, `dialog_phones`, `list_messages`, `count_messages`. **`list_inbound` stays** — the admin was not its only caller; `tests/test_assembler.py` and `tests/test_inbound_reconcile.py` read inbound through it

## 11. Translations

- [x] 11.1 Add every new msgid to `app/admin/translations/ru` and `.../en`, including an empty-conversation string to replace the one lost with `dialog.html`
- [x] 11.2 Remove the msgids left dead by the removed templates (`Inbound`, `Dialogs`, `All dialogs`, `No dialogs`, `Last 14 days`)

## 12. Test-suite repair and documentation

- [x] 12.1 `tests/test_i18n_completeness.py`: replace `/admin/inbound`, `/admin/dialogs`, `/admin/dialogs/+…` in the path list, and replace the `За 14 дней` assertion with a string the new statistics view renders
- [x] 12.2 Rewrite `tests/test_admin_dialogs_tz.py` against the SMS view — the MSK rendering it guards is still required
- [x] 12.3 Update `openspec/specs/outbound-send/spec.md` evidence pointers that name the moved admin endpoints
- [x] 12.4 `docs/api.md` — admin path table and the "14-day breakdown" wording (RU `:171`, EN `:350`); blacklist policy now has a manual path (`:177`); note that `GET /sms/{id}` can 404 for a message an operator deleted
- [x] 12.5 `docs/project-structure.md` — the template tree still lists the three removed files
- [x] 12.6 `README.md` — the admin-UI feature line, and the screenshot table (`:130`, `:377`) which captions a Dialog view that no longer exists
- [x] 12.7 Re-shoot `docs/img/messages.png` and replace `docs/img/dialog.png` with the expanded-row view
- [x] 12.8 `CHANGELOG.md` — entry noting the merged tab, the period default, the unblock behaviour change and the redirected URLs

## 13. Verification

- [x] 13.1 Run the full suite (`python -m pytest`) and confirm it is green
- [x] 13.2 Run the app locally against a copy of the database: default view, an expanded conversation, each action including a refused deletion, each period on both views, the redirects from the old URLs, and a conversation with an alphanumeric sender
- [x] 13.3 Check the rendered table for layout regressions — the direction column, the period selector and the spanning row must not push the page into horizontal scrolling, on desktop and at the 640 px breakpoint
