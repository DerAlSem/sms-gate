## Context

The host is reached today at `sms.deralsem.ru`, a `CNAME` to `home.deralsem.ru` resolving
to the wired address, unproxied. Requests land on nginx, which terminates TLS with a
Let's Encrypt certificate and proxies to `127.0.0.1:30080`. nginx does nothing else for this
hostname: a redirect from port 80, TLS, `Host` and `X-Real-IP`.

A Cloudflare Tunnel already exists on the host — `3efe69fe-…`, credentials in place, ingress
`sms.deralsem.ru → http://127.0.0.1:30080`, connector 2026.7.3 installed. It has never been
run, has no unit, and no record points at it. The zone is on Cloudflare's nameservers.

The backup uplink works and fails over on route metrics after roughly ninety seconds. It is
behind CGNAT, which is why none of this can be solved by pointing a record anywhere.

## Goals / Non-Goals

**Goals:**

- The hostname answers while any uplink is up.
- The host is administrable during an outage, not only after it.
- The failure of the new component is louder than the failure it replaces.

**Non-Goals:**

- Changing how failover decides which uplink carries traffic. That is `backup-uplink`'s
  job and it works.
- Load balancing, or serving from both paths at once.
- Hiding the privacy cost. It is a decision, recorded, not a detail.

## Decisions

### The tunnel runs always, and DNS never moves

The alternative — direct normally, tunnel on failure — was the shape originally proposed and
was rejected on three grounds, of which the third is decisive.

It starts a component at the moment the network has just degraded. It needs the record
switched and switched back, and propagation is not ours to control, so both transitions
carry a window where the hostname resolves somewhere that cannot answer; an unstable primary
makes that a flap. And it produces a path that is exercised only by the incident it exists
to survive. This project has now been bitten twice by exactly that: a reader loop that died
in silence, and a backup channel that reported itself connected while carrying nothing. A
third instance of the same shape, deliberately built, would be hard to defend.

Always-on inverts it: the tunnel is exercised by every request, and failover becomes
invisible at the addressing layer because there is nothing to switch.

### The price is paid at the edge, and it is the real one

Cloudflare terminates TLS, so it sees request bodies — including the PIN codes this gateway
exists to deliver. Today TLS ends on our own nginx and nothing leaves the host in clear.

This is the change's actual cost, and it is not recoverable by configuration: it follows from
the topology. The owner accepted it explicitly, against the alternative of a VPS carrying
WireGuard, which keeps TLS end-to-end at the cost of a machine to run, pay for and patch.

It is written here, in the specs and in the proposal, because a decision of this kind
discovered later in a config file reads as an accident.

### The tunnel becomes a single point of failure, and that has to be paid for

Before this, reachability failed exactly when the wired link failed — obvious, and the same
event the operator was already watching. Afterwards a single process is the only way in, and
its death is invisible: the link is fine, the service answers on its own port, every existing
health check passes, and nothing outside can reach it.

That is the same silent-and-total shape the modem work spent two changes eliminating, so it
is not acceptable to introduce it untreated. Supervision with automatic restart handles the
transient case; an alert handles the case supervision cannot fix. The bar is that this
component's failure is at least as visible as the failure it replaced.

### Administrative access is part of the change, not a follow-up

An outage that leaves the service running and the host unreachable is half a remedy — the
gateway answers while the reason it failed over cannot be looked at. The existing route is a
port on the wired address and dies with it.

The connector supports an `ssh://` ingress. The vendor's documentation is explicit that
non-HTTP services need the connector on the *client* side too, so this is not "ssh keeps
working" — it is a second, deliberate route with client-side setup, and the design has to say
so rather than imply the old command still works.

It also has to be gated. An SSH ingress without an access policy is reachable by anyone who
learns the hostname, which would trade an outage for an exposure — a bad trade even once.

### Certificate renewal has to move before it breaks, not after

Renewal answers a challenge on port 80 of the wired address. Once the hostname is a proxied
record, port 80 from outside belongs to the tunnel, whose ingress answers `404` for anything
that is not the service. The challenge is delivered to nothing.

The failure is silent and deferred by up to ninety days, which makes it the most likely thing
in this change to be discovered by an outage rather than by us. It is treated as part of the
work, with renewal *proved* on the new arrangement rather than assumed, and with the
neighbouring hostname on the same timer verified to still renew.

Two shapes are available: move the challenge to DNS-01 with a scoped API token, or keep
`/.well-known/acme-challenge` routed to nginx through the tunnel's ingress. The first removes
the dependency on inbound entirely and is the better fit for a host whose inbound path is now
a tunnel; the second is smaller. The choice is made during implementation against which one
can be *proved* on the day, not by preference.

## Risks / Trade-offs

- **Cloudflare sees plaintext.** → Accepted by the owner, recorded in three places so it
  cannot be rediscovered as a surprise. The alternative topology is named and costed.
- **One process is now the only way in.** → Supervised, restarted, alerted on. Rollback to
  the direct path is kept to one step precisely because this risk is real.
- **The connector's failover behaviour is unmeasured.** → Made a verification task with the
  rig that already exists: the modem can be unbound from USB and the wired link can be
  pulled. A recovery-time figure that comes from documentation rather than measurement is
  not accepted.
- **The direct path stops being exercised.** → It stays configured and able to serve, which
  is what makes rollback one step; but it will rot in the same way the tunnel would have
  under the rejected design. Rollback is therefore a documented action to be *checked*, not
  assumed to work when needed.
- **`X-Real-IP` is no longer set for this hostname.** → Checked before the cutover, not
  after; the header the edge supplies has a different name.

## Accepted gaps

- **Cloudflare is now in the availability path at all times.** An edge outage takes the
  gateway's inbound with it even when the house, the modem and the service are all healthy.
  This is inherent to the chosen topology and is the counterpart of the privacy cost: both
  were bought together, deliberately.
- **The window across a failover is not zero.** Roughly ninety seconds of failover detection
  plus however long the connector takes to dial out again. The change measures it rather than
  removing it; making it shorter is a different piece of work on the uplink's thresholds.

## Open Questions

- **DNS-01 or an ingress route for the ACME challenge?** Settled during implementation by
  which one can be demonstrated renewing, not by preference.
- **What is the actual unreachable window across a failover?** To be measured, then written
  into the spec as a recorded figure.
