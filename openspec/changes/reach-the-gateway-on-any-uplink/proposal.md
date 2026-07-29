## Why

The backup uplink keeps the gateway able to reach the internet. It has never made the
gateway *reachable*: the carrier puts it behind CGNAT, so no inbound connection arrives over
it and no record can be pointed at it. When the wired link goes, `sms.deralsem.ru` stops
answering though the modem, the SIM and the service are all healthy — and the host stops
being reachable over SSH too, so the outage cannot even be looked at.

A tunnel dialled *outward* is the only shape that survives CGNAT. The far end is already
paid for and already running: `mprz.ru`, which hosts the applications that call this gateway.

## What Changes

- The gateway is reached through a **permanently established** tunnel to `mprz.ru`, not one
  raised when the wired link fails. A path used only during an outage is a path first
  exercised by the incident it exists to survive — this project has already been bitten
  twice by exactly that shape, and building a third instance deliberately would be hard to
  defend.
- **BREAKING for operations:** `sms.deralsem.ru` resolves to `mprz.ru` instead of the house.
  TLS is terminated there by a server block of its own, and traffic reaches the gateway over
  the tunnel.
- Failover stops involving DNS. The record never moves, so there is no propagation window in
  either direction and no state machine that has to be right twice. Which uplink carries the
  tunnel stays the routing question the wwan watchdog already answers.
- **The tunnel joins two endpoints, not two networks.** Reaching the house from `mprz.ru` —
  the busiest and most exposed machine in the estate — must be limited to the one service
  being published, or an availability change quietly becomes a route into the home network.
- **Supervision is on carrying traffic, not on the process being alive.** "Alive and moving
  nothing" is precisely the shape that has already cost this project two changes: a data
  session reporting `connected` over an interface with no address, and a loop that died in
  silence.
- **Reachability is checked from outside the failure domain.** Everything that watches this
  gateway today runs on the gateway. That answers "is the process up", never "does the name
  answer from the internet" — and the two diverge exactly when it matters.
- **Administrative access survives the wired link**, through the same tunnel.
- **Requests are recorded with where they came from.** Nothing records this today, which was
  survivable while reaching the gateway meant being on the house's network; it stops being so
  when there is one public entrance and the credentials behind it are long-lived.
- **The direct path is retired in two stages, not one.** It stays serving through a soak
  period, so rollback is real while the new path is unproven; it is retired afterwards, so
  "the tunnel is the only way in" becomes true rather than being asserted while port 443 on
  the house still answers to anyone who knows the address.
- The far end needs a certificate of its own, which is routine there — it already issues them
  for eleven hostnames. Renewal at the house is unaffected either way: it is validated over
  DNS and has never depended on being reachable, which also means the rollback path cannot
  quietly expire out from under itself.

## Capabilities

### New Capabilities

- `inbound-reachability`: being reachable from outside over whichever uplink carries
  traffic — the tunnel and what it is allowed to reach, supervision that tests traffic
  rather than liveness, detection from outside the failure domain, administrative access
  during an outage, and how certificates keep renewing once the hostname moves.

### Modified Capabilities

- `service-runtime`: its first requirement is scoped to background tasks *inside the gateway
  process*. It is written broadly enough ("any long-running background task") to be read, a
  year from now, as governing the tunnel connector too — which it does not: that one is a
  separate process supervised by systemd, with a different mechanism and different evidence.

## Impact

- `deploy/` — a unit for the tunnel, its key material, and the server block on `mprz.ru`.
- DNS for `sms.deralsem.ru` — target changes; nothing changes at failover thereafter.
- `mprz.ru` — a new server block and a certificate. It carries every other service in the
  estate, so the change must be additive and contained rather than a rework of its entry
  point.
- Home nginx — the `sms.deralsem.ru` block eventually binds to the tunnel address instead of
  the public one. `nas.deralsem.ru` shares that nginx and its renewal, and must be untouched.
- No application code is expected to change, except binding uvicorn to the loopback and
  recording where each request came from.

## Depends on

- `mprz.ru` being available to host the far end, which it is, and which is also where GM+
  runs — so its loss takes the gateway's callers with it. That shared fate is what makes it
  acceptable as the single way in: an unreachable gateway with no one left to call it is not
  an outage anyone experiences.
- The existing operator-alert mechanism in `deploy/` (`notify-telegram.sh`, the
  `OnFailure=`/`StartLimit*` pattern in `sms-gate.service`), which is what makes the
  supervision requirements achievable without new code.
