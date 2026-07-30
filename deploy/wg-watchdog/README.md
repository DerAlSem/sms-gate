# Tunnel watchdog

Runs on the house. Answers whether the tunnel to `edge.example.com` is **carrying anything**, which is
a different question from whether its unit is active.

## Why liveness is the wrong test

WireGuard has no connection to lose. The interface stays up whether or not the peer is there,
so `systemctl is-active wg-quick@wg-edge` reports `active` over a tunnel that moves nothing.

That is the shape this project has already paid for twice — a data session reporting
`connected` over an interface with no address, and a background loop that terminated with its
exception discarded — and after the hostname moves it is the most likely way the only route
into this host fails. The gateway can be perfectly healthy and completely unreachable, with
every existing check green.

So the test is reachability: the peer's address either answers or it does not, and that
cannot be true while the tunnel is broken.

Handshake age was the other candidate and is worse. It advances only on rekey, so it lags a
working tunnel and reads as stale on an idle one — a proxy for the property rather than the
property.

## What it does

| Condition | Action |
|---|---|
| Peer answers | Reset. If restarts had happened, say it is carrying again. |
| Silent for `FAILS_BEFORE_RESTART` checks | Restart the tunnel |
| `ALERT_AFTER_RESTARTS` restarts without success | Alert once — this is no longer a blip |
| Still silent afterwards | Keep restarting, stay quiet; the operator has been told |

Defaults: check every 60s, restart after 2 silent checks, alert after 2 fruitless restarts —
so roughly four minutes from a dead tunnel to an alert, and a failover of ~2 minutes never
reaches the alert.

Restarting during a failover is harmless and often helpful: it re-resolves the endpoint and
forces a fresh handshake from the new source address.

## Install

```sh
sudo install -m 755 wg-tunnel-check.sh /usr/local/sbin/wg-tunnel-check
sudo install -m 644 wg-tunnel-check.service wg-tunnel-check.timer /etc/systemd/system/
sudo tee /etc/wg-tunnel-check.env >/dev/null <<'ENVEOF'
# Required — the script refuses to run on the published example address.
PEER_ADDR=YOUR.TUNNEL.FAR.END
UNIT=wg-quick@YOUR-INTERFACE
ENVEOF
sudo systemctl daemon-reload
sudo systemctl enable --now wg-tunnel-check.timer
```

Credentials come from `/opt/sms-gate/.env`, the same place the gateway's own notifier reads
them — one place to rotate, not two.

Verify:

```sh
sudo /usr/local/sbin/wg-tunnel-check ; echo "exit=$?"          # silent, 0
sudo env PEER_ADDR=10.10.10.99 UNIT=true /usr/local/sbin/wg-tunnel-check ; echo "exit=$?"
```

The second points at an address that cannot answer and at `true` instead of the real unit, so
it exercises the failure path without restarting the tunnel. Run it four times to see the
alert fire, then `sudo rm -f /run/wg-tunnel-check.state`.

## What it cannot tell you

That the hostname is unreachable *from the internet*. The tunnel can be carrying while the
far end has stopped publishing the name, and this watchdog would be satisfied. That is
`deploy/reachability/`'s job, and the two are deliberately separate: this one is inside the
house looking at its own link, and that one is outside looking at the whole path.
