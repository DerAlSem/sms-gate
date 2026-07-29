## Why

The backup uplink keeps the gateway able to reach the internet. It has never made the
gateway *reachable*: the operator sits behind CGNAT, so no inbound connection arrives over
it and no DNS record can be pointed at it. When the wired link goes, `sms.deralsem.ru`
stops answering even though the modem, the SIM and the service are all healthy — and the
box also stops being reachable over SSH, so the outage cannot be looked at.

A tunnel dialled *outward* is the only shape that works behind CGNAT. One is already
configured on the host and has never been run.

## What Changes

- The gateway is reached through a **permanently running** Cloudflare Tunnel rather than
  over a direct inbound connection. It is not opened on failure: a path used only during
  an outage is a path never exercised until it matters, and the moment the network has
  just degraded is the worst moment to start a component.
- **BREAKING for operations:** `sms.deralsem.ru` becomes a proxied `CNAME` to the tunnel.
  The direct path — port 443 on the home address, terminated by nginx — stops serving that
  hostname from outside. Rollback is putting the record back.
- **BREAKING for privacy:** TLS is terminated by Cloudflare, so request bodies — including
  the PIN codes this gateway exists to deliver — are visible to it. Accepted deliberately
  by the owner as the price of the simplest topology; recorded here because it is the kind
  of decision that must not be discovered later in a config file.
- Failover stops involving DNS at all. The record never changes, so there is no TTL window
  in either direction and no state machine to get right twice. Which uplink carries the
  tunnel stays the routing question the wwan watchdog already answers.
- **The tunnel becomes the only way in, and therefore a new single point of failure** for a
  service that today works whenever the wired link works. It is supervised and its death is
  made loud, because the failure it replaces was at least obvious.
- **Administrative access survives the wired link.** SSH is published through the same
  tunnel, gated by an access policy — an unprotected SSH ingress is reachable by anyone who
  learns the hostname.
- **Certificate renewal is migrated off the HTTP-01 challenge**, which the tunnel breaks by
  taking port 80 from outside. Left alone this fails silently and is discovered when the
  certificate expires.

## Capabilities

### New Capabilities

- `inbound-reachability`: being reachable from outside over whichever uplink is carrying
  traffic — the tunnel, its supervision, what happens when it dies, how administrative
  access survives an outage, and how certificates continue to renew once the direct path
  no longer serves the hostname.

### Modified Capabilities

None. `backup-uplink` keeps every requirement it has: this change adds no duty to the
uplink and takes none away. The two are deliberately separate — the uplink's job is that
*something* carries traffic, and this capability's job is that the gateway can be found
over whatever that turns out to be.

## Impact

- `deploy/` — a supervised unit for the tunnel connector, and its ingress configuration.
- DNS for `sms.deralsem.ru` — record type and target change; proxying is turned on.
- Certificate renewal — challenge type changes; `nas.deralsem.ru` shares the renewal
  timer and must not be broken by it.
- No application code is expected to change. `X-Real-IP` is no longer set by nginx for
  this hostname, so anything reading it must be checked before, not after.

## Depends on

Nothing in the repository. It depends on facts about the host that were verified rather
than assumed: the tunnel already exists and is configured, the zone is served by
Cloudflare's nameservers, and the connector is installed. The one thing not established
from the vendor's documentation — whether the connector survives its uplink changing
underneath it, and how quickly — is a verification task rather than an assumption.
