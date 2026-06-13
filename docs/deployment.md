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

Install or refresh them (one-time, and again whenever the unit files change — the
`post-receive` hook does NOT copy them):

```bash
sudo cp /opt/sms-gate/deploy/sms-gate.service /etc/systemd/system/
sudo cp /opt/sms-gate/deploy/sms-gate-notify@.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart sms-gate
```

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

The post-receive hook needs `sudo systemctl restart` without password:

```bash
sudo visudo -f /etc/sudoers.d/sms-gate
```

Add:
```
smsgate ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart sms-gate, /usr/bin/systemctl stop sms-gate, /usr/bin/systemctl start sms-gate
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
