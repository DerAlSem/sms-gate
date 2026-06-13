# wwan-backup — backup internet via Quectel EM06 (T2)

Data session via QMI (`/dev/cdc-wdm0` → `wwan0`), AT ports `ttyUSB2/3` are not
touched — sms-gate runs in parallel. ModemManager is not needed and harmful
(it interferes with AT ports) — do not install.

## Logic

- `wwan-backup.service` keeps the QMI session up with a standby default route
  (metric 700 — the kernel ignores it while the primary metric 100 is alive).
- `wwan-watchdog.timer` (every 30s) pings `1.1.1.1`/`8.8.8.8` strictly via
  `enp2s0`. 3 consecutive failures → default via `wwan0` metric 50 + DNS set to
  operator servers (`resolvectl`). 3 consecutive successes → rollback.
- Sends a Telegram alert on every switch (credentials from `/opt/sms-gate/.env`).

## Installation (root)

```bash
apt-get install -y libqmi-utils
install -m755 /opt/sms-gate/deploy/wwan-backup/wwan-backup.sh /usr/local/sbin/wwan-backup
cp /opt/sms-gate/deploy/wwan-backup/wwan-{backup,watchdog}.service \
   /opt/sms-gate/deploy/wwan-backup/wwan-watchdog.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now wwan-backup.service wwan-watchdog.timer
```

Config (APN, thresholds, interfaces) can be overridden in `/etc/default/wwan-backup`.

## Verification

```bash
wwan-backup status                      # session, routes, counters
ping -I wwan0 1.1.1.1                   # is the backup channel alive?
journalctl -t wwan-backup -f            # switch log
```

Limitation: T2 is behind CGNAT — inbound connections to sms.example.com via the
backup channel do not work (outbound only). Solution — WireGuard to VPS /
Cloudflare Tunnel (next step).
