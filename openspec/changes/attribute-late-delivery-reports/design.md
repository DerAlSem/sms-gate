## Context

The gateway learns the fate of a sent message from an unsolicited `+CDS` line. Everything
it knows about which message that line is about comes from one field, and that field is not
ours.

### The wire contract

`docs/modem.md:103` records a captured sample and the layout:

```
+CDS: 6,42,"+79991234567",145,"26/04/17,12:00:01+12","26/04/17,12:00:03+12",0
       fo,mr,ra          ,tora,scts                 ,dt                    ,st
```

| field | meaning | used today |
|---|---|---|
| `fo` | first octet | no |
| `mr` | TP-Message-Reference — the value `+CMGS` returned | **yes** |
| `ra` | recipient address of the original submit | no |
| `tora` | type of that address (129 national, 145 international) | no |
| `scts` | service centre timestamp **of the original submit** | no |
| `dt` | discharge time | no |
| `st` | TP-Status | **yes** |

`_CDS_PATTERN` (`app/modem/parser.py:19-21`) already walks past `ra`, `tora`, `scts` and
`dt` to reach `st`, consuming them as unnamed groups. The pattern is known to match live
lines of **both** outcomes: every `DELIVERED` row in the journal came through it, and so did
the `st=64` alert of 2026-09-02 that prompted this change.

⚠️ **The group numbers are positional.** `parse_cds` reads `group(1)` as `mr` and
`group(2)` as `st`. Capturing `ra` and `scts` renumbers them, and an implementation that
forgets to re-index will read the status out of a timestamp — `delivered` becomes
"the timestamp is not the string 0", which is always false, and every delivery in the
system silently becomes a failure. This is the single most dangerous edit in the change and
it is invisible to every scenario that builds a `DeliveryReport` by hand, as the existing
tests do (`tests/test_delivery_hooks.py:167-192`).

### Why one field is not enough

`mr` is a single octet chosen by the modem. Two facts make it repeat:

1. **It wraps.** 0…255 and round again — at this volume roughly every three weeks.
2. **It was suspected of restarting** on the recovery ladder's `AT+CFUN=1,1`
   (`app/modem/at_commands.py:675`), which would make references repeat minutes apart.
   **Measured and not supported:** across 1765 messages the reference decreases eight times,
   seven of them exactly `255 -> 0`, and the eighth is a wrap crossing the boundary while
   references were consumed without producing a message row. It wraps; it has not been seen
   to restart.

The fix does not depend on which generator dominates — it is a rule for telling two messages
apart when they share a reference, and it does not care why they do. The measurement matters
for one thing only: it is what lets the age window be a bound rather than a guess, since a
counter that merely wraps repeats on a period the traffic rate makes predictable.

## Goals / Non-Goals

**Goals**

- A delivery report changes the status of the message it is about, or of no message.
- Evidence the report already carries is used instead of discarded.
- Missing or unusable evidence degrades to today's behaviour, never to a refusal.
- Every report the gateway receives survives its own processing, so a wrong decision can be
  found afterwards and a dropped report is not lost.

**Non-Goals**

- **Switching `+CDS` to PDU mode.** The text form carries everything needed.
- **`messages.modem_ref`** — written by `set_message_sent` and read by nothing (verified:
  no reader outside the write). Left alone.
- **The UDH concatenation reference**, `msg.message_id % 256` (`app/modem/manager.py:469`),
  which wraps on the same period and governs reassembly on the recipient's handset. A
  separate concern with a separate blast radius; named here so the next reader does not
  read "the one-octet problem" as settled everywhere.
- **The intermediate-status defect.** `parse_cds` treats every non-zero `st` as a failure
  (`parser.py:167`), including the 0x20–0x3F "still trying" band that `_tp_status_class`
  itself calls temporary. Such a report moves the message to `failed`, which is not an
  eligible status, so the real verdict can never be applied afterwards. This change neither
  fixes nor worsens it, and carries the requirement forward verbatim; it is a separate
  change and task 8.2 opens it.
- **Recovering attributions already lost.** Part rows overwritten before this ships are
  gone.
- **Replaying a recorded report.** The ledger is evidence, not a queue: an operator can see
  that a report was refused and can turn the switch back off, but there is no operation that
  applies a recorded report after the fact, and no admin control that edits a message's
  status. Building one is a separate decision with its own surface.

