# SMS Gate — Deployment Guide

> 🇷🇺 Документация на русском. **English version below ↓** — [jump to English](#english)

<!-- Russian translation: SAME headings/sections/order as the English original -->

## Configuration

Ключи начальной загрузки / инфраструктуры (последовательные порты, `DB_PATH`, `HOST`, `PORT`, `ADMIN_USER`,
`ADMIN_PASSWORD`) читаются из `.env` при запуске — полный список см. в `.env.example`.

Настройки времени выполнения — учётные данные voxlink, оповещения Telegram, правила маршрутизации входящих,
порог блокировки и таймаут доставки — управляются в админ-интерфейсе по адресу
`/admin/settings` и хранятся в базе данных. Токены клиентских приложений создаются и отзываются
по адресу `/admin/apps`. Перезапуск при изменении этих значений не требуется.

---

## Server Prerequisites

```bash
# On the server (Ubuntu 24)
sudo apt update
sudo apt install python3.12 python3.12-venv git

# Add user to dialout group (for serial port access)
sudo usermod -aG dialout $USER
# Re-login after this!
```

---

## 1. Setup Bare Git Repo on Server

```bash
# On the server
sudo mkdir -p /opt/sms-gate.git
sudo mkdir -p /opt/sms-gate
sudo chown $USER:$USER /opt/sms-gate.git /opt/sms-gate

git init --bare /opt/sms-gate.git
```

---

## 2. Create Post-Receive Hook

```bash
cat > /opt/sms-gate.git/hooks/post-receive << 'EOF'
#!/bin/bash
TARGET="/opt/sms-gate"
GIT_DIR="/opt/sms-gate.git"

echo ">>> Deploying to $TARGET"
git --work-tree=$TARGET --git-dir=$GIT_DIR checkout -f

cd $TARGET

# Recreate venv if requirements changed
if [ ! -d "venv" ] || [ requirements.txt -nt venv/timestamp ]; then
    echo ">>> Updating venv..."
    python3.12 -m venv venv
    venv/bin/pip install -r requirements.txt
    touch venv/timestamp
fi

echo ">>> Installing units..."
sudo /usr/local/sbin/sms-gate-install-units

echo ">>> Restarting service..."
sudo systemctl restart sms-gate

echo ">>> Done!"
EOF

chmod +x /opt/sms-gate.git/hooks/post-receive
```

---

## 3. Add Git Remote on Laptop

```bash
# On the laptop, in your local project directory/
git init
git remote add deploy ssh://user@server-ip/opt/sms-gate.git

# To deploy:
git add -A
git commit -m "initial"
git push deploy main
```

---

## 4. Systemd Service

Скопируйте `deploy/sms-gate.service` на сервер:

```bash
sudo cp /opt/sms-gate/deploy/sms-gate.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable sms-gate
sudo systemctl start sms-gate
```

Unit-файлы теперь лежат в репозитории в каталоге `deploy/` (источник истины):
`deploy/sms-gate.service` и `deploy/sms-gate-notify@.service`.

Начиная с этого места их ставит деплой — хук вызывает `sms-gate-install-units`, который
сравнивает содержимое, копирует только изменившееся, делает `daemon-reload` и печатает, что
именно поменял. До этого они были копиями, которые деплой не трогал, и изменение unit-файла
молча не доезжало: деплой отчитывался успехом, служба перезапускалась, правки не было.

**Ставится не всё из `deploy/`, и это намеренно.** Репозиторий публикует форму, а не адрес,
поэтому сторож туннеля и nginx-блоки держат здесь примеры, а на машине — настоящие значения.
Установка таких файлов направила бы сторож на адрес, где никто не отвечает, и переписала бы
`server_name` на имя, которым никто не пользуется. Машинные значения живут в
`/etc/wg-tunnel-check.env`, `/etc/default/wwan-backup` и systemd-drop-in'ах. nginx-блоки
исключены навсегда: `listen` и `server_name` не параметризуются.

Службы установщик **не перезапускает** — `wwan-backup` на остановке рвёт резервную сессию, и
во время проводной аварии это унесло бы единственный живой аплинк. Скрипты, которые эти
службы запускают, перевызываются на каждом тике, так что установки скрипта достаточно;
изменившийся *unit* вступает в силу на следующей загрузке.

Сам установщик — root-owned, лежит вне задеплоенного дерева и обновляется руками:

```bash
sudo install -m 755 /opt/sms-gate/deploy/install-units.sh /usr/local/sbin/sms-gate-install-units
```

Это граница, а не недосмотр: манифест, который может переписать пуш, — не манифест. Отсюда же
следует, что доступ на пуш здесь равносилен руту, поскольку unit-файл называет команду. Сузить
это нельзя, пока деплой вообще ставит юниты, и принято оно осознанно.

Главный unit ограничивает перезапуски (`StartLimitBurst=5` / `StartLimitIntervalSec=300`): после
5 быстрых сбоев systemd прекращает циклические попытки и переходит в состояние `failed`, что запускает
`OnFailure=sms-gate-notify@sms-gate.service` → одно оповещение в Telegram с трассировкой.

---

## 5. Create .env on Server

`.env` содержит только ключи **начальной загрузки / инфраструктуры** — значения, которые нужны процессу до
открытия базы данных. Всё остальное (учётные данные voxlink, оповещения Telegram, правила маршрутизации
входящих, порог блокировки, таймаут доставки, регион телефона) настраивается во время выполнения
через админ-интерфейс (`/admin/settings`) и хранится в базе данных. Токены клиентских приложений
управляются по адресу `/admin/apps`. Перезапуск при изменении этих значений не требуется.

```bash
# On server — this file is NOT in git
cat > /opt/sms-gate/.env << 'EOF'
# Modem / serial
SERIAL_SEND_PORT=/dev/ttyUSB2
SERIAL_READ_PORT=/dev/ttyUSB3
SERIAL_BAUDRATE=115200

# Storage
DB_PATH=/opt/sms-gate/data/sms.db

# Server
HOST=0.0.0.0
PORT=80

# Admin UI (HTTP Basic) — change before exposing the service
ADMIN_USER=admin
ADMIN_PASSWORD=change-me
EOF
```

> **Устаревшие переменные окружения:** если `ALERT_BOT_TOKEN`, `ALERT_CHAT_ID` или другие ключи
> мягкой конфигурации присутствуют в `.env` от более старой установки, они автоматически
> переносятся в БД при первом запуске и далее игнорируются. Вы можете удалить их из `.env`, как только
> сервис успешно запустится.

### Telegram Alerting

Учётные данные Telegram-бота настраиваются в админ-интерфейсе, а не в `.env`.
После запуска сервиса перейдите в `/admin/settings` и заполните
`ALERT_BOT_TOKEN` и `ALERT_CHAT_ID`. Перезапуск не требуется.

Протестируйте уведомитель целиком, ничего не сломав:

```bash
# Dry run: prints the payload, sends nothing.
sudo ALERT_DRY_RUN=1 /opt/sms-gate/deploy/notify-telegram.sh sms-gate.service

# Real send via the systemd path:
sudo systemctl start sms-gate-notify@sms-gate.service
```

Сообщение в Telegram должно прийти в течение нескольких секунд.

**Замечание о тайминге:** оповещение systemd о падении срабатывает, когда unit прекращает попытки перезапуска —
после ~5 сбоев (`StartLimitBurst`), так что ожидайте его примерно через 40–50 с после начала цикла падений, а не при
первом падении. Процесс, который падает медленно (с интервалом дольше 300-секундного окна burst между
падениями), не записав ERROR, может не вызвать оповещение systemd; обработчик ERROR на уровне приложения
покрывает всё, что логируется перед смертью.

---

## 6. Sudoers for Restart (no password)

Хуку post-receive нужен `sudo systemctl restart` и установщик юнитов без пароля. Имя в правиле
обязано совпадать с аккаунтом, от которого выполняется хук, — это владелец bare-репозитория
`/opt/sms-gate.git`, а не обязательно `smsgate`; проверить можно через `ls -ld /opt/sms-gate.git`.

```bash
sudo visudo -f /etc/sudoers.d/sms-gate
```

Добавьте:
```
smsgate ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart sms-gate, /usr/bin/systemctl stop sms-gate, /usr/bin/systemctl start sms-gate, /usr/local/sbin/sms-gate-install-units
```

---

## Daily Workflow

```bash
# On laptop — edit code, then:
git add -A && git commit -m "fix delivery parsing"
git push deploy main
# Server auto-deploys and restarts
```

## Checking Logs

```bash
# On server
sudo journalctl -u sms-gate -f          # Live logs
sudo journalctl -u sms-gate --since today  # Today's logs
sudo systemctl status sms-gate          # Quick status
```

---

## Serial Port Permissions

Если сервис не может открыть последовательный порт:

```bash
# Check which port the modem uses
ls -la /dev/ttyUSB*

# The service runs as user 'smsgate' in group 'dialout'
# Make sure the port is owned by dialout:
ls -la /dev/ttyUSB2
# Should show: crw-rw---- 1 root dialout ...

# If not, create a udev rule:
sudo cat > /etc/udev/rules.d/99-quectel.rules << 'EOF'
SUBSYSTEM=="tty", ATTRS{idVendor}=="2c7c", MODE="0660", GROUP="dialout"
EOF
sudo udevadm control --reload-rules
```

---

<a id="english"></a>
## English

> 🇬🇧 Russian version above ↑

# SMS Gate — Deployment Guide

## Configuration

Bootstrap / infrastructure keys (serial ports, `DB_PATH`, `HOST`, `PORT`, `ADMIN_USER`,
`ADMIN_PASSWORD`) are read from `.env` at startup — see `.env.example` for the full list.

Runtime settings — voxlink credentials, Telegram alerting, inbound dispatch rules,
blacklist threshold, and delivery timeout — are managed in the admin UI at
`/admin/settings` and stored in the database. Client app tokens are created and revoked
at `/admin/apps`. No restart is required when changing these values.

---

## Server Prerequisites

```bash
# On the server (Ubuntu 24)
sudo apt update
sudo apt install python3.12 python3.12-venv git

# Add user to dialout group (for serial port access)
sudo usermod -aG dialout $USER
# Re-login after this!
```

---

## 1. Setup Bare Git Repo on Server

```bash
# On the server
sudo mkdir -p /opt/sms-gate.git
sudo mkdir -p /opt/sms-gate
sudo chown $USER:$USER /opt/sms-gate.git /opt/sms-gate

git init --bare /opt/sms-gate.git
```

---

## 2. Create Post-Receive Hook

```bash
cat > /opt/sms-gate.git/hooks/post-receive << 'EOF'
#!/bin/bash
TARGET="/opt/sms-gate"
GIT_DIR="/opt/sms-gate.git"

echo ">>> Deploying to $TARGET"
git --work-tree=$TARGET --git-dir=$GIT_DIR checkout -f

cd $TARGET

# Recreate venv if requirements changed
if [ ! -d "venv" ] || [ requirements.txt -nt venv/timestamp ]; then
    echo ">>> Updating venv..."
    python3.12 -m venv venv
    venv/bin/pip install -r requirements.txt
    touch venv/timestamp
fi

echo ">>> Installing units..."
sudo /usr/local/sbin/sms-gate-install-units

echo ">>> Restarting service..."
sudo systemctl restart sms-gate

echo ">>> Done!"
EOF

chmod +x /opt/sms-gate.git/hooks/post-receive
```

---

## 3. Add Git Remote on Laptop

```bash
# On the laptop, in your local project directory/
git init
git remote add deploy ssh://user@server-ip/opt/sms-gate.git

# To deploy:
git add -A
git commit -m "initial"
git push deploy main
```

---

## 4. Systemd Service

Copy `deploy/sms-gate.service` to server:

```bash
sudo cp /opt/sms-gate/deploy/sms-gate.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable sms-gate
sudo systemctl start sms-gate
```

The unit files now live in the repo under `deploy/` (source of truth):
`deploy/sms-gate.service` and `deploy/sms-gate-notify@.service`.

The deploy installs them from here on: the hook calls `sms-gate-install-units`, which compares
content, copies only what differs, runs `daemon-reload`, and prints what it changed. Before
that they were copies the deploy never touched, so a changed unit file silently failed to
arrive — the deploy reported success, the service restarted, and the change was simply absent.

**Not everything under `deploy/` is installed, deliberately.** This repository publishes the
shape and not the address, so the tunnel watchdog and the nginx blocks hold examples here and
real values on the machine. Installing those would point the watchdog at an address nothing
answers on and rewrite a `server_name` to a hostname nobody calls. Machine-specific values
belong in `/etc/wg-tunnel-check.env`, `/etc/default/wwan-backup` and systemd drop-ins. The
nginx blocks are excluded permanently: `listen` and `server_name` do not parameterise.

The installer does **not** restart services. `wwan-backup` tears down the backup data session
on stop, which during a wired outage would take the only working uplink with it. The scripts
those services run are re-executed on every tick, so installing the script is enough for them;
a changed *unit* applies at the next boot.

The installer itself is root-owned, lives outside the deployed tree, and is updated by hand:

```bash
sudo install -m 755 /opt/sms-gate/deploy/install-units.sh /usr/local/sbin/sms-gate-install-units
```

That is the boundary, not an oversight — a manifest a push could edit is not a manifest. It
also means push access is equivalent to root here, since a unit file names a command. That
cannot be narrowed away while deploys install units at all, and is accepted knowingly.

The main unit limits restarts (`StartLimitBurst=5` / `StartLimitIntervalSec=300`): after
5 rapid failures systemd stops looping and enters `failed`, which triggers
`OnFailure=sms-gate-notify@sms-gate.service` → one Telegram alert with the traceback.

---

## 5. Create .env on Server

`.env` holds only **bootstrap / infrastructure** keys — the values the process needs before
the database is open. Everything else (voxlink credentials, Telegram alerting, inbound
dispatch rules, blacklist threshold, delivery timeout, phone region) is configured at
runtime via the admin UI (`/admin/settings`) and stored in the database. Client app tokens
are managed at `/admin/apps`. No restart is required when changing those values.

```bash
# On server — this file is NOT in git
cat > /opt/sms-gate/.env << 'EOF'
# Modem / serial
SERIAL_SEND_PORT=/dev/ttyUSB2
SERIAL_READ_PORT=/dev/ttyUSB3
SERIAL_BAUDRATE=115200

# Storage
DB_PATH=/opt/sms-gate/data/sms.db

# Server
HOST=0.0.0.0
PORT=80

# Admin UI (HTTP Basic) — change before exposing the service
ADMIN_USER=admin
ADMIN_PASSWORD=change-me
EOF
```

> **Legacy env vars:** if `ALERT_BOT_TOKEN`, `ALERT_CHAT_ID`, or other soft-config keys are
> present in `.env` from an older install, they are migrated into the DB automatically on
> the first start and ignored afterwards. You can remove them from `.env` once the service
> has started successfully.

### Telegram Alerting

Telegram bot credentials are configured in the admin UI, not in `.env`.
Navigate to `/admin/settings` after the service is running and fill in
`ALERT_BOT_TOKEN` and `ALERT_CHAT_ID`. No restart is required.

Test the notifier end-to-end without breaking anything:

```bash
# Dry run: prints the payload, sends nothing.
sudo ALERT_DRY_RUN=1 /opt/sms-gate/deploy/notify-telegram.sh sms-gate.service

# Real send via the systemd path:
sudo systemctl start sms-gate-notify@sms-gate.service
```

A Telegram message should arrive within a few seconds.

**Note on timing:** the systemd crash alert fires when the unit gives up restarting —
after ~5 failures (`StartLimitBurst`), so expect it ≈40–50s into a crash loop, not on the
first crash. A process that crashes slowly (longer than the 300s burst window between
crashes) without logging an ERROR may not trigger the systemd alert; the app-level ERROR
handler covers anything that logs before dying.

---

## 6. Sudoers for Restart (no password)

The post-receive hook needs `sudo systemctl restart` and the unit installer without a password.
The name in the rule must be the account the hook runs as — the owner of the bare repo
`/opt/sms-gate.git`, not necessarily `smsgate`; check with `ls -ld /opt/sms-gate.git`.

```bash
sudo visudo -f /etc/sudoers.d/sms-gate
```

Add:
```
smsgate ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart sms-gate, /usr/bin/systemctl stop sms-gate, /usr/bin/systemctl start sms-gate, /usr/local/sbin/sms-gate-install-units
```

---

## Daily Workflow

```bash
# On laptop — edit code, then:
git add -A && git commit -m "fix delivery parsing"
git push deploy main
# Server auto-deploys and restarts
```

## Checking Logs

```bash
# On server
sudo journalctl -u sms-gate -f          # Live logs
sudo journalctl -u sms-gate --since today  # Today's logs
sudo systemctl status sms-gate          # Quick status
```

---

## Serial Port Permissions

If the service can't open the serial port:

```bash
# Check which port the modem uses
ls -la /dev/ttyUSB*

# The service runs as user 'smsgate' in group 'dialout'
# Make sure the port is owned by dialout:
ls -la /dev/ttyUSB2
# Should show: crw-rw---- 1 root dialout ...

# If not, create a udev rule:
sudo cat > /etc/udev/rules.d/99-quectel.rules << 'EOF'
SUBSYSTEM=="tty", ATTRS{idVendor}=="2c7c", MODE="0660", GROUP="dialout"
EOF
sudo udevadm control --reload-rules
```

## How the gateway is reached

`gateway.example.com` does not point at the house. It points at `edge.example.com`, which forwards to the
house over a permanent WireGuard tunnel.

```
caller ──https──▶ edge.example.com:443 ──http over wg-edge──▶ house 10.10.10.3:80 ──▶ uvicorn 127.0.0.1:30080
                  (TLS ends here)                      (nginx)
```

**Why, and not merely how.** The backup uplink is an LTE modem behind carrier-grade NAT: it
has no address that can be resolved to and no port on it can be opened from outside. So a
record pointing at the house answers only while the wired link is up, and a wired outage
takes the gateway with it — modem, SIM and service all healthy, and nobody able to reach
them. A connection dialled *outward* is the only shape that survives, because its return
traffic rides a connection the carrier already permitted.

The tunnel is up at all times, not raised on failure. A path used only during an outage is
first tested by the outage; this one is exercised by every ordinary request, and a failover
changes no DNS record at all.

**Measured across a failover:** no interrupted request at five-second resolution, in either
direction. The session survives the address change, so there is no handshake to redo. Plan
against the uplink's own detection threshold — about ninety seconds — not against the tunnel.

### What sits where

| Machine | Part | File in this repo |
|---|---|---|
| `edge.example.com` | TLS, server block for the hostname | `deploy/nginx/mprz-gateway.example.com.conf` |
| `edge.example.com` | Relay carrying the house's alerts to Telegram | `deploy/nginx/edge-alert-relay.conf` |
| `edge.example.com` | Checks the hostname answers, from outside | `deploy/reachability/` |
| house | Answers on the tunnel address | `deploy/nginx/house-gateway-tunnel.conf` |
| house | Checks the tunnel *carries* | `deploy/wg-watchdog/` |

All of these are installed by hand. A deploy updates this repository on the box and does not
touch them — which has already produced changes that were committed, deployed and inert at
the same time. See `openspec/changes/` for the work item.

### Administrative access during an outage

The ordinary route is a port on the wired address and dies with it. During a wired outage,
reach the house through the far end:

```bash
ssh -J edge.example.com deralsem@10.10.10.3
```

Or as a `~/.ssh/config` entry, so it is one command when it is needed:

```
Host house-tunnel
    HostName 10.10.10.3
    User deralsem
    ProxyJump edge.example.com
```

Keys only — passwords are refused for the tunnel's addresses, because the far end hosts
eleven public applications and a compromise of any of them would otherwise become a
brute-force attempt against the house over a channel nobody watches.

### Rollback

One change: point `gateway.example.com` back at `house.example.com` (CNAME, DNS only). The house
still serves the hostname on its own certificate, which renews over DNS and therefore cannot
expire from being unreachable.

Two things to know before relying on it. It restores a path that works **only over the wired
link**, so it answers "this topology turned out badly" and never "it is down right now". And
it propagates on the record's TTL, unlike a failover, which propagates not at all.

### What watches what, and what each is blind to

| Watcher | Runs on | Answers | Blind to |
|---|---|---|---|
| `wg-tunnel-check` | house | Is the tunnel carrying? | Whether the far end still publishes the name |
| `reachability-check` | `edge.example.com` | Does the hostname answer, served by the gateway? | `edge.example.com` itself dying |
| gateway's own alerting | house | Modem, sends, loops | Anything about being reached |

`reachability-check` requires a marker only the application emits. A front end returns its
own error page when it cannot reach the origin, and a name that answers with somebody else's
error is a name that answers — a probe accepting any `200` cannot tell service from outage.

`reachability-check`'s blind spot is deliberate. `edge.example.com` dying takes eleven sites and the
gateway's own caller with it, so there is nobody left to be affected and no way for it to go
unnoticed.

### Alerts during a wired outage

The mobile carrier cannot reach `api.telegram.org`. Before this was addressed, an outage
produced no alert at all and the *restore* alert arrived afterwards — being told an outage
ended and never that it began.

The house now sends through the relay on `edge.example.com`, over the tunnel, which works on either
uplink. It is tried **first**, so it is the route ordinary traffic exercises; the direct route
is the second attempt and covers the relay being down. If neither answers, the alert is held
on disk and delivered when a route returns, stamped with its age — a late alert read without
one is read as current.

Set `ALERT_RELAY_BASE` in `.env`; the application picks it up as a setting on first start.
