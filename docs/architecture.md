# SMS Gate — Architecture

## Overview

An HTTP service running on an Ubuntu server with a Quectel EP06E LTE modem. It accepts SMS-sending requests (authorization codes) from multiple client applications, delivers them via AT commands, stores the history, and tracks delivery status.

## System Diagram

```
┌──────────────┐     HTTP :80      ┌──────────────┐    AT commands    ┌─────────┐
│  sp_bot      │───────────────────│              │──────────────────│         │
│  rk_bot      │   POST /sms/send │   SMS Gate   │  /dev/ttyUSB*   │  EP06E  │
│  gm_bot      │◄──────────────────│   (FastAPI)  │◄─────────────────│  Modem  │
│  ...         │   GET /sms/{id}   │              │  +CDS (delivery)│         │
└──────────────┘                   └──────┬───────┘                 └─────────┘
                                          │
                                   ┌──────┴───────┐
                                   │   SQLite     │
                                   │   sms.db     │
                                   └──────────────┘
```

## Technology Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Language | Python 3.12+ | pyserial mature, FastAPI async, widely known |
| Framework | FastAPI | Async, auto-docs (Swagger), Pydantic validation |
| Database | SQLite (WAL mode) | Sufficient for tens of SMS/day, zero config |
| Modem comms | pyserial + AT commands | Direct control, delivery report support |
| Process mgmt | systemd | Native, reliable, auto-restart |

## Components

### 1. API Server (`app/api/`)
FastAPI application. Handles HTTP requests, validates input, authenticates clients, writes to DB, enqueues messages for sending.

### 2. Modem Manager (`app/modem/`)
Singleton that owns the serial port connection. Two responsibilities:
- **Sender**: takes messages from an asyncio queue, sends via AT+CMGS, records message reference
- **Reader**: background task that continuously reads the serial port for unsolicited responses (+CDS delivery reports), updates message status in DB

### 3. Database (`app/db/`)
SQLite via aiosqlite. WAL mode enabled for concurrent read/write. Simple migration on startup.

### 4. Auth (`app/auth/`)
Bearer token authentication. Each client app has a unique token. Middleware extracts token from `Authorization` header, resolves to app_id.

### 5. Phone Validation (`app/phone.py`)
Phone numbers are validated with the [`phonenumbers`](https://github.com/daviddrysdale/python-phonenumbers) library and normalized to E.164 on ingress.  The validation region is controlled by the `phone_region` soft setting (default `RU`, editable at `/admin/settings`).

**Operator / region enrichment** is performed via [voxlink](https://num.voxlink.ru/) (`num.voxlink.ru`) and is **RF-only**: the lookup is gated to `+7` numbers.  Numbers from other countries are accepted and sent normally but will have empty `operator` and `region` fields.  Contributions adding enrichment for non-RF numbers (e.g. using `phonenumbers.carrier` / `phonenumbers.geocoder` as a best-effort fallback) are welcome.
