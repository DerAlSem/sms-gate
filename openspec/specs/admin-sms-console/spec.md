# admin-sms-console Specification

## Purpose
TBD - created by archiving change merge-inbound-and-dialogs-into-sms-tab. Update Purpose after archive.
## Requirements
### Requirement: One SMS view carries both directions

The admin console SHALL present outbound and inbound messages in a single view, reachable
from one navigation entry. It SHALL NOT offer separate navigation entries for inbound
messages or for dialogs.

Each row SHALL show the message's direction, so that a stream carrying both is readable
without opening anything.

#### Scenario: Both directions appear in one table

- **WHEN** the SMS view is opened and the selected period contains both a sent and a
  received message
- **THEN** both appear as rows in the same table, each marked with its direction

#### Scenario: Inbound and dialog navigation entries are gone

- **WHEN** any admin page is rendered
- **THEN** the navigation offers no `Inbound` entry and no `Dialogs` entry

#### Scenario: Old inbound and dialog URLs still answer

- **WHEN** `/admin/inbound` or `/admin/dialogs` is requested
- **THEN** the response redirects to the SMS view

#### Scenario: A dialog deep link opens the conversation it named

- **WHEN** `/admin/dialogs/<phone>` is requested
- **THEN** the response redirects to the SMS view filtered to that number over all time,
  with that number's most recent row expanded

### Requirement: Rows are keyed by direction and ordered deterministically

The view SHALL identify a row by its direction together with its id — outbound and inbound
are numbered by two independent sequences, so an id alone is ambiguous.

Rows SHALL be ordered by `created_at` for outbound and `received_at` for inbound, most
recent first, and SHALL break ties on equal timestamps by direction and then by id
descending. The same column SHALL be the one the period bounds.

`CURRENT_TIMESTAMP` has one-second resolution, so equal timestamps are ordinary; an
unbroken tie under `LIMIT`/`OFFSET` lets a row appear on two pages or on neither.

#### Scenario: Interleaved by time, not by id

- **WHEN** an inbound message arrives after an outbound message was created, and the
  inbound id happens to be lower
- **THEN** the inbound message is listed above the outbound one

#### Scenario: Equal timestamps still page deterministically

- **WHEN** more messages share one timestamp than fit on a page
- **THEN** every message appears exactly once across the pages, in a stable order

#### Scenario: Colliding ids stay distinct

- **WHEN** an outbound message and an inbound message share the same id
- **THEN** each row addresses its own record, and an action taken on one does not affect
  the other

### Requirement: A period governs what the view lists and counts

The SMS view and the statistics view SHALL each be bounded by a selected period, chosen
from **24 hours**, **7 days**, **30 days**, **a year** and **all time**. When no period is
given, or the given one is not recognised, the selected period SHALL be **30 days**.

A period other than *all time* SHALL be a window measured back from the present. The
options SHALL be labelled by the window they actually apply — a control labelled "month"
over a rolling 30-day window would answer a different question from the one it appears to
answer.

The navigation links between the SMS view and the statistics view SHALL carry the currently
selected period.

#### Scenario: 30 days is the default

- **WHEN** the SMS view is opened without a period
- **THEN** the table lists messages from the last 30 days and the 30-day option is shown
  as selected

#### Scenario: An unrecognised period falls back to the default

- **WHEN** the SMS view is opened with a period value that is not one of the five
- **THEN** the view renders the 30-day period rather than failing

#### Scenario: A message outside the period is absent

- **WHEN** the period is *7 days* and a message is 10 days old
- **THEN** that message is not listed and is not counted

#### Scenario: All time restores the full history

- **WHEN** the period is *all time*
- **THEN** every message is eligible for listing, with no lower time bound

#### Scenario: The period follows the operator across views

- **WHEN** the period is *a year* on the SMS view and the statistics view is opened from
  the navigation
- **THEN** the statistics view opens on the same period

### Requirement: Filters compose with the period, and status implies outbound

The view SHALL offer a phone-number filter, a status filter and a direction filter, and
SHALL apply them together with the selected period. The record count shown SHALL be the
count of rows matching every active filter within the period, not the count of all
messages.

Status is a property of outbound messages only. An active status filter SHALL force the
direction to outbound, and the control that selects the inbound direction SHALL NOT carry a
status filter with it — the combination "delivered inbound" has no meaning, and silently
returning an empty table for it would read as a fault.

The rule is one-directional on purpose. Both controls submit on every request, so a server
that also let the direction clear the status could not tell which of the two the operator
had just changed; making the status the deciding one, and having the inbound control drop
the status as it navigates, leaves no ambiguous state to resolve.

#### Scenario: Count reflects the filtered set

- **WHEN** the period is *30 days*, a phone filter is active, and 3 messages match
- **THEN** the view reports 3 records

#### Scenario: Direction filter narrows to one direction

- **WHEN** the direction filter is set to inbound
- **THEN** only received messages are listed

#### Scenario: Choosing a status forces the outbound direction

