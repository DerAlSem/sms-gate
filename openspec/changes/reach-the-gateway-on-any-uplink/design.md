## Context

`sms.deralsem.ru` resolves to the house today, unproxied. Requests land on nginx, which
terminates TLS with a Let's Encrypt certificate and proxies to `127.0.0.1:30080`. That nginx
also serves `nas.deralsem.ru` and shares one renewal timer with it.

The backup uplink works and fails over on route metrics after roughly ninety seconds. It is
behind CGNAT, which is why none of this is solvable by pointing a record anywhere.

`mprz.ru` is a machine on a static address, running nginx, in the same estate — and it hosts
GM+, the application that calls this gateway.

The first draft of this change was written around a third-party tunnel; `critique.md` records
what two critic passes found in it. Most of those findings are about the shape rather than
the vendor and survive into this draft. One of them changed the topology, and is recorded
below.

## Goals / Non-Goals

**Goals:**

- The hostname is served by the gateway while any uplink is up.
- The host is administrable *during* an outage, not only afterwards.
- The new component's failure is at least as visible as the failure it replaces.

**Non-Goals:**

- Changing how failover decides which uplink carries traffic. That is `backup-uplink`'s job
  and it works.
- Serving from both paths at once, or balancing between them.
- Shortening the failover window itself. It is measured here, not reduced.

## Decisions

### The tunnel runs always, and DNS never moves

The alternative — direct normally, tunnel raised on failure — was the shape originally
brought to this work and was rejected on three grounds, of which the third decides it.

It starts a component at the moment the network has just degraded. It needs the record
switched and switched back, and propagation is not ours, so both transitions carry a window
where the hostname resolves somewhere that cannot answer; an unstable primary turns that into
a flap. And it produces a path exercised only by the incident it exists to survive. This
project has been bitten twice by precisely that: a loop that died in silence, and a backup
channel reporting itself connected while carrying nothing. A third instance, built
deliberately, would be indefensible.

Always-on inverts it. The tunnel is exercised by every request, and failover becomes invisible
at the addressing layer because there is nothing to switch.

### The far end is `mprz.ru`, and the reason is not cost

The first draft chose a third-party edge and recorded the price as "the provider terminates
TLS and sees PIN codes". The critique found that accounting to be wrong, and wrong in the
direction that mattered: through that edge also travel the applications' bearer tokens and the
admin interface's credentials, and behind the admin interface sit sending, the whole message
history, and the settings. A leaked PIN expires in a minute. A leaked token does not.

The owner had accepted a trade described smaller than it was. Once the far end is a machine in
the same estate, the trade disappears rather than being weighed — nothing is shown to anyone
who was not already trusted with all of it.

The availability argument then inverts too. A far end that could fail independently would be a
new single point of failure; this one hosts GM+, so its loss takes the gateway's callers with
it. An unreachable gateway that no one is left to call is not an outage anyone experiences.
That shared fate, not the saving, is what makes one way in acceptable.

### Terminating TLS at the far end, not passing it through

Passing TLS through — forwarding raw TCP into the tunnel and terminating at home — is
attractive on two counts: nothing, not even `mprz.ru`, sees plaintext, and the certificate
story does not change at all, because the existing challenge keeps arriving through the tunnel
and the home nginx keeps its own configuration.

It is rejected because of what `mprz.ru` is. Passing through by hostname means restructuring
its port-443 listener into a stream with SNI inspection — touching the single entry point of
every other service in the estate for the sake of one. The blast radius of a mistake there is
everything, and the thing being gained is protection from a machine we already trust with our
own secrets.

Terminating at the far end is instead a new server block beside the existing ones: additive,
contained, and unremarkable to its neighbours. The cost paid is that renewal for this hostname
moves there too, which is ordinary work rather than a workaround.

### The direct path is retired in two stages

The first draft claimed the tunnel would be the only way in, and simultaneously that the
direct path stayed able to serve so rollback was one step. Both cannot hold: port 443 on the
house answers anyone who knows the address and sets the header, whatever a record says. The
risk analysis was written against the claim, and the configuration disagreed with it.