## Decisions

### D1 — this is record linkage, and the two sides get separate identities

A part's identity is `(message_id, seq)` — the only two facts the gateway owns at send time.
A report's identity is `(mr, ra, scts)` — facts the network owns. Neither is the other, and
joining them is a linkage decision that can be wrong. The design therefore keeps both sides
addressable and records the join it made, rather than treating the modem's counter as a
primary key and calling the question answered.

`message_parts` becomes `PRIMARY KEY (message_id, seq)`, with `modem_ref` an ordinary
indexed column that repeats and a `sent_at` per part.

Rejected: keeping the reference unique and having the *sender* retire colliding rows. The
reference is not ours to allocate; a scheme whose correctness depends on a value the modem
picks is the defect in another shape.

Per-part `sent_at` rather than `messages.sent_at`: the message is dated by its first part
(`outbound-send`, "A message becomes `sent` when its first part is accepted"), so the
message's timestamp dates the message, not the segment.

### D2 — every report is written down before anything is decided

A new append-only table `delivery_reports` records each `+CDS`: its parsed fields, the raw
line, the outcome of attribution, and the candidates considered.

This is what makes the rest safe:

- a report that is dropped is **kept**, so the proposal's own complaint — "the message the
  report was actually about can never be corrected" — is not reproduced by the fix;
- the risky rule (D3) can ship **recording but not acting**, and be turned on against a
  week of real evidence rather than an argument;
- "how many reports did we discard last week, and were they really about nothing" becomes a
  query instead of a grep through logs that have rotated.

```sql
CREATE TABLE delivery_reports (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    raw_line      TEXT NOT NULL,      -- the only field an unparsable report still has
    modem_ref     INTEGER,            -- everything below is nullable by design
    recipient     TEXT,
    submitted_at  TIMESTAMP,          -- scts, resolved to UTC
    discharged_at TIMESTAMP,          -- dt
    status_code   INTEGER,
    outcome       TEXT NOT NULL,      -- attributed | superseded | unplaced
                                    -- | unparsable   (the parser could not read it)
                                    -- | unprocessable (it parsed; handling it raised —
                                    --   the loop guard's own outcome, kept apart because
                                    --   the two say different things about what broke)
    reason        TEXT,               -- why, in words: "the record carries ... the reason"
    decided_by    TEXT,               -- sole | nearest | recency
    message_id    INTEGER,            -- NOT a foreign key; see below
    seq           INTEGER,
    candidates    TEXT,               -- JSON: every part whose reference matched, with its own outcome
    window_hours  INTEGER,            -- the settings this decision was made under
    strict        INTEGER
);
CREATE INDEX idx_delivery_reports_at  ON delivery_reports(received_at);
CREATE INDEX idx_delivery_reports_ref ON delivery_reports(modem_ref);
```

- **`message_id` is deliberately not a foreign key.** With `PRAGMA foreign_keys = ON`
  (`app/db/connection.py:17`) a declared reference would turn every deletion of a message
  that has reports into a refusal — an operator surface breaking on an audit table. The
  ledger is the account of what the network said; it outlives the row it names.
- **`window_hours` and `strict` are recorded per row** because the flip decision (task 9.1)
  asks "how many contradictions did we record while the switch was off", and a setting read
  a week later cannot answer for a decision made before it changed.
- **`candidates` records every part whose reference matched**, each with its own outcome —
  not only the winner. "How many reports did we contradict" is unanswerable from a table
  that stores the choice and forgets the alternatives.
- **Retention** is a named constant with a default of 30 days — long enough that the switch
  is flipped against a full window of evidence — alongside `_INBOUND_SEEN_RETENTION`
  (`app/modem/manager.py:70`).
- **Pruning runs on the expiry sweep**, not where `prune_inbound_seen` is called.
  That one runs from `scan_inbox` (`app/modem/manager.py:823`), which fires at startup and
  on link recovery; a gateway that never loses its link would not prune this table for
  months.

### D3 — attribution: a filter chain that fails open, with the one closing rule behind a switch

Given a report `(mr, ra, tora, scts, st)`:

**Candidates** are the parts where `modem_ref = mr`, the owning message is `sent` or
`expired`, and the part's own `sent_at` is not older than
`delivery_report_max_age_hours`. A part whose `sent_at` is unknown counts as **inside** the
window — unknown is not old, and a NULL compared in SQL silently answers "does not
qualify", which is fail-closed in a design that must fail open.

