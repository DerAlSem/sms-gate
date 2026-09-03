# SMS Gate — Database Schema

SQLite database file: `data/sms.db` (relative to project root on server).

Enable WAL mode on first connection:
```sql
PRAGMA journal_mode=WAL;
```

---

## Table: apps

Client applications that are allowed to send SMS.

```sql
CREATE TABLE apps (
    id          TEXT PRIMARY KEY,        -- 'my_bot', 'another_app'
    token       TEXT UNIQUE NOT NULL,    -- Bearer token for auth
    description TEXT,                    -- Human-readable name
    is_active   BOOLEAN DEFAULT 1,      -- 0 = disabled, rejects requests
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Seed data example

Apps are created and managed via the admin UI at `/admin/apps`. Direct INSERT also works:

```sql
INSERT INTO apps (id, token, description) VALUES
  ('my_bot',      'tok_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', 'My Bot'),
  ('another_app', 'tok_yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy', 'Another App');
```

Token format recommendation: `tok_{32 random hex chars}`.
Generate with: `python -c "import secrets; print('tok_' + secrets.token_hex(16))"`

---

## Table: messages

All SMS requests and their lifecycle.

```sql
CREATE TABLE messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    app_id       TEXT NOT NULL REFERENCES apps(id),
    phone        TEXT NOT NULL,           -- '+79991234567'
    text         TEXT NOT NULL,           -- SMS body
    status       TEXT NOT NULL DEFAULT 'pending',
                                          -- pending|sent|delivered|failed|expired
    modem_ref    INTEGER,                 -- first part's AT+CMGS ref (per-part refs live in message_parts)
    sent_at      TIMESTAMP,              -- when modem accepted the message
    delivered_at TIMESTAMP,              -- when +CDS delivery report received
    error        TEXT,                    -- error description if failed
    resent_from  INTEGER REFERENCES messages(id),
                                          -- set when this row is an admin re-send of a
                                          -- failed/expired message; carries the original's
                                          -- id so the owning app can attribute the outcome
                                          -- (surfaces as `resent_from` in delivery webhooks)
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_messages_app_id    ON messages(app_id);
CREATE INDEX idx_messages_status    ON messages(status);
CREATE INDEX idx_messages_modem_ref ON messages(modem_ref);
CREATE INDEX idx_messages_phone     ON messages(phone);
```

---

## Status Lifecycle

```
POST /sms/send
     │
     ▼
  pending ──── modem sends ────► sent ──── +CDS received ────► delivered
     │                            │
     │                            ├── no +CDS in timeout ──────► expired
     │                            │
     └── modem error ────────────►└── AT error ──────────────► failed
