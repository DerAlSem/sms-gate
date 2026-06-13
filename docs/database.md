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
    id          TEXT PRIMARY KEY,        -- 'sp_bot', 'rk_bot', 'gm_bot'
    token       TEXT UNIQUE NOT NULL,    -- Bearer token for auth
    description TEXT,                    -- Human-readable name
    is_active   BOOLEAN DEFAULT 1,      -- 0 = disabled, rejects requests
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Seed data example

```sql
INSERT INTO apps (id, token, description) VALUES
  ('sp_bot', 'tok_sp_xxxxxxxxxxxx', 'SP Bot'),
  ('rk_bot', 'tok_rk_xxxxxxxxxxxx', 'RK Bot'),
  ('gm_bot', 'tok_gm_xxxxxxxxxxxx', 'GM Bot');
```

Token format recommendation: `tok_{app_id}_{32 random hex chars}`.
Generate with: `python -c "import secrets; print('tok_sp_' + secrets.token_hex(16))"`

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

CREATE INDEX idx_messages_app_id ON messages(app_id);
CREATE INDEX idx_messages_status ON messages(status);
CREATE INDEX idx_messages_modem_ref ON messages(modem_ref);
```

---

## Status Lifecycle

```
POST /sms/send
     │
     ▼
  pending ──── modem sends ────► sent ──── +CDS received ────► delivered
     │                            │
     │                            ├── no +CDS in 5 min ──────► expired
     │                            │
     └── modem error ────────────►└── AT error ──────────────► failed
```

---

## Notes

- `modem_ref` is the integer returned by `AT+CMGS` after successful send. It's used to match incoming `+CDS` delivery reports to the correct message.
- `modem_ref` values cycle 0-255, so matching should also consider timing (most recent pending `sent` message with that ref).
- Run migration on app startup. Use `CREATE TABLE IF NOT EXISTS` for idempotency.
