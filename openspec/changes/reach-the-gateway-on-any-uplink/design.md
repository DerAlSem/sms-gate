## Context

`gateway.example.com` resolves to the house today, unproxied. Requests land on nginx, which
terminates TLS with a Let's Encrypt certificate and proxies to `127.0.0.1:30080`. That nginx
also serves `neighbour.example.com` and shares one renewal timer with it.

The backup uplink works and fails over on route metrics after roughly ninety seconds. It is
behind CGNAT, which is why none of this is solvable by pointing a record anywhere.

`edge.example.com` is a machine on a static address, running nginx, in the same estate — and it hosts
the application that calls this gateway.

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

### The far end is `edge.example.com`, and the reason is not cost

The first draft chose a third-party edge and recorded the price as "the provider terminates
TLS and sees PIN codes". The critique found that accounting to be wrong, and wrong in the
direction that mattered: through that edge also travel the applications' bearer tokens and the
admin interface's credentials, and behind the admin interface sit sending, the whole message
history, and the settings. A leaked PIN expires in a minute. A leaked token does not.

The owner had accepted a trade described smaller than it was. Once the far end is a machine in
the same estate, the trade disappears rather than being weighed — nothing is shown to anyone
who was not already trusted with all of it.

The availability argument then inverts too. A far end that could fail independently would be a
new single point of failure; this one hosts the calling application, so its loss takes the gateway's callers with
it. An unreachable gateway that no one is left to call is not an outage anyone experiences.
That shared fate, not the saving, is what makes one way in acceptable.

### Terminating TLS at the far end, not passing it through

Passing TLS through — forwarding raw TCP into the tunnel and terminating at home — is
attractive on two counts: nothing, not even `edge.example.com`, sees plaintext, and the certificate
story does not change at all, because the existing challenge keeps arriving through the tunnel
and the home nginx keeps its own configuration.

It is rejected because of what `edge.example.com` is, and the files say so rather than the guess that
first said it. Its nginx serves a dozen hostnames, every one of them on `listen 443 ssl` in the HTTP context, and there is no stream section at all. Passing
through by hostname would mean converting that single listener into a stream with SNI
inspection: touching the entry point of every service in the estate for the sake of one. The
blast radius of a mistake there is everything, and what is gained is protection from a machine
we already trust with all our own secrets.

Terminating at the far end is instead a new server block beside the existing ones: additive,
contained, unremarkable to its neighbours, and a certificate of the kind it already issues for all of them.

The second half of the original argument turned out to be false and is withdrawn. It said
renewal at the house would break because the tunnel takes port 80. Renewal there is validated
over DNS and always has been, so it never depended on being reachable at all. That removes a
whole group of work — and it removes a hazard the critique had raised against the rollback
path, which was that a certificate quietly failing to renew would take the fallback with it.
It cannot: the fallback's certificate renews whether or not anything can reach the house.

### The direct path is retired in two stages

The first draft claimed the tunnel would be the only way in, and simultaneously that the
direct path stayed able to serve so rollback was one step. Both cannot hold: port 443 on the
house answers anyone who knows the address and sets the header, whatever a record says. The
risk analysis was written against the claim, and the configuration disagreed with it.

The resolution is that both are true, in sequence. Through the soak the direct path serves and
rollback is one action, because the new path has proven nothing yet. Afterwards it is retired
and the claim becomes true.

Retirement is done by binding the hostname's server block to the tunnel address rather than by
closing ports, because `neighbour.example.com` shares that server and needs both ports to keep
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
- **`edge.example.com` becomes load-bearing for this gateway.** → Accepted on shared fate: it hosts the
  caller. This would not be acceptable if the callers lived elsewhere.
- **The direct path rots while it is still the rollback.** → Its serving ability is checked
  during the soak rather than assumed, and it is retired afterwards, so the rot has a
  deadline.
- **Alerting shares a throttle across senders.** → A flapping uplink and a flapping connector
  would suppress each other exactly when both are failing. Covered by a requirement rather
  than left to be discovered during the first real outage.
- **Touching `edge.example.com` risks every other service on it.** → The change there is additive: one
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

## Settled during reconnaissance

- **The certificates are separate, not one covering several.** Read off the wire:
  `gateway.example.com` is its own certificate with itself as its only subject alternative name.
  One broken renewal cannot take another with it, so the renewal migration needs no special
  care on that account.
- **Renewal on the home server is already failing, and was before this change existed.**
  `neighbour.example.com` resolves to a third machine now, so its challenge is delivered somewhere
  else and the timer exits in failure on every run. This is not ours, but it is in our way:
  moving `gateway.example.com` produces exactly the same symptom, and a new failure hiding behind
  an existing one is a failure nobody investigates. It is cleared first so that afterwards a
  red timer means something.
- **Renewal at the house is validated over DNS, not over an inbound challenge.** The premise
  that the tunnel would break it was wrong and is withdrawn, together with the work it
  implied. Noted rather than dropped, because it carries a real risk that predates this
  change: the credential enabling it can edit the zone that decides where this hostname
  points, so a compromise of the house is already a hijack of the name. That is worth its own
  look at the token's scope, and it is not this change's to fix.
- **`edge.example.com` already runs WireGuard, and only one of its two interfaces is ours.** `wg0` is
  how the bots reach Telegram — `edge.example.com` is a *client* on it and its allowed addresses are
  Telegram's ranges through a foreign endpoint. `wg-edge` is the estate's own, with
  `edge.example.com` as its server and one peer already on it, confined to a single address. The house
  joins there, which means the constraint this change requires is the convention that
  interface already follows rather than something imposed on it.

  The constraint that does *not* come free is on the house's side. A default route into the
  tunnel — the value most guides supply — would send everything the house emits through
  `edge.example.com`, including the gateway's outbound webhooks and the probes by which the uplink
  watchdog decides whether the wired link is alive. Failover would then be reacting to the
  tunnel's health instead of the link's, which inverts the relationship this change is built
  on: the tunnel is supposed to ride whichever uplink is chosen, never to choose it.

## Open Questions

- **What is the measured re-establishment time?** To be measured on the rig that already
  exists, then written into the spec as a figure.
