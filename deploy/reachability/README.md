# Reachability check

Answers the one question nothing else on this system answers: **can anyone actually reach
`gateway.example.com`?**

Everything else that watches the gateway runs on the gateway. That tells you whether the
process is up, and it is silent about whether the name resolves, whether the certificate is
valid, whether the tunnel is carrying anything, and whether the machine publishing the
hostname is still publishing it. Those diverge from "the process is up" exactly when it
matters.

## Where it runs, and why that is not a contradiction

On `edge.example.com` — the machine that publishes the hostname. That is inside the failure domain
for precisely one case: `edge.example.com` itself dying.

That case is not a silent failure. It takes every other site that machine hosts with it,
including the application that calls this gateway — so there is nobody left to be affected,
and no way for it to go unnoticed. Every other failure introduced by moving the hostname
here is visible from here: a dead tunnel, a dead gateway, a wrong DNS record, an expired
certificate, a front end that stopped routing the hostname.

A better vantage point exists (a device on an unrelated network, a third-party monitor) and
would cover that last case too. It is not worth the moving part while the case it covers is
the loudest failure the estate has.

## A status code is not the check

The publishing front end answers its own error page when it cannot reach the origin. A name
that answers with somebody else's error is a name that answers, so a probe that accepts any
`200` cannot tell service from outage. This one requires a marker in the body that only the
application produces.

## Install

```sh
sudo install -m 755 reachability-check.sh /usr/local/sbin/reachability-check
sudo install -m 644 reachability-check.service reachability-check.timer /etc/systemd/system/
sudo tee /etc/reachability-check.env >/dev/null <<'ENVEOF'
# What to check. Required — the script refuses to run on the published example value.
URL=https://YOUR-GATEWAY-HOST/docs
HOSTNAME_CHECKED=YOUR-GATEWAY-HOST
ALERT_BOT_TOKEN=...
ALERT_CHAT_ID=...
ENVEOF
sudo chmod 600 /etc/reachability-check.env
sudo systemctl daemon-reload
sudo systemctl enable --now reachability-check.timer
```

Verify by hand before trusting it:

```sh
sudo /usr/local/sbin/reachability-check ; echo "exit=$?"
URL=https://gateway.example.com/nope MARKER=nothing sudo -E /usr/local/sbin/reachability-check ; echo "exit=$?"
```

The first should exit `0` silently. The second should exit `1` and log a failure — run it
three times to see the alert fire, since one bad check is not an outage.

## Tuning

| Variable | Default | Why |
|---|---|---|
| `FAIL_THRESHOLD` | 3 | A failover is ~90s of detection plus the tunnel dialling out again, which trips one or two checks. That is a pause, not an incident; alerting on it teaches the operator to ignore alerts. |
| `REMIND_EVERY` | 60 | While it stays broken: one reminder an hour, not one a minute. |
| `CERT_WARN_DAYS` | 14 | The certificate here began as a copy of the house's, as a bridge across the cutover. Unreplaced, it expires quietly. |

## What it depends on

Telegram, which on this machine is reached through a tunnel of its own. If that tunnel dies
the alerts stop without saying so — second-order, and recorded here rather than discovered.