Then, in order:

1. **Contradiction.** A candidate whose recipient differs from the report's `ra` is
   eliminated — *including when it is the only candidate*, which is the whole point.
2. **Nearness.** Where more than one candidate survives and `scts` parses, the candidate
   whose part `sent_at` is nearest to it wins.
3. **Recency.** Where the tie still stands, the most recently sent candidate wins. This is
   a guess. It is named as one, recorded as one in the ledger, and it carries a
   consequence: a report attributed by recency alone does not count toward the
   destination's blacklist, because an irreversible penalty must not rest on a tiebreak.

A candidate chosen — sole or selected — **is updated**; the obligation is positive, not
merely permitted, or an implementation that attributes nothing at all satisfies every rule.

**Attribution returns a decision, not a row.** The part, the outcome
(`attributed` / `superseded` / `unplaced`), the reason, and *how* it was chosen
(`sole` / `nearest` / `recency`) come out together, because three consumers read them and
each reads a different field: the ledger writes all of it, the alert fires on `unplaced`
alone, and `record_permanent_fail` must not fire on `recency`. A lookup that returns only a
row cannot carry that, and the blacklist rule would have a test and no mechanism.

**Three outcomes, one of which alerts.** A report whose reference matches a part of a
message already `delivered` or `failed` — or a part a report has already set — is
`superseded`: ordinary network behaviour, since a multipart message completed at the timeout
still receives its remaining reports. Recorded, silent. Only `unplaced` — nothing matched,
everything eliminated, or the sole match outside the window — notifies. The alert gets its
own toggle defaulting to **on** (reusing `notify_delivery_errors` would inherit its `False`
default and the guarantee would be empty on every existing install) and de-duplicates on the
report's reference, so a wrapped counter cannot turn one fault into a storm.

#### Comparing `ra` to a stored number

Not by canonicalizing. `app/phone.py:validate_and_normalize` needs a region and raises on
anything it dislikes, and both failure modes are wrong here: with `restrict_region=True` a
foreign `ra` raises and the rule silently switches itself off; with a national `ra` parsed
against our region, a foreign number can canonicalize into a *different valid* number and
eliminate the correct sole candidate. That is the regression this change exists to avoid,
arrived at through the safety mechanism.

Instead both sides are reduced to **significant digits**: strip every non-digit, take the
last ten (or all of them, if fewer), compare. `+79031680015`, `89031680015` and
`79031680015` all reduce to `9031680015`. The comparison cannot raise, needs no region, and
needs `tora` for nothing — which is why `tora` stays unused, deliberately rather than by
omission. `ra` is *usable* only when it holds at least ten digits; anything shorter,
empty, or absent eliminates nothing.

#### Parsing `scts`

`"26/04/17,12:00:01+12"` is `YY/MM/DD,hh:mm:ss` followed by a **quarter-hour** offset:
`+12` is UTC+03:00, not UTC+12:00. An implementation that treats it as hours is nine hours
out, and because a timestamp may only order candidates and never eliminate one, that error
would never surface as a failure — only as the wrong candidate chosen. An `scts` that does
not parse is treated as absent, never as epoch zero.

#### The switch

`delivery_report_strict_attribution` (bool, default **off** on first deploy). Off, a
contradiction is recorded in the ledger and the report is attributed as it would have been
before. On, a contradiction eliminates. Step 1 is the only rule in this change that can
refuse a delivery, so it is the only one that gets a switch — and the flip is a separate,
evidence-led decision (task 8.1), not part of the deploy.

#### Which write happens first

Each `queries.py` function commits on its own, so the two writes cannot be one transaction
without restructuring the layer. The status write goes first and the record second: an
attribution that happened and was not written down is a gap in the account, while a record
written for an attribution that then failed is a false account, and the account is what task
9.1 reads. A record that fails to write is logged and abandoned — it may not fail the report
it describes.

### D4 — the window bounds the search; it does not adjudicate

`delivery_report_max_age_hours`, positive integer, default **168** (seven days), re-read per
report, as `delivery_timeout_seconds` is re-read per sweep.

Its job is to stop an ancient `expired` message sitting in the candidate set for ever, not
to decide anything. A report that falls outside it is recorded in the ledger rather than
discarded, so the case D3 cannot reach — conclusive evidence about a message older than the
window — is preserved rather than thrown away.