- **WHEN** the status filter is set to `delivered` while the direction filter is inbound
- **THEN** the view lists delivered outbound messages and shows the direction as outbound

#### Scenario: The inbound control carries no status with it

- **WHEN** the table is filtered by a status and the control selecting the inbound
  direction is rendered
- **THEN** that control's target carries no status filter, so following it lists inbound
  messages

### Requirement: Every phone number placed in a URL is percent-encoded

Every link, redirect target and form field that carries a phone number in a query SHALL
percent-encode it, and every handler SHALL read back the number it was given. A number in
E.164 form begins with `+`, which decodes to a space in a query string.

#### Scenario: A number survives the round trip through a query string

- **WHEN** `/admin/dialogs/<phone>` for `+79001234567` is requested and the redirect is
  followed
- **THEN** the SMS view filters on `+79001234567`, not on a number with a leading space

#### Scenario: Paging preserves the filtered number

- **WHEN** a phone-filtered table is paged
- **THEN** the next page is filtered on the same number

### Requirement: A row expands into the conversation with its number

Selecting a row SHALL reveal, in place, the conversation with that row's number — messages
of both directions in chronological order, each outbound one carrying its status and, when
present, its error. The expanded conversation SHALL appear exactly once, under the selected
row, even when the same number occupies several rows of the table.

Expansion SHALL be addressed by the row's key, not by its number, and SHALL leave the
period, the filters and the page unchanged.

The conversation SHALL NOT be bounded by the selected period. The period bounds what the
table lists; a conversation cut off mid-thread cannot be read.

The conversation SHALL show at most the most recent 100 messages, offering the rest on
request. It is rendered inside the list page and re-rendered after every action, so an
unbounded thread would be paid for repeatedly.

#### Scenario: The thread opens in place

- **WHEN** a row for a number with earlier traffic is selected
- **THEN** the conversation with that number appears below that row, and the table around
  it keeps its period, filters and page

#### Scenario: One conversation, not one per row

- **WHEN** the selected row's number has several rows within the period
- **THEN** the conversation is rendered once, under the selected row

#### Scenario: The thread predates the period

- **WHEN** the period is *24 hours* and the selected row's number was last written to a
  year ago
- **THEN** the expanded conversation still shows that year-old message

#### Scenario: A long thread is capped

- **WHEN** a number's conversation holds more than 100 messages
- **THEN** the most recent 100 are shown, with the earlier ones available on request

#### Scenario: An expansion key that names nothing

- **WHEN** the view is requested with an expansion key for a row that does not exist
- **THEN** the table renders normally with nothing expanded, rather than failing

### Requirement: The conversation panel carries the message actions

The expanded conversation SHALL offer, subject to each action's own preconditions:

- **reply** — send a new SMS to that number;
- **re-send** — queue a fresh copy of an outbound message;
- **delete** — remove a message;
- **block / unblock** — add the number to the blacklist or lift the block.

After any of these actions the view SHALL return to the same period, the same filters, the
same page, and the same conversation expanded.

Re-send and reply keep the guarantees `outbound-send` already states for them — phone
normalisation, refusal for a blacklisted destination, the `failed`/`expired` precondition on
re-send, and `admin` ownership. This capability adds only where those actions are reachable
from and where they return to.

#### Scenario: Acting leaves the operator where they were

- **WHEN** a reply is sent from a conversation opened on page 2 of a phone-filtered,
  7-day-bounded table
- **THEN** the view returns to page 2 of that same filtered, 7-day-bounded table with the
  same conversation expanded

### Requirement: Actions are offered only where they can succeed

The view SHALL offer **reply** and **block** only for a row whose counterparty is a valid
phone number, and SHALL group a conversation by the stored sender string exactly as stored.
A received message's sender is stored as the network delivered it and need not be a phone
number: a service sender arrives as a name such as `Tinkoff`.

Offering a reply to a name would produce a validation failure at send time, and offering a
block would write a non-number into the blacklist.

#### Scenario: A service sender offers no reply

- **WHEN** a row whose sender is `Tinkoff` is expanded
- **THEN** the conversation is shown without a reply field and without a block action

#### Scenario: A service sender's messages still group together

- **WHEN** several messages arrive from `Tinkoff`
- **THEN** they appear in one conversation under that sender

### Requirement: Destructive actions verify the request's origin

Deleting a message and blocking a number SHALL be rejected when the request carries an
`Origin` or `Referer` that is not this console's own.

The console authenticates with HTTP Basic and holds no per-request token, so a browser will
attach cached credentials to a cross-site form post. This change adds the first irreversible
action reachable that way.

#### Scenario: A cross-site delete is refused

- **WHEN** a delete is posted with an `Origin` header naming another site
- **THEN** the request is refused and the message remains

#### Scenario: An ordinary same-origin action succeeds

- **WHEN** a delete is posted from the console itself
- **THEN** it is carried out

### Requirement: Deletion is refused while anything still depends on the message

