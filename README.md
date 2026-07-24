# SMS Gate

> 🇷🇺 Документация на русском. **English version below ↓** — [jump to English](#english)

<!-- Russian translation: SAME headings/sections/tables/order as the English original -->

[![CI](https://github.com/DerAlSem/sms-gate/actions/workflows/ci.yml/badge.svg)](https://github.com/DerAlSem/sms-gate/actions/workflows/ci.yml)

**Свой собственный SMS-шлюз за 100 рублей в месяц.** Вам понадобится дешёвый USB-модем LTE и обычная SIM-карта с подходящим тарифом.

Коммерческие SMS-провайдеры берут **~5–80 ₽ _за сообщение_** — терпимо на десятках,
разорительно на объёме. Обычная SIM-карта с безлимитом на SMS стоит фиксированные
**~100 ₽/месяц**. Отправляете 100 кодов в месяц или 100 000 — счёт не меняется, а
цена за сообщение стремится к нулю _(а экономия → ∞ 😉)_. Ваши номера и история
сообщений остаются на **вашем собственном сервере** — без посредников.

Небольшой HTTP-шлюз для сервера: отправляет и принимает SMS через
LTE-модем (собран под **Quectel EP06E / EM06**, но должен работать с любым
AT-модемом, у которого есть последовательные порты). Клиентские приложения шлют
POST с номером и текстом; шлюз отправляет сообщение через AT-команды, отслеживает
отчёты о доставке, хранит историю в SQLite и предоставляет небольшой веб-интерфейс
администратора.

Изначально создавался, чтобы рассылать одноразовые коды авторизации от нескольких
ботов, когда Telegram падал, — а сейчас через Telegram авторизоваться и вовсе нельзя.
Очень простая архитектура: один процесс, один файл SQLite, supervision через systemd.
Без внешнего брокера и без обязательного контейнера.

## Features

- **HTTP API** — `POST /sms/send`, `GET /sms/{id}`, авторизация по Bearer-токену для каждого клиентского приложения
- **Кириллица и многочастные SMS на исходящих** — отправка в режиме PDU с автоматическим выбором кодировки GSM 7-bit/UCS2; длинные сообщения разбиваются на части с UDH-конкатенацией и собираются обратно в одно сообщение на телефоне получателя
- **Отслеживание доставки** — разбирает отчёты о доставке `+CDS`; переводит сообщения
  `pending → sent → delivered/failed`, отмечает зависшие как просроченные
- **Входящие SMS** — декодирует сообщения в режиме PDU (включая UCS2 и сборку многочастных),
  при необходимости передаёт их на webhook по префиксу первого слова
- **Не отправляет в отсутствующую сеть** — перед отправкой шлюз спрашивает модем,
  зарегистрирован ли он, и при явном «нет» откладывает сообщение, не тратя попытку.
  Проверка делается прямо перед отправкой, а не берётся из периодического опроса.
  Смысл узкий: ретраи и так спасают отправку, которая не дошла до модема, — а вот
  многочастное сообщение, у которого первая часть уже принята, повторить нельзя никогда.
  Не начав отправку, шлюз просто не создаёт этот случай. Если проверка не удалась,
  сообщение всё равно отправляется: незнание — не отказ
- **Восстановление модема по провалам отправки** — модем, который исправно отвечает на
  команды, но не отправляет, раньше не считался больным: восстановление запускалось
  только при потере регистрации. Теперь застой отправки (три разных сообщения подряд
  либо одно, исчерпавшее весь бюджет попыток, и с тех пор ни одной удачной отправки)
  тоже запускает штатную лестницу восстановления. На время восстановления отправка и
  чтение входящих приостанавливаются и возобновляются, только когда модем снова
  зарегистрировался, — иначе восстановление само порождало бы те сбои, на которые
  реагирует. Выключается отдельно (`send_stall_recovery_enabled`)
- **Автоматические повторы отправки** — если сообщение не дошло до модема (нет ответа,
  таймаут приглашения, временный отказ сети), шлюз повторяет отправку с нарастающими
  паузами (`send_retry_backoff`, по умолчанию `30,120,300` — четыре попытки примерно за
  8 минут). Статус `failed` и вебхук уходят приложению **только когда попытки
  исчерпаны**, поэтому кратковременный сбой сети больше не выглядит как недоставка.
  Сообщение сохраняет свой `id`. Повтор **никогда** не делается, если байты сообщения уже
  ушли в модем или если одна из частей многочастного SMS уже принята — иначе получатель
  получил бы дубль. Пустое значение настройки выключает повторы
- **Вебхуки статусов исходящих** — при смене статуса (`sent`, `delivered`, `failed`,
  `expired`) шлёт приложению-владельцу `POST {id, status, error, occurred_at}`,
  маршрутизируя по `app_id` сообщения — чтобы приложение узнавало судьбу SMS за секунды,
  а не на следующем опросе. Доставка вебхука best-effort, `GET /sms/{id}` остаётся
  источником правды ([контракт для приёмной стороны](docs/delivery-webhook.md))
- **Настраиваемая проверка номеров** — принимаемая страна задаётся в runtime-настройке
  (`phone_region`, по умолчанию `RU`) прямо в интерфейсе администратора; номера проверяются
  библиотекой [`phonenumbers`](https://github.com/daviddrysdale/python-phonenumbers)
  и нормализуются в E.164
- **Авто-чёрный список** — номера с повторяющимися постоянными ошибками блокируются, пока
  оператор не снимет блокировку
- **Определение оператора и региона** — обогащает номера через voxlink, **только для РФ** (`+7`
  номера). Не-`+7` номера отправляются как обычно, но без данных об операторе и регионе;
  PR-ы, добавляющие best-effort обогащение для других стран (например, через
  `phonenumbers.carrier` / `phonenumbers.geocoder`), приветствуются
- **Двуязычный интерфейс администратора** (русский по умолчанию + английский, переключаемый) — сообщения, диалоги,
  входящие, чёрный список, диапазоны номеров, статистика за день, runtime-**настройки** и
  управление **токенами** клиентов
- **Уведомления в Telegram** — по типам, каждый включается в интерфейсе администратора: системные ошибки (логи ERROR),
  сбои отправки исходящих, сбои доставки / попадание в чёрный список и входящие SMS; всё в один
  чат с дедупликацией по временному окну и настраиваемой меткой инстанса
- **Тесты** — набор `pytest`, покрывающий разбор PDU, сборку, оповещения, lookup, статистику,
  настройки, проверку номеров и страницы администратора

## Screenshots

Интерфейс администратора двуязычный (русский по умолчанию, английский переключается). _(Ниже — демонстрационные данные.)_

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

- **API** (`app/api/`) — проверка запросов, авторизация, постановка в очередь
- **Modem manager** (`app/modem/`) — владеет последовательным портом; sender опустошает
  asyncio-очередь, цикл reader обрабатывает незапрошенные ответы (отчёты о доставке,
  входящие PDU)
- **DB** (`app/db/`) — aiosqlite, режим WAL, миграция при старте
- **Settings** (`app/settings_store.py`) — runtime-конфигурация в БД, редактируется в интерфейсе администратора
- **Admin** (`app/admin/`) — шаблоны Jinja2 (i18n через gettext/Babel) за HTTP Basic auth

Подробнее см. [`docs/`](docs/) (`architecture.md`, `database.md`,
`modem.md`, `api.md`, `deployment.md`, `i18n.md`).

## Requirements

- Python 3.12+
- Модем с поддержкой AT-команд и последовательными портами (например, `/dev/ttyUSB2`/`/dev/ttyUSB3`)
- Linux (разрабатывается/разворачивается на Ubuntu с systemd)

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

База данных и таблицы создаются автоматически при первом запуске. Интерактивная
документация API доступна по адресу `http://localhost:8000/docs`, интерфейс администратора — на `/admin`.

### Registering a client app / token

Создавайте клиентские приложения и их токены в интерфейсе администратора по адресу **`/admin/apps`** (токен
показывается один раз при создании). Или вставьте запись напрямую:

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

> Принимаемая страна задаётся настройкой `phone_region` (по умолчанию `RU`) на `/admin/settings`.
> Номера в национальном формате принимаются и нормализуются в E.164; номера из других
> стран отклоняются, если не совпадают с настроенным регионом.

## Configuration

Конфигурация **bootstrap/infra** читается из переменных окружения или файла `.env` (через
`pydantic-settings`) — см. [`.env.example`](.env.example):

| Variable | Default | Notes |
|----------|---------|-------|
| `SERIAL_SEND_PORT` / `SERIAL_READ_PORT` | `/dev/ttyUSB2` / `/dev/ttyUSB3` | Последовательные порты модема |
| `DB_PATH` | `data/sms.db` | Файл SQLite |
| `HOST` / `PORT` | `0.0.0.0` / `80` | Привязка uvicorn |
| `ADMIN_USER` / `ADMIN_PASSWORD` | `admin` / `change-me` | **Поменяйте перед публикацией!** |

**Runtime-настройки** — voxlink lookup, оповещения в Telegram, правила передачи входящих
(`inbound_dispatch`) и вебхуков статусов исходящих (`delivery_dispatch`),
порог чёрного списка, таймаут доставки, паузы повторов (`send_retry_backoff`) и
`phone_region` — хранятся в базе данных и
редактируются на **`/admin/settings`** (без перезапуска). При первом старте они один раз
заполняются из совпадающих переменных окружения, далее управляются в БД. Токены клиентов управляются на
**`/admin/apps`**.

## Running tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Deployment

Развёртывание на базе systemd (git push-to-deploy, unit-файлы, нотификатор Telegram и
опциональный резервный канал LTE failover) описано в
[`docs/deployment.md`](docs/deployment.md) и [`deploy/`](deploy/). Пути в этих
файлах (`/opt/sms-gate`, порты, хостнеймы) — примеры, адаптируйте их под свой хост.

> Документация `README`, `docs/api.md`, `docs/deployment.md` — двуязычная; при правках обновляйте обе секции (RU сверху — основная).

## License

[MIT](LICENSE)

---

<a id="english"></a>
## English

> 🇬🇧 Russian version above ↑

> README, `docs/api.md`, `docs/deployment.md` are bilingual — when editing, update both the RU (top, canonical) and EN sections.

[![CI](https://github.com/DerAlSem/sms-gate/actions/workflows/ci.yml/badge.svg)](https://github.com/DerAlSem/sms-gate/actions/workflows/ci.yml)

**Your own SMS gateway for ~100 ₽ a month.** All you need is a cheap USB LTE modem and a
regular SIM on a plan with enough SMS.

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

It was originally built to send one-time authorization codes from several bots when
Telegram kept going down — and now logging in via Telegram isn't possible at all. The
architecture is deliberately simple: one process, one SQLite file, systemd for
supervision. No external broker, no container required.

## Features

- **HTTP API** — `POST /sms/send`, `GET /sms/{id}`, Bearer-token auth per client app
- **Outbound Cyrillic & multipart** — sends in PDU mode with automatic GSM 7-bit/UCS2 encoding; long messages are split into UDH-concatenated parts and reassembled as one message on the recipient's phone
- **Delivery tracking** — parses `+CDS` delivery reports; marks messages
  `pending → sent → delivered/failed`, expires stale ones
- **Inbound SMS** — decodes PDU-mode messages (incl. UCS2 and multipart reassembly),
  optionally dispatches them to a webhook by first-word prefix
- **Never sends into a missing network** — before transmitting, the gateway asks the modem
  whether it is registered and holds the message back on a definite no, without spending
  an attempt. The check is made fresh at send time rather than taken from a periodic
  poll. The value is narrow on purpose: retries already recover a send that never reached
  the modem, but a multipart whose first part was accepted can never be retried — not
  starting is the only fix. A check that cannot be completed does not hold the message:
  not knowing is not a refusal
- **Modem recovery driven by send failures** — a modem that answers every command and
  still refuses to send used to look healthy, because only lost registration triggered
  recovery. A send stall (three different messages, or one that used up its whole retry
  budget, with no successful send since) now fails the health check and escalates on the
  existing ladder. Sending and inbound reading are suspended while recovery runs and
  resume only once the modem reports registration again — otherwise recovery would
  manufacture the very failures it reacts to. Switchable on its own
  (`send_stall_recovery_enabled`)
- **Automatic send retries** — when a message never reached the modem (no response, a
  prompt timeout, a temporary network refusal), the gateway tries again with growing
  delays (`send_retry_backoff`, default `30,120,300` — four attempts inside about eight
  minutes). `failed` and its webhook reach the application **only once the attempts are
  exhausted**, so a brief network blip no longer looks like a delivery failure. The
  message keeps its `id`. A retry is **never** made once the message's bytes have gone to
  the modem, or once any part of a multipart SMS has been accepted — either would put a
  duplicate on the recipient's handset. An empty setting disables retrying
- **Outbound status webhooks** — on a status change (`sent`, `delivered`, `failed`,
  `expired`) POSTs `{id, status, error, occurred_at}` to the owning application, routed by
  the message's `app_id` — so an app learns an SMS's fate in seconds instead of on its next
  poll. Webhook delivery is best-effort; `GET /sms/{id}` stays authoritative
  ([receiving-side contract](docs/delivery-webhook.md))
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
- **Telegram notifications** — per-type, each toggled in the admin UI: system errors (ERROR logs), outbound send failures, delivery failures / blacklisting, and inbound SMS; all to one chat with windowed dedup and a configurable instance label
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

**Runtime settings** — voxlink lookup, Telegram alerting, inbound-dispatch (`inbound_dispatch`)
and outbound status-webhook (`delivery_dispatch`) rules,
blacklist threshold, delivery timeout, send-retry backoff (`send_retry_backoff`), and
`phone_region` — live in the database and are
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