**Open, and it wants live data.** Task 7.2 reads message 1749's actual dates; if the gap
that alert crossed is longer than a week, this default is wrong and changes before ship.

### D5 — the writes address the part, not the reference

`set_part_delivered` / `set_part_failed` currently say
`UPDATE message_parts SET status = … WHERE modem_ref = ?` — with no `LIMIT`, so the moment
the reference repeats they rewrite every historical part sharing that octet. They take
`(message_id, seq)`: the row attribution chose, addressed by its own identity.

### D6 — two vacuous truths, closed together

`message_parts_all_delivered` answers `True` for a message with no part rows at all
(`queries.py:286-292`). And `complete_partly_reported_messages` (`queries.py:593-635`)
promotes a message to `delivered` with `delivery_inferred = 1` when **any** part is
delivered and none failed — so a single misattributed positive report manufactures a
delivery for a message no report ever named. That is the worst consequence of the defect and
it is the one the original proposal missed.

Both are addressed as behaviour, not as function contracts: no message reaches `delivered`
— reported or inferred — unless at least one part record of *that message* was updated by a
report attributed to it.

## Migration

SQLite cannot replace a primary key in place, so `message_parts` is rebuilt. The naive
script is unsafe here in three separate ways, and all three are fixed together.

```sql
-- guard: has the rebuild already run? Test the PK SHAPE, not a column's presence.
--   sqlite_master.sql for message_parts contains 'PRIMARY KEY (message_id, seq)'
PRAGMA foreign_keys = OFF;
BEGIN IMMEDIATE;
DROP TABLE IF EXISTS message_parts_v2;          -- a previous crashed run leaves this behind
CREATE TABLE message_parts_v2 (
    message_id  INTEGER NOT NULL REFERENCES messages(id),
    seq         INTEGER NOT NULL,
    modem_ref   INTEGER NOT NULL,
    total       INTEGER NOT NULL,
    status      TEXT NOT NULL DEFAULT 'sent',
    sent_at     TIMESTAMP,
    PRIMARY KEY (message_id, seq)
);
INSERT INTO message_parts_v2 (message_id, seq, modem_ref, total, status, sent_at)
SELECT p.message_id, p.seq, p.modem_ref, p.total, p.status, m.sent_at
  FROM message_parts p JOIN messages m ON m.id = p.message_id
 WHERE p.rowid = (SELECT p2.rowid FROM message_parts p2        -- ONE WHOLE ROW per pair:
                   WHERE p2.message_id = p.message_id          -- the old key never enforced
                     AND p2.seq        = p.seq                 -- (message_id, seq)
                   ORDER BY (p2.status = 'sent') ASC,          -- a reported row first,
                            p2.rowid DESC                      -- then the later one
                   LIMIT 1);
DROP TABLE message_parts;                       -- takes its indexes with it
ALTER TABLE message_parts_v2 RENAME TO message_parts;
CREATE INDEX IF NOT EXISTS idx_message_parts_ref     ON message_parts(modem_ref);
CREATE INDEX IF NOT EXISTS idx_message_parts_message ON message_parts(message_id);
COMMIT;
PRAGMA foreign_keys = ON;
```

Both indexes are recreated **inside** the rebuild. The existing
`CREATE INDEX IF NOT EXISTS idx_message_parts_message` lives in the base script
(`app/db/migrate.py:98`), which has already run by this point; the `DROP` takes the index
with it and nothing would put it back until the next start. The reference index is new and
load-bearing: candidate lookup is a `modem_ref` scan over a table this change stops bounding
at 256 rows.

- **Atomic.** `run_migrations` uses `executescript` (`app/db/migrate.py:16`), which commits
  implicitly and leaves these steps unprotected. A kill between `DROP` and `RENAME` leaves
  no `message_parts`, and the base `CREATE TABLE IF NOT EXISTS` recreates the **old** shape
  empty on the next boot, whereupon the rebuild runs again, hits the existing
  `message_parts_v2`, and the service crash-loops with the part records gone. The rebuild
  therefore runs as its own explicit transaction, outside `executescript`.
- **Idempotent on the fact that changed.** The guard reads the stored DDL for the primary
  key, not the presence of `sent_at` — a column anyone can add with
  `_add_column_if_missing`, which would make the guard lie for ever.