```

---

## Table: bad_numbers

Phones that have accumulated delivery failures and may be blocked from future sends.

```sql
CREATE TABLE bad_numbers (
    phone        TEXT PRIMARY KEY,
    fail_count   INTEGER NOT NULL DEFAULT 0,
    blocked_at   TIMESTAMP,
    last_error   TEXT,
    last_fail_at TIMESTAMP,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

The blacklist threshold (fail count before blocking) is configured via the `settings` table.

---

## Table: inbound_messages

Fully assembled inbound SMS received from the modem.

```sql
CREATE TABLE inbound_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    phone       TEXT NOT NULL,
    text        TEXT NOT NULL,
    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_inbound_phone ON inbound_messages(phone);
```

---

## Table: inbound_parts

Partial segments of multipart (concatenated) inbound SMS, held until all parts arrive.

```sql
CREATE TABLE inbound_parts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    phone       TEXT NOT NULL,
    ref         INTEGER NOT NULL,   -- concatenation reference number from PDU
    total       INTEGER NOT NULL,   -- total number of parts
    seq         INTEGER NOT NULL,   -- this part's sequence number (1-based)
    text        TEXT NOT NULL,
    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(phone, ref, total, seq)
);
```

Once all `total` parts for a `(phone, ref, total)` group are present they are assembled, written to `inbound_messages`, and the parts are deleted.

---

## Table: message_parts

Per-part tracking for outbound multipart (UDH-concatenated) SMS. One row per
segment; a message is marked `delivered` only when every part's `+CDS` report
arrives. For a single-part SMS there is exactly one row.

A part is identified by its message and its segment number — the only two facts
the gateway owns at send time. `modem_ref` is an ordinary indexed column that
repeats.

```sql
CREATE TABLE message_parts (
    message_id  INTEGER NOT NULL REFERENCES messages(id),
    seq         INTEGER NOT NULL,         -- this part's 1-based sequence number
    modem_ref   INTEGER NOT NULL,         -- TP-MR returned by AT+CMGS for this part
    total       INTEGER NOT NULL,         -- total number of parts
    status      TEXT NOT NULL DEFAULT 'sent',  -- sent|delivered|failed
    sent_at     TIMESTAMP,                -- when THIS segment was accepted
    PRIMARY KEY (message_id, seq)
);

CREATE INDEX idx_message_parts_message ON message_parts(message_id);
CREATE INDEX idx_message_parts_ref     ON message_parts(modem_ref);
```

`modem_ref` was the primary key until 0.18.0, and parts were written with
`INSERT OR REPLACE`. The whole table could therefore never hold more than 256
rows: every 257th send overwrote the record of whichever message had used that
reference before, and that message lost every trace of what it put on the wire.
The upgrade rebuilds the table, keeping one whole row per `(message_id, seq)`
and backfilling `sent_at` from the message.

---

## Table: delivery_reports

Every `+CDS` line the gateway reads, recorded before anything is decided on it.
Append-only, evidence rather than a queue: there is no operation that applies a
recorded report after the fact.

```sql
CREATE TABLE delivery_reports (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    raw_line      TEXT NOT NULL,   -- all an unreadable report still has
    modem_ref     INTEGER,         -- everything below is nullable by design
    recipient     TEXT,            -- `ra`, the address the report names
    submitted_at  TIMESTAMP,       -- `scts`, resolved to UTC
    discharged_at TIMESTAMP,       -- `dt`
    status_code   INTEGER,         -- `st`
    outcome       TEXT NOT NULL,   -- see below
    reason        TEXT,
    decided_by    TEXT,            -- sole | nearest | recency
    message_id    INTEGER,         -- NOT a foreign key; see below
    seq           INTEGER,
    candidates    TEXT,            -- JSON: every part whose reference matched
    window_hours  INTEGER,         -- the settings the decision was made under
    strict        INTEGER
);

CREATE INDEX idx_delivery_reports_at  ON delivery_reports(received_at);
CREATE INDEX idx_delivery_reports_ref ON delivery_reports(modem_ref);
```

Outcomes: `attributed` (a part was chosen and updated), `superseded` (the
reference matched a part already reported, or one whose message is already
finished — ordinary network behaviour, silent), `unplaced` (nothing matched,
every candidate was eliminated, or the only match fell outside the window — this
is the one that notifies an operator), `unparsable` (the parser could not read
the line), `unprocessable` (it parsed and handling it raised).

`message_id` is deliberately **not** a foreign key. `PRAGMA foreign_keys` is on,
and a declared reference would make deleting a message that has reports fail —
an operator surface breaking on an audit table. These rows are the account of
what the network said; they outlive the message they name and are removed by
their own 30-day retention, pruned on the expiry sweep.

Useful queries while deciding whether to turn `delivery_report_strict_attribution`
on:

```sql
-- how the last week's reports came out
SELECT outcome, COUNT(*) FROM delivery_reports
 WHERE received_at > datetime('now', '-7 days') GROUP BY outcome;

-- contradictions recorded while the switch was off: is it a real
-- misattribution, or a difference in our own formatting?
SELECT received_at, modem_ref, recipient, candidates FROM delivery_reports
 WHERE strict = 0 AND candidates LIKE '%"contradicted": true%'
 ORDER BY received_at DESC;

-- attributions that rest on a tiebreak (these never touch the blacklist)
SELECT COUNT(*) FROM delivery_reports WHERE decided_by = 'recency';
```

---

## Table: phone_ranges

Operator/region data keyed by 6-digit phone prefix (used for bulk lookup).

```sql
CREATE TABLE phone_ranges (
    prefix6      TEXT PRIMARY KEY,
    allocated    INTEGER NOT NULL,
    operator     TEXT,
    region       TEXT,
    operator_inn TEXT,
    checked_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## Table: number_operators

Per-number operator/region cache (individual lookups, takes precedence over `phone_ranges`).

```sql
CREATE TABLE number_operators (
    phone      TEXT PRIMARY KEY,
    operator   TEXT,
    region     TEXT,
    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## Table: settings

DB-backed runtime configuration. Seeded from environment variables on first start and editable via the admin UI at `/admin/settings`.

```sql
CREATE TABLE settings (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Known keys:

| key | description |
|-----|-------------|
| `voxlink_*` | Voxlink API credentials/endpoint |
| `alerting_*` | Telegram alerting config (bot token, chat id, etc.) |
| `inbound_dispatch_*` | Inbound SMS forwarding targets |
| `blacklist_threshold` | Fail count before a number is blocked |
| `delivery_timeout` | Seconds to wait for `+CDS` before marking `expired` |
| `phone_region` | Default phone region for number parsing |

Values are always stored as `TEXT`; the application layer handles type conversion.

---

## Notes

- `messages.modem_ref` is the integer returned by `AT+CMGS` for the message's first part. It is written on send and read by nothing; delivery reports are matched against `message_parts`, not against this column.
- `modem_ref` values cycle 0–255 and repeat roughly every three weeks at this volume, so a reference alone does not identify a message. A report is attributed by reference **plus** the recipient address it carries, the service-centre timestamp of the original submit, and the age of the part — see `app/modem/attribution.py`.
- All tables are created with `CREATE TABLE IF NOT EXISTS` for idempotent startup migrations.
- An internal `admin` app row is inserted on first start (with `is_active = 0`) for UI reply tracking; it cannot send SMS.
