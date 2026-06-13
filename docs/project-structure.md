# SMS Gate — Project Structure

```
sms-gate/
├── docs/                       # This documentation
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app, lifespan (startup/shutdown)
│   ├── config.py               # Settings from env vars / .env file
│   ├── api/
│   │   ├── __init__.py
│   │   ├── router.py           # POST /sms/send, GET /sms/{id}
│   │   ├── schemas.py          # Pydantic models (request/response)
│   │   └── dependencies.py     # Auth dependency (Bearer token → app_id)
│   ├── db/
│   │   ├── __init__.py
│   │   ├── connection.py       # aiosqlite connection, WAL mode
│   │   ├── migrate.py          # CREATE TABLE IF NOT EXISTS on startup
│   │   └── queries.py          # CRUD functions for messages and apps
│   └── modem/
│       ├── __init__.py
│       ├── manager.py          # ModemManager: init, send, background reader
│       ├── at_commands.py      # Low-level AT command send/receive
│       └── parser.py           # Parse +CDS, +CMGS responses
├── data/                       # SQLite DB lives here (gitignored)
│   └── .gitkeep
├── deploy/
│   ├── sms-gate.service        # systemd unit file
│   └── post-receive            # git hook for deploy
├── .env.example                # Template for env vars
├── requirements.txt
└── README.md
```

---

## Configuration (config.py)

Read from environment variables (or `.env` file via `pydantic-settings`):

```python
class Settings(BaseSettings):
    # Modem
    serial_port: str = "/dev/ttyUSB2"
    serial_baudrate: int = 115200

    # Database
    db_path: str = "data/sms.db"

    # Delivery report
    delivery_timeout_seconds: int = 300  # 5 minutes

    # Server
    host: str = "0.0.0.0"
    port: int = 80

    model_config = SettingsConfigDict(env_file=".env")
```

### .env.example

```env
SERIAL_PORT=/dev/ttyUSB2
SERIAL_BAUDRATE=115200
DB_PATH=data/sms.db
DELIVERY_TIMEOUT_SECONDS=300
HOST=0.0.0.0
PORT=80
```

---

## Dependencies (requirements.txt)

```
fastapi==0.115.*
uvicorn[standard]==0.34.*
aiosqlite==0.20.*
pyserial==3.5.*
pyserial-asyncio==0.6.*
pydantic-settings==2.7.*
```

---

## App Lifespan (main.py)

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()                    # Run migrations
    await modem_manager.connect()      # Open serial, send init AT commands
    asyncio.create_task(
        modem_manager.reader_loop()    # Background delivery report reader
    )
    asyncio.create_task(
        expire_stale_messages()        # Periodic: mark old 'sent' as 'expired'
    )
    yield
    # Shutdown
    await modem_manager.disconnect()

app = FastAPI(title="SMS Gate", lifespan=lifespan)
app.include_router(sms_router)
```

---

## Request Flow

```
1. Client sends POST /sms/send with Bearer token
2. dependencies.py: extract token → lookup in apps table → get app_id
3. schemas.py: validate phone format, text length
4. queries.py: INSERT into messages (status=pending), return id
5. Put message_id into asyncio.Queue
6. Return {"id": 42, "status": "pending"} to client
7. ModemManager sender picks from queue:
   a. AT+CMGS → send SMS
   b. Parse +CMGS ref number
   c. UPDATE messages SET status=sent, modem_ref=ref
8. Later, serial reader gets +CDS:
   a. Parse message reference and status
   b. UPDATE messages SET status=delivered/failed
```