- **One whole row per pair, never a blend, and never the unreported one.** A column-wise
  `GROUP BY` with `MAX()` per column assembles a row that never existed: `MAX(status)` under
  BINARY collation orders `'delivered' < 'failed' < 'sent'`, so a duplicated pair holding
  `delivered` and `sent` collapses to **`sent`** — a confirmed part downgraded to outstanding,
  which then feeds the sweep and turns a delivery into an expiry notification to the owning
  app. `MAX(modem_ref)` is worse than useless on a counter that wraps: larger is not later.

  ⚠️ **A bare `MAX(rowid)` loses the same row, and this was written as `MAX(rowid)` until the
  implementation tested it.** Picking a whole row stops the *blend*, not the *downgrade*: the
  duplicate arises when a segment is transmitted twice, so the later row is the second
  transmission and carries `sent`, while the report that confirmed the first arrived against
  the **earlier** row. Taking the latest row therefore discards the confirmation just as
  surely as `MAX(status)` does — a different mechanism reaching the identical harm the
  paragraph above rules out. The surviving row is chosen whole by an ordering that prefers a
  row a report actually reached, latest first within that: `ORDER BY (status = 'sent') ASC,
  rowid DESC`. Task 3.7 is the test, and it inserts the confirmed row **first** so that a
  `MAX(rowid)` implementation fails it.
- **Tolerant of legacy data**, because the old schema keyed on
  `modem_ref` and never constrained the pair. The send path is not *expected* to produce a
  duplicate — `is_retryable(..., already_sent=…)` (`app/modem/errors.py:79`) refuses a retry
  once any part has been accepted, which is also why a plain `INSERT` on the new key is safe
  going forward and a conflict there is a fault worth raising rather than resolving. But a
  migration that bets startup on an invariant the old schema never enforced is the wrong
  bet.
- **The base DDL is replaced, not left behind.** `migrate.py:90-96` still declares
  `modem_ref INTEGER PRIMARY KEY`. It becomes the new shape, so a fresh install does not
  create the defect and immediately rebuild it, and so the repository has one schema rather
  than two. ⚠️ Because the guard reads the stored DDL, the base statement must be written so
  that the guard **matches what SQLite stores for it** — otherwise a fresh install rebuilds
  the table on every single start and nothing about that is visible. A test on the empty-
  database path is what holds this, not care.
- **`PRAGMA foreign_keys`** is on (`app/db/connection.py:17`) and is disabled around the
  rebuild, as the documented SQLite procedure requires. Nothing references `message_parts`,
  and the `JOIN` keeps the new reference valid regardless.
- **Orphan part rows are dropped** by the `JOIN` — parts whose message is gone are
  unattributable by definition, and carrying them forward would feed them back into the
  candidate set.
- **`sent_at` is backfilled from the message** — approximate for a second segment, and
  honest: a per-segment submit time was never recorded. Unknown is treated as inside the
  window (D3), so the approximation cannot silently exclude anything.
- **No expand/contract phase.** One process owns this file and the migration runs at startup
  before any reader — that is a concurrency argument, not an atomicity one, which is why the
  transaction above is needed as well.
- **Back-out is a restore, and a restore is data loss** — every message and inbound SMS
  since the backup. Acceptable at this volume, and stated rather than dressed up as a
  rollback.

## Risks / Trade-offs

- **Dropping a report is not neutral.** For a message still in `sent`, "no status changes"
  lasts until `expire_stale_messages` moves it to `expired` and `delivery-dispatch` POSTs
  that to the owning app. The trade is not "delivered or nothing", it is "delivered or
  expired", and for a negative report it is also a suppressed blacklist increment and a
  suppressed operator alert. This is why a drop raises an operator notification rather than
  a log line, and why step 1 ships switched off.
- **A network whose `ra` never matches our stored form** would have its reports dropped in
  strict mode. Mitigated by digit comparison rather than canonicalization, by the ledger
  recording every contradiction before the switch is flipped, and by the switch existing.
- **`message_parts` grows unbounded** — one row per segment instead of at most 256 in total.
  Thousands of rows in a file that already holds message texts. `delete_message` removes a
  message's parts; the ledger is pruned on its own retention.
- **The window can be set too short** and start bounding out reports the network is still
  entitled to send. Positive integer, generous default, and the ledger keeps what it bounds.
