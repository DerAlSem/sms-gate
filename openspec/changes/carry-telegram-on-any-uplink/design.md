# Design

## The shape that was withdrawn, and why

This change began as a routing change: put Telegram's two ranges into the tunnel, because the
far end already forwards exactly those ranges over its own WireGuard client. Three unknowns
were named against it and all three were measured on 2026-09-18.

| unknown | measured | outcome |
|---|---|---|
| does the far end forward at all | `net.ipv4.ip_forward = 1` | yes |
| would a packet from the house find that interface | `ip route get 149.154.167.99 from <house> iif <tunnel>` → `dev wg0` | yes, already |
| would the foreign peer accept our traffic | from the far end: `src 10.66.66.2` completes TLS in **0.13 s**; `src 10.67.67.1` **times out at 12 s** | no |

The third is the one that decides it. The foreign peer accepts the far end's own address and
nothing else, so the route would need a masquerade rule opening the whole tunnel subnet
outward through an interface that is not ours — `reach-the-gateway-on-any-uplink` task 1.6
recorded that interface as "not a hub of ours… not to be touched".

The relay achieves the same reachability for one protocol, one caller and named destinations,
with an allow-list and no path logging, in a file this repository versions. It is also the
shape already deployed and already working. So the routing change buys nothing the relay does
not, and costs a general egress path where a specific one suffices.

**What the withdrawal does not cover.** A non-HTTP dependency on a blocked destination would
have no relay to use. None exists today. If one appears, this decision is the one to reopen,
and the table above is what to reopen it against.

## Where the relay's address lives

`alert_relay_base` already exists (`app/settings_store.py`) and `app/alerting.py` already
prefers it. This change does not add a second setting per caller: one relay, one base, read
from the same place by everything that calls a covered vendor. A caller needing a different
vendor addresses it by path under that base, not by a base of its own — otherwise adding a
vendor means adding a setting, and the settings drift apart exactly the way the three copies
of the delivery path drifted.

## How two vendors share one relay

The relay today is `location / → api.telegram.org`, so the Bot API occupies the whole of it
and a second vendor has nowhere to go.

**Chosen: distinguish by path prefix.** The Bot API keeps `/`, which leaves every existing
caller unchanged, and the Gateway API is reached under a prefix the relay strips. The
alternative — a second listener on the tunnel address — was rejected because the far end's
tunnel-facing firewall admits a named set of ports, so a new port is a change to a firewall
this repository does not hold, to buy a distinction a path prefix already makes.

⚠️ **Open, and gated on the vendor reference rather than on inference:** where the Gateway API
carries its credential. The Bot API carries a token in the path, which is why `access_log` is
off. If the Gateway API authenticates by header instead, the logging argument for it is a
different argument, and `proxy_set_header` has to be written knowing which. The samples in
`route-sends-by-operator/captures/` are responses; they do not show the request. To be read
off the vendor reference before the relay clause is written — not assumed from the Bot API's
shape.

## Proving the relay while the ordinary route still works

The probe runs from the house against the tunnel address. It does not resolve the vendor's
name anywhere: the house's resolver is intercepted by the home router and answers
`198.18.13.246` for `gatewayapi.telegram.org`, so any name resolved here measures the router's
proxy. The relay resolves the vendor at the far end, where DNS is not intercepted.

The probe therefore needs to distinguish **an answer from the vendor** from **an answer from
the relay's own nginx**. An invalid-token call to the Bot API returns `401` produced by
Telegram; a relay that cannot reach Telegram returns `502` produced by nginx. That difference
is the check, and it costs one request with a credential that is deliberately not a credential.

**Not a send.** The probe must never deliver a message: an alerting path proved by sending
alerts is a path that alerts about itself.

## Reporting a fault in the thing that reports faults

`sms-gate-alert` exits zero when it has no credentials, which tells systemd the alert was
delivered. The report has to leave by a route that does not need the missing configuration,
so it is the exit status and the unit state — which the operator's existing checks already
read — rather than a message.

This is deliberately not "hold it in the spool until credentials appear". A held alert implies
someone to deliver it to; with no chat configured there is no one, and a spool filling with
undeliverable alerts is the second fault the bounded spool exists to prevent.

## What stays untouched

- The tunnel's `AllowedIPs` (task 1.8 of `reach-the-gateway-on-any-uplink`).
- The far end's `wg0` and its foreign endpoint.
- The direct route, which remains the fallback on every caller.