Deleting an outbound message SHALL be permitted only when **all** of the following hold:

- its status is `delivered` or `failed`. **`expired` is not deletable**: an expired message
  remains eligible for a late delivery report, which `delivery-dispatch` requires to correct
  itself to `delivered`;
- no message re-sent from it is still in flight — that is, every message whose `resent_from`
  names it is itself `delivered` or `failed`. `delivery-dispatch` requires `resent_from` in
  **every** notification for the re-sent message, and that field is read at notification
  time;
- it is at least 24 hours old. `GET /sms/{id}` is the authoritative status source an
  application polls to recover a dropped webhook; deleting a fresh message replaces that
  answer with a 404 indistinguishable from "no such message".

Deleting an outbound message SHALL remove its per-part delivery records in the same
transaction, and SHALL clear the `resent_from` reference of any message that named it. If
the request is refused, nothing SHALL be removed.

Deleting an inbound message SHALL remove that message.

Deletion and manual blocking SHALL each be recorded in the log with the number, the
direction, the id and the beginning of the text. There is no soft delete, so the log is the
only trace that survives.

#### Scenario: An in-flight message cannot be deleted

- **WHEN** deletion is requested for a message in `sent` or `pending` state
- **THEN** the request is refused and the message remains

#### Scenario: An expired message cannot be deleted

- **WHEN** deletion is requested for a message in `expired` state
- **THEN** the request is refused, because a delivery report may still arrive for it

#### Scenario: A fresh message cannot be deleted

- **WHEN** deletion is requested for a `delivered` message created an hour ago
- **THEN** the request is refused

#### Scenario: A message with an in-flight re-send cannot be deleted

- **WHEN** deletion is requested for a `failed` message whose re-sent copy is still `sent`
- **THEN** the request is refused, so the copy's notifications keep carrying `resent_from`

#### Scenario: Deleting takes the part records with it

- **WHEN** an eligible multipart message with recorded parts is deleted
- **THEN** the message and its part records are gone, and no orphaned part record remains

#### Scenario: A refused deletion changes nothing

- **WHEN** deletion is refused for any reason
- **THEN** the message, its part records and every reference to it are unchanged

#### Scenario: Telegram notification references are untouched

- **WHEN** an outbound message is deleted
- **THEN** rows in `notify_refs` are unaffected — its `message_id` is a Telegram message id,
  not a gateway message id

#### Scenario: Deleting an inbound message

- **WHEN** deletion is requested for a received message
- **THEN** that message is removed and the conversation no longer shows it

### Requirement: Blocking refuses new sends on every path, and unblocking keeps the history

Blocking a number from the conversation SHALL mark it blocked without disturbing the
automatic failure counter that `outbound-send` accumulates against it, and unblocking SHALL
lift the block while keeping that counter and its recorded failures.

Deleting the blacklist row on unblock would hand a number that earned its threshold a fresh
budget of failures.

While a number is blocked, **every** path that creates an outbound message SHALL refuse it,
including a reply arriving through Telegram. Messages already accepted for that number are
governed by `outbound-send`, which fails a queued message whose destination was blacklisted
after acceptance.

#### Scenario: Unblocking preserves the failure count

- **WHEN** a number with recorded failures is blocked from a conversation and then unblocked
- **THEN** it is no longer blocked, and its failure count and last error are unchanged

#### Scenario: A Telegram reply to a blocked number is refused

- **WHEN** a Telegram reply is received for a number that is blacklisted
- **THEN** no message is created and none is queued

#### Scenario: Blocking is reversible from the same place

- **WHEN** a number is blocked from its conversation
- **THEN** the same conversation offers unblocking

### Requirement: Statistics are reported for the selected period

The statistics view SHALL count only messages within the selected period, SHALL report the
number of **received** messages alongside the outbound status counts, and SHALL break the
period down over time buckets sized to it: hourly for *24 hours*, daily for *7 days* and
*30 days*, monthly for *a year* and *all time*. Buckets SHALL be computed in MSK, as the
rest of the console is.

A message SHALL belong to a period by the time it was created — received, for an inbound
message — and SHALL be counted under its current status. Status is a present-tense fact, not
an event inside the window.

#### Scenario: Cards count the period, not all history

- **WHEN** the statistics view is opened with the period *7 days*
- **THEN** each status card counts only messages created in the last 7 days

#### Scenario: A message created before the period but delivered inside it is not counted

- **WHEN** the period is *7 days* and a message created 10 days ago was delivered yesterday
- **THEN** it is not counted

#### Scenario: Received messages are reported

- **WHEN** the statistics view is opened
- **THEN** it reports how many messages were received in the period

#### Scenario: The breakdown is bucketed to the period

- **WHEN** the period is *a year*
- **THEN** the breakdown has one row per month rather than one row per day

#### Scenario: Buckets fall on MSK days

- **WHEN** a message was created at 23:30 UTC, which is 02:30 MSK the next day
- **THEN** it is bucketed into the MSK day

