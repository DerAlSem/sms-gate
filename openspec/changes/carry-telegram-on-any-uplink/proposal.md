## Why

The carrier behind the backup uplink drops Telegram and nothing else. Measured on
2026-09-18 by real address bound to `wwan0`: `api.telegram.org` (149.154.166.110) and
`gatewayapi.telegram.org` (149.154.167.99) both time out at fifteen seconds, while
`cloudflare.com` answers in 0.34 s, `www.google.com` in 0.44 s and `api.ucaller.ru` in
0.17 s over that same interface. The interface carries traffic. One vendor does not arrive.

Half of the answer already exists and is not written down anywhere. A relay on the far end
of the tunnel — `deploy/nginx/edge-alert-relay.conf`, bound to the tunnel address, admitting
only the house — forwards Bot API calls out over a machine that can reach Telegram. It is
deployed and it works: from the house, `http://<tunnel-far-end>/bot<invalid>/getMe` answers
**401 in 0.21 s**, and the 401 comes from Telegram itself. The far end is reachable over the
backup uplink too — **404 in 0.28 s** over `wwan0` — so the path survives the outage it
exists for.

What is missing is that the relay covers only the callers that happen to know about it, and
no requirement says they must. Three callers do not:

- `app/telegram_poll.py` has `https://api.telegram.org` compiled into `_API`. The operator's
  replies — the channel through which an SMS is sent by hand — stop being received during a
  wired outage.
- `gatewayapi.telegram.org` is not proxied by the relay at all. That is the `tg_gateway` rung
  of `route-sends-by-operator`, whose task 1.12 is presently written as an assumption this
  change has to remove.
- `deploy/reachability/reachability-check.sh` posts to `api.telegram.org` directly, so the
  check that exists to detect an outage from outside the failure domain is itself carried by
  the path the outage removes.

And the relay is a path whose ordinary exercise cannot be taken on trust. The home router
intercepts DNS: `gatewayapi.telegram.org` resolves to `198.18.13.246` on the wired link, an
address belonging to the router's own proxy. So on the wired link the direct route answers,
through a substitution this repository does not control, and the relay can be dead for months
without a symptom — until the day the wire drops, which is the day it is needed. This project
has been bitten by exactly that shape twice, and `reach-the-gateway-on-any-uplink` was written
against it.

## What Changes

- **Every Telegram call the gateway makes goes through the relay first**, with the direct
  route as fallback — the ordering `app/alerting.py` already implements and which becomes
  normative rather than incidental. The callers that bypass it are brought in.
- **The relay carries the Gateway API as well as the Bot API.** They are separate hostnames
  with separate credentials, and the relay admits each explicitly rather than becoming a
  general forwarder.
- **The relay is exercised on a schedule, by real address**, so its death is discovered by a
  probe and not by an outage. A name resolved at the house cannot be part of that probe.
- **An alert is not silently dropped when it cannot be addressed.** `sms-gate-alert` answers
  `no alert credentials` and exits zero — observed three times on 19–20 August 2026, each
  time losing the alert it was given. Missing credentials are a fault of the gateway's
  configuration, and a fault that hides alerts must be reported as loudly as the alerts it
  ate.

## Non-goals

- **No route for Telegram's ranges into the tunnel, and no masquerade on the far end.** That
  was the shape this change started as. It was withdrawn on evidence: the far end does not
  masquerade the tunnel subnet (from the far end, `src 10.66.66.2` completes TLS to Telegram
  in 0.13 s while `src 10.67.67.1` times out at 12 s), so it would need a new NAT rule opening
  the whole subnet outward, where the relay already achieves the same thing for one protocol,
  for one caller, with `access_log off` and an allow-list, in a file this repository versions.
- **The tunnel's `AllowedIPs` stays as narrow as it is.** `reach-the-gateway-on-any-uplink`
  task 1.8 set it to the far end alone, deliberately: a wider one would send the uplink
  watchdog's own probes through the tunnel and make failover a decision about the tunnel
  rather than about the wire. This change does not touch it.
- **Nothing here fixes the carrier.** Telegram remains unreachable over `wwan0` directly, and
  the direct route remains the fallback it is today.

## Capabilities

### New Capabilities

- `outbound-reachability`: the gateway reaching the services it depends on, over whichever
  uplink is carrying traffic — which route is tried in what order, which vendors the relay
  admits, how the relay is proved alive, and what happens to a message that no route could
  carry.

## Impact

- `app/telegram_poll.py` — takes its base from configuration instead of a constant.
- `app/alerting.py` — its route ordering becomes specified; no behavioural change expected.
- `deploy/nginx/edge-alert-relay.conf` — a second vendor hostname.
- `deploy/reachability/reachability-check.sh` — goes through the relay.
- `deploy/alert-send.sh` — missing credentials stop being a silent exit.
- `openspec/changes/route-sends-by-operator/tasks.md` task 1.12 — its assumption is removed
  rather than carried; the rung becomes uplink-independent.

## Depends on

- The tunnel from `reach-the-gateway-on-any-uplink`, which is deployed and whose watchdog is
  running. That change is not yet archived, so `inbound-reachability` is not in the live spec;
  this change adds a capability of its own rather than modifying one that does not exist yet.
