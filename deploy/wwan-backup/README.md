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
wwan-backup test-alert                  # does an alert actually get out?
```

`test-alert` exists because the alert path used to be checkable only by staging a real
failover. That is a poor trade: a genuine outage to answer a question about a route. To prove
the *relay* carried it rather than the direct route, blackhole the direct one for the
duration — the message still arriving is the whole claim:

```bash
tg=$(getent ahosts api.telegram.org | awk '{print $1}' | head -1)
ip route add blackhole "$tg"
wwan-backup test-alert
ip route del blackhole "$tg"
```

**Blackhole what the name resolves to here, not Telegram's published ranges.** On this house
`api.telegram.org` answers as `198.18.11.187` — a reserved RFC 2544 address, substituted by a
bypass on the router. Blackholing `149.154.160.0/20` therefore blocks nothing and the test
passes while proving nothing, which is exactly what happened on 2026-08-01: two alerts were
declared "delivered by the relay, the direct route could not have carried it" when the direct
route had been open the whole time.

Both are true at once, incidentally, and either alone would sink the direct route during an
outage: the carrier really does block Telegram — its real addresses time out over `wwan0`
while an ordinary host answers — *and* the substituted address is a LAN-local fiction that
means nothing once traffic leaves by the backup.

Alerts go to the relay at the far end first and fall back to `api.telegram.org`. The order is
deliberate: the carrier this uplink runs on blocks Telegram, so the direct route is dead at
exactly the moment a failover alert is raised — which is how the alert saying the outage had
begun was lost while the one saying it had ended arrived.

Inbound over the backup used to be impossible: T2 is behind CGNAT, so nothing could reach the
host on it. That is no longer the shape — a WireGuard tunnel to the far end carries inbound
traffic over whichever uplink is alive, and it is the far end that holds the public address.
See `deploy/wg-watchdog/` and the `inbound-reachability` spec.
