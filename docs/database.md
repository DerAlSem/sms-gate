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
    modem_ref    INTEGER,                 -- AT+CMGS message reference number
    sent_at      TIMESTAMP,              -- when modem accepted the message
    delivered_at TIMESTAMP,              -- when +CDS delivery report received
    error        TEXT,                    -- error description if failed
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

- `modem_ref` is the integer returned by `AT+CMGS` after successful send. It is used to match incoming `+CDS` delivery reports to the correct message.
- `modem_ref` values cycle 0–255, so matching should also consider timing (most recent `sent` message with that ref).
- All tables are created with `CREATE TABLE IF NOT EXISTS` for idempotent startup migrations.
- An internal `admin` app row is inserted on first start (with `is_active = 0`) for UI reply tracking; it cannot send SMS.