The resolution is that both are true, in sequence. Through the soak the direct path serves and
rollback is one action, because the new path has proven nothing yet. Afterwards it is retired
and the claim becomes true.

Retirement is done by binding the hostname's server block to the tunnel address rather than by
closing ports, because `nas.deralsem.ru` shares that server and needs both ports to keep
working. Firewalling would have taken the neighbour down with it.

### Rollback is a deliberate action, not an emergency remedy

Worth stating because the first draft implied otherwise. Rolling back restores a path that
works only over the wired link — so during a wired outage it cannot be used at all. It answers
"this topology turned out badly", never "it is down right now".

That is also the answer to the objection that the rollback path becomes an untested path, the
very argument used to reject the on-demand tunnel. The asymmetry is real: the on-demand tunnel
would have been exercised by automation in the middle of a degradation, while rollback is
exercised by a person who has decided to use it and can check it first. It is not an
untested path in the same sense — but it does need checking before it is relied upon, which
belongs in the tasks rather than in an assumption.

### The tunnel is constrained at both ends, by decision

A tunnel is a route by default. The far end carries every service in the estate and is the
most exposed machine there; the near end sits on a home network with file shares on it. Left
at defaults, an availability change silently becomes mutual network access between those two
— through an omission, not a decision.

So the addresses each end may reach are stated explicitly, and the requirement is written
against the property rather than the mechanism.

### Recovery time is ours to measure, not the connector's to promise

The first draft recorded this as an unmeasured vendor behaviour. The critique found the larger
factor to be our own: `wwan-backup.sh` installs a rule pinning traffic from the primary
interface's address to a table that fails over with it, so sockets established before an
outage are governed by something this project wrote — and part of that rule's stated purpose,
serving inbound connections over the primary interface, is what this change retires.

The figure recorded is therefore the time to re-establish, counted from when the new uplink is
carrying traffic. The full unreachable window is that plus the uplink's own detection
threshold, which belongs to `backup-uplink` and would otherwise make this figure a lie the
moment that threshold is tuned.

## Risks / Trade-offs

- **One path in, and it is a machine we do not watch from outside.** → Supervision tests
  carrying traffic rather than liveness, and a check from outside the failure domain is part
  of the change rather than a follow-up. Without the external check, the inside-out
  observability answers a question nobody is asking.
- **`mprz.ru` becomes load-bearing for this gateway.** → Accepted on shared fate: it hosts the
  caller. This would not be acceptable if the callers lived elsewhere.
- **The direct path rots while it is still the rollback.** → Its serving ability is checked
  during the soak rather than assumed, and it is retired afterwards, so the rot has a
  deadline.
- **Alerting shares a throttle across senders.** → A flapping uplink and a flapping connector
  would suppress each other exactly when both are failing. Covered by a requirement rather
  than left to be discovered during the first real outage.
- **Touching `mprz.ru` risks every other service on it.** → The change there is additive: one
  server block, one certificate, no rework of its entry point. This is the reason TLS
  terminates there rather than passing through.

## Accepted gaps

- **The window across a failover is not zero.** Roughly ninety seconds of detection plus the
  re-establishment time. This change measures it; shortening it is work on the uplink's
  thresholds and belongs to `backup-uplink`.
- **A degraded primary can satisfy the uplink's health check while failing the tunnel.**
  Failover tests ICMP to public resolvers over the primary interface; reachability now means
  the tunnel is established. A link where ICMP passes and TCP does not leaves both mechanisms
  believing themselves right. The external check is what surfaces it; correlating the two
  signals automatically is deliberately not attempted here.

## Open Questions

- **Are the neighbouring hostnames separate certificates or one covering several?** Decides
  whether one broken renewal can take the others with it, and therefore how much care the
  renewal migration needs.
- **What is the measured re-establishment time?** To be measured on the rig that already
  exists, then written into the spec as a figure.
