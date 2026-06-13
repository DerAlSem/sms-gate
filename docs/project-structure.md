# SMS Gate — Project Structure

```
sms-gate/
├── docs/                       # This documentation
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app, lifespan (startup/shutdown)
│   ├── config.py               # Bootstrap/infra settings from env/.env
│   ├── settings_store.py       # DB-backed runtime settings store (SettingsStore)
│   ├── alerting.py             # Telegram alerting (setup, reconfigure, send)
│   ├── phone.py                # phonenumbers validation/normalization helpers
│   ├── api/
│   │   ├── __init__.py
│   │   ├── router.py           # POST /sms/send, GET /sms/{id}
│   │   ├── schemas.py          # Pydantic models (request/response)
│   │   └── dependencies.py     # Auth dependency (Bearer token → app_id)
│   ├── admin/
│   │   ├── __init__.py
│   │   ├── router.py           # Admin UI routes (/admin/*)
│   │   ├── i18n.py             # gettext/Babel bilingual rendering (RU/EN)
│   │   ├── timefmt.py          # Locale-aware time formatting helpers
│   │   ├── templates/          # Jinja2 HTML templates
│   │   │   ├── base.html
│   │   │   ├── messages.html
│   │   │   ├── apps.html
│   │   │   ├── settings.html
│   │   │   ├── blacklist.html
│   │   │   ├── inbound.html
│   │   │   ├── stats.html
│   │   │   ├── ranges.html
│   │   │   ├── dialog.html
│   │   │   └── dialogs.html
│   │   └── translations/       # gettext catalogs
│   │       ├── ru/LC_MESSAGES/messages.po
│   │       └── en/LC_MESSAGES/messages.po
│   ├── db/
│   │   ├── __init__.py
│   │   ├── connection.py       # aiosqlite connection, WAL mode
│   │   ├── migrate.py          # Schema migrations on startup
│   │   └── queries.py          # CRUD functions for messages and apps
│   ├── lookup/
│   │   ├── __init__.py
│   │   ├── operator.py         # Operator/region lookup orchestration
│   │   ├── voxlink.py          # Voxlink HTTP lookup client
│   │   └── backfill.py         # Background backfill of operator data
│   └── modem/
│       ├── __init__.py
│       ├── manager.py          # ModemManager: loops (sender, reader, inbound, expire, keepalive, parts_flush)
│       ├── at_commands.py      # Low-level AT command send/receive
│       ├── parser.py           # Parse +CDS, +CMGS, +CMT responses
│       ├── pdu.py              # PDU encode/decode (SMS-SUBMIT / SMS-DELIVER)
│       ├── assembler.py        # Multipart SMS reassembly
│       └── dispatch.py         # Inbound webhook dispatch
├── tests/
│   ├── conftest.py
│   └── test_*.py               # ~30 test modules (pytest)
├── data/                       # SQLite DB lives here (gitignored)
│   └── .gitkeep
├── deploy/
│   ├── sms-gate.service        # systemd unit file
│   └── post-receive            # git hook for deploy
├── .env.example                # Template for bootstrap env vars
├── requirements.txt
└── README.md
```

---

## Configuration

Settings are split into two layers:

### Bootstrap / infra — `config.py`

Read once at startup from environment variables or `.env` via `pydantic-settings`.
These are infra-level values that cannot be changed at runtime without a restart:

```python
class Settings(BaseSettings):
    # Modem / serial
    serial_send_port: str = "/dev/ttyUSB2"
    serial_read_port: str = "/dev/ttyUSB3"
    serial_baudrate: int = 115200

    # Database
    db_path: str = "data/sms.db"

    # Server
    host: str = "0.0.0.0"
    port: int = 80

    # Admin UI credentials (kept in env to avoid lockout)
    admin_user: str = "admin"
    admin_password: str = "change-me"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
```

Minimal `.env` bootstrap:

```env
SERIAL_SEND_PORT=/dev/ttyUSB2
SERIAL_READ_PORT=/dev/ttyUSB3
ADMIN_USER=admin
ADMIN_PASSWORD=secret
```

### Runtime settings — `settings_store.py`

All "soft" settings live in the `settings` table and are managed through the admin UI at `/admin/settings`. They are loaded at startup via `SettingsStore.load()` and can be changed live without restart. Categories:

| Section | Keys |
|---|---|
| Voxlink | `voxlink_enabled`, `voxlink_url`, `voxlink_timeout`, `voxlink_cache_ttl_days` |
| Alerting | `alert_bot_token`, `alert_chat_id`, `alert_dedup_window` |
| Inbound dispatch | `inbound_dispatch` (JSON list), `inbound_dispatch_retries`, `inbound_dispatch_timeout` |
| Limits | `blacklist_threshold`, `delivery_timeout_seconds` |
| Sending | `phone_region` |

`SettingsStore` provides synchronous typed getters from an in-memory cache; `set_many()` writes to the DB and fires section change-hooks (e.g. to reconfigure alerting without restart).

On first startup, `seed_from_env()` seeds DB rows from matching env vars (uppercase key names), falling back to code defaults. Existing rows are never overwritten.

---

## Dependencies (requirements.txt)

```
fastapi==0.115.*
uvicorn[standard]==0.34.*
aiosqlite==0.20.*
pyserial==3.5.*
pyserial-asyncio==0.6.*
pydantic-settings==2.7.*
phonenumbers
babel
```

---

## App Lifespan (main.py)

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db(settings.db_path)
    await run_migrations()
    await seed_from_env()          # Seed runtime settings from env on first boot
    await store.load()             # Load runtime settings into memory
    setup_telegram_alerts(store)
    store.on_change("Alerting", lambda: reconfigure(store))

    await modem_manager.connect()
    await modem_manager.scan_inbox()

    tasks = [
        asyncio.create_task(modem_manager.sender_loop()),
        asyncio.create_task(modem_manager.reader_loop()),
        asyncio.create_task(modem_manager.inbound_loop()),
        asyncio.create_task(modem_manager.expire_loop()),
        asyncio.create_task(modem_manager.keepalive_loop()),
        asyncio.create_task(modem_manager.parts_flush_loop()),
    ]
    yield

    # Shutdown
    for task in tasks: task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await modem_manager.disconnect()
    await close_db()
```

---

## Request Flow

```
1. Client sends POST /sms/send with Bearer token
2. dependencies.py: extract token → lookup in apps table → get app_id
3. schemas.py: validate phone (via phone.py / phonenumbers), text length
4. queries.py: INSERT into messages (status=pending), return id
5. Put message_id into asyncio.Queue
6. Return {"id": 42, "status": "pending"} to client
7. ModemManager sender_loop picks from queue:
   a. Encode as PDU (pdu.py), send via AT+CMGS
   b. Parse +CMGS ref number
   c. UPDATE messages SET status=sent, modem_ref=ref
8. reader_loop gets +CDS delivery report:
   a. Parse message reference and status
   b. UPDATE messages SET status=delivered/failed
9. inbound_loop gets +CMT (incoming SMS):
   a. PDU-decode, reassemble multipart (assembler.py)
   b. Dispatch to configured webhooks (dispatch.py)
```
