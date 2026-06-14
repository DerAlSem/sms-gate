# SMS Gate

[![CI](https://github.com/DerAlSem/sms-gate/actions/workflows/ci.yml/badge.svg)](https://github.com/DerAlSem/sms-gate/actions/workflows/ci.yml)

**Self-hosted SMS that doesn't bleed money.** Send your one-time codes through a cheap
USB LTE modem and a regular SIM instead of renting delivery from an aggregator per message.

Commercial SMS providers charge **~5–80 ₽ _per message_** — fine for dozens, brutal at
volume. A consumer SIM with an unlimited-SMS plan is a flat **~100 ₽/month**. Send 100
codes a month or 100 000 — your bill doesn't move, so your per-message cost collapses
toward zero _(your savings → ∞ 😉)_. Your numbers and message history stay on **your own
server** — no third party in the loop.

A small, self-hosted HTTP gateway for sending and receiving SMS through an LTE
modem (built for a **Quectel EP06E / EM06**, but any AT-command modem exposing
serial ports should work). Client apps POST a phone number and text; the gateway
sends the message via AT commands, tracks delivery reports, stores history in
SQLite, and exposes a small admin web UI.

It was built to send one-time authorization codes from several bots through a
single SIM, so it is deliberately simple: one process, one SQLite file, systemd
for supervision. No external broker, no container required.

## Features

- **HTTP API** — `POST /sms/send`, `GET /sms/{id}`, Bearer-token auth per client app
- **Outbound Cyrillic & multipart** — sends in PDU mode with automatic GSM 7-bit/UCS2 encoding; long messages are split into UDH-concatenated parts and reassembled as one message on the recipient's phone
- **Delivery tracking** — parses `+CDS` delivery reports; marks messages
  `pending → sent → delivered/failed`, expires stale ones
- **Inbound SMS** — decodes PDU-mode messages (incl. UCS2 and multipart reassembly),
  optionally dispatches them to a webhook by first-word prefix
- **Configurable phone validation** — the accepted country is a runtime setting
  (`phone_region`, default `RU`) edited in the admin UI; numbers are validated with
  the [`phonenumbers`](https://github.com/daviddrysdale/python-phonenumbers) library
  and normalized to E.164
- **Auto-blacklist** — numbers with repeated permanent failures are blocked until
  an operator clears them
- **Operator/region lookup** — enriches numbers via voxlink, **RF-only** (`+7`
  numbers). Non-`+7` numbers are sent normally but get no operator/region data;
  PRs adding best-effort enrichment for other countries (e.g. via
  `phonenumbers.carrier` / `phonenumbers.geocoder`) are welcome
- **Bilingual admin UI** (Russian default + English, switchable) — messages, dialogs,
  inbound, blacklist, number ranges, daily stats, runtime **settings**, and client
  **token management**
- **Telegram alerting** — service crashes and failover events ping a Telegram chat
- **Tests** — `pytest` suite covering PDU parsing, assembly, alerting, lookup, stats,
  settings, phone validation, and the admin pages

## Screenshots

The admin UI is bilingual (Russian default, English switchable). _(Sample data below.)_

| Outbound messages | Dialog (chat) view |
|---|---|
| ![Outbound messages](docs/img/messages.png) | ![Dialog view](docs/img/dialog.png) |

| Runtime settings (country picker, no `.env` edits) | Client app tokens |
|---|---|
| ![Settings](docs/img/settings.png) | ![Apps](docs/img/apps.png) |

## Architecture

```
┌──────────────┐   HTTP POST /sms/send   ┌──────────────┐   AT commands   ┌─────────┐
│ client apps  │────────────────────────▶│   SMS Gate   │────────────────▶│  LTE    │
│ (bots, etc.) │◀────────────────────────│  (FastAPI)   │◀────────────────│  modem  │
└──────────────┘   GET /sms/{id}          └──────┬───────┘   +CDS reports  └─────────┘
                                                 │
                                          ┌──────┴───────┐
                                          │ SQLite (WAL) │
                                          └──────────────┘
```

- **API** (`app/api/`) — request validation, auth, enqueue
- **Modem manager** (`app/modem/`) — owns the serial port; a sender drains an
  asyncio queue, a reader loop consumes unsolicited responses (delivery reports,
  inbound PDUs)
- **DB** (`app/db/`) — aiosqlite, WAL mode, migrate-on-startup
- **Settings** (`app/settings_store.py`) — DB-backed runtime config, edited in the admin UI
- **Admin** (`app/admin/`) — Jinja2 templates (i18n via gettext/Babel) behind HTTP Basic auth

See [`docs/`](docs/) for more details (`architecture.md`, `database.md`,
`modem.md`, `api.md`, `deployment.md`, `i18n.md`).

## Requirements

- Python 3.12+
- An AT-command-capable modem exposing serial ports (e.g. `/dev/ttyUSB2`/`/dev/ttyUSB3`)
- Linux (developed/deployed on Ubuntu with systemd)

## Quick start

```bash
git clone <your-fork-url> sms-gate
cd sms-gate

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env — at minimum set ADMIN_PASSWORD and your SERIAL_* ports

uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The database and tables are created automatically on first start. Interactive API
docs are available at `http://localhost:8000/docs`, the admin UI at `/admin`.

### Registering a client app / token

Create client apps and their tokens in the admin UI at **`/admin/apps`** (the token is
shown once on creation). Or insert one directly:

```bash
sqlite3 data/sms.db "INSERT INTO apps (id, token, description, is_active) VALUES ('my_bot', 'some-long-random-token', 'my bot', 1);"
```

### Sending a message

```bash
curl -X POST http://localhost:8000/sms/send \
  -H "Authorization: Bearer some-long-random-token" \
  -H "Content-Type: application/json" \
  -d '{"phone": "+79991234567", "text": "MyApp: 4821"}'
```

> The accepted country is set by `phone_region` (default `RU`) at `/admin/settings`.
> National-format numbers are accepted and normalized to E.164; numbers from other
> countries are rejected unless they match the configured region.

## Configuration

**Bootstrap/infra** config is read from environment variables or a `.env` file (via
`pydantic-settings`) — see [`.env.example`](.env.example):

| Variable | Default | Notes |
|----------|---------|-------|
| `SERIAL_SEND_PORT` / `SERIAL_READ_PORT` | `/dev/ttyUSB2` / `/dev/ttyUSB3` | Modem serial ports |
| `DB_PATH` | `data/sms.db` | SQLite file |
| `HOST` / `PORT` | `0.0.0.0` / `80` | uvicorn bind |
| `ADMIN_USER` / `ADMIN_PASSWORD` | `admin` / `change-me` | **Change before exposing!** |

**Runtime settings** — voxlink lookup, Telegram alerting, inbound-dispatch rules,
blacklist threshold, delivery timeout, and `phone_region` — live in the database and are
edited at **`/admin/settings`** (no restart needed). On first start they are seeded once
from any matching env vars, then managed in the DB. Client tokens are managed at
**`/admin/apps`**.

## Running tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Deployment

A systemd-based deployment (git push-to-deploy, unit files, Telegram notifier, and
an optional LTE failover backup channel) is described in
[`docs/deployment.md`](docs/deployment.md) and [`deploy/`](deploy/). Paths in those
files (`/opt/sms-gate`, ports, hostnames) are examples — adapt them to your host.

## License

[MIT](LICENSE)
