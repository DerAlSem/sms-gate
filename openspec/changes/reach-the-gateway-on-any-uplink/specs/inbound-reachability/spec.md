## ADDED Requirements

### Requirement: The gateway is reachable over whichever uplink is carrying traffic

The gateway SHALL be reachable at its public hostname while any uplink is up, including one
that has no public address of its own.

The backup uplink sits behind carrier-grade NAT. It has no address that can be resolved to
and no port on it can be opened from outside, so reachability over it cannot be arranged by
pointing a record anywhere. A connection dialled *outward* is the only shape that survives,
because its return traffic rides a connection the carrier's network already permitted.

A response produced by the far end of that path — an error page, a gateway timeout, anything
generated because the gateway could not be reached — SHALL NOT satisfy this requirement. The
distinction is the whole point: a name that answers with someone else's error is a name that
answers, and a requirement that accepts it cannot tell service from outage.

#### Scenario: The wired link is up
- **WHEN** the primary uplink is carrying traffic
- **THEN** a request to the public hostname is served by the gateway itself

#### Scenario: The backup uplink is carrying traffic
- **WHEN** the primary uplink has failed over to a backup behind carrier-grade NAT
- **THEN** a request to the public hostname is still served by the gateway itself, without the house being reachable at an address of its own

#### Scenario: The gateway cannot be reached through the path
- **WHEN** the far end is up but the tunnel to the gateway is not
- **THEN** the requirement is not satisfied by the far end's own error response

### Requirement: The inbound path is permanently established, not raised on failure

The connection carrying inbound traffic SHALL be established at all times, and SHALL NOT be
started in response to an uplink failing.

Three reasons, and the third decides it. A path raised on demand is started at the moment the
network has just degraded, which is the worst available moment to start anything. Its
addressing has to be switched to and back, and propagation is not the gateway's to control,
so both transitions carry a window in which the hostname resolves somewhere that cannot
answer. And a path exercised only during an outage is a path never exercised — tested for the
first time by the very incident it exists to survive, which is the same class of fault as a
loop that dies in silence or a data session that reports itself connected while carrying
nothing.

A permanently established path is exercised by every ordinary request.

#### Scenario: An uplink fails
- **WHEN** traffic moves from one uplink to another
- **THEN** no addressing record changes, and no connection is raised that was not already running

#### Scenario: The uplink is restored
- **WHEN** the primary uplink returns and traffic moves back
- **THEN** again nothing is switched, and the hostname resolves to the same place throughout

### Requirement: The inbound path is supervised on whether it carries traffic

Supervision of the inbound path SHALL test that the path is *carrying traffic*, not merely
that its process is running, and SHALL restart it when it is not.

Process death is the easy half and not the likely one. The failure that has actually cost
this project two changes is the other shape: a component that reports itself healthy and
moves nothing — a data session `connected` over an interface with no address, a background
loop terminated with its exception discarded. A tunnel connector has the same property. Its
process can be alive, its unit active and every existing check green, while it holds no
registered connection to the far end and nothing reaches the gateway.

Supervision SHALL therefore rest on evidence from the path itself.

#### Scenario: The connector dies
- **WHEN** the process holding the inbound path exits
- **THEN** it is restarted automatically

#### Scenario: The connector is alive and carrying nothing
- **WHEN** the process is running and its unit is active, but the path holds no established connection to the far end
- **THEN** this is treated as a failure of the path rather than as health

### Requirement: The operator is told when the inbound path cannot be kept up

Failure to keep the inbound path established SHALL raise an operator alert, and the point at
which repeated failure becomes an alert SHALL be stated in numbers rather than left to
judgement.

This requirement exists because this change creates the exposure it addresses. Before it, the
gateway was reachable whenever the wired link was up, and losing that was as obvious as losing
the link. Afterwards a single path is the only way in: the link can be healthy, the service
can be answering on its own port, every existing check can pass, and nothing outside can
reach it. Depending on a new component obliges the change to make that component's failure at
least as visible as the failure it replaced.

An unbounded restart loop is not a failure state, so a supervisor left to restart for ever
raises nothing. The bound is what turns a loop into an alert.

#### Scenario: A transient failure
- **WHEN** the path drops once and is re-established
- **THEN** it is restarted, and no alert is raised

#### Scenario: Failure that persists
- **WHEN** re-establishing fails as many times within a window as the stated bound allows
- **THEN** the operator is alerted, rather than the gateway remaining quietly unreachable while looking healthy

### Requirement: Loss of reachability is detected from outside the failure domain

The gateway's reachability SHALL be tested from outside the network that carries it, and
that test SHALL alert by a route that does not depend on the gateway being reachable.

Everything watching this gateway today runs on the gateway. That answers "is the process up"
and never "does the name answer from the internet", and the two diverge exactly when it
matters: a fault at the far end — its server block, its certificate, its own outage — is
indistinguishable from perfect health when viewed from inside the house. So is a tunnel that
is registered and mis-routed.

An observer inside the failure domain cannot report the failure domain being unreachable.

#### Scenario: The far end stops serving the hostname
- **WHEN** the gateway is healthy and the far end no longer routes the hostname to it
- **THEN** the operator is told, though nothing on the gateway is wrong

#### Scenario: Nothing is wrong
- **WHEN** the gateway is reachable
- **THEN** the check passes without producing noise

### Requirement: The tunnel joins two endpoints, not two networks

The tunnel SHALL be constrained, at both ends, to the addresses and services it exists to
carry, and SHALL NOT make the networks behind either end reachable from the other.

A tunnel is a route by default, not a port forward. The far end is the busiest and most
exposed machine in the estate — it carries every other service — and the near end sits on a
home network holding file shares and appliances that were never meant to face anything. An
availability change that quietly joins those two networks has traded an outage for a much
worse class of problem, and it does so through an omission rather than a decision.

Symmetrically, the gateway SHALL NOT be able to reach beyond what it needs at the far end.

#### Scenario: The far end is compromised
- **WHEN** something on the far end attempts to reach a host or port on the home network other than the published service
- **THEN** it cannot

#### Scenario: The published service
- **WHEN** the far end forwards a request for the published hostname
- **THEN** it reaches the gateway

### Requirement: Administrative access survives the loss of the primary uplink

The operator SHALL be able to reach the host administratively while the primary uplink is
down, over a path that does not depend on the primary uplink's address.

An outage that leaves the service running and the host unreachable is half a remedy: the
gateway keeps answering while the reason it failed over cannot be looked at, logs cannot be
read, and nothing can be corrected until the wired link returns of its own accord. The
existing administrative route is a port on the primary uplink's address and dies with it.

#### Scenario: The wired link is down
- **WHEN** the operator needs to reach the host during a primary-uplink outage
- **THEN** administrative access is available

#### Scenario: The path is published to others
- **WHEN** administrative access is carried by a shared machine
- **THEN** it is reachable only by the operator, not by anything else that machine hosts

### Requirement: The gateway stops answering for this hostname outside the tunnel, once the tunnel has earned it

After the inbound path has been proven in service, the gateway SHALL stop serving its public
hostname on any path other than the tunnel.

Until then it SHALL keep serving both, because a rollback to a path that has been dismantled
is not a rollback. Retiring the direct path on the day of the change would assert "the tunnel
is the only way in" while port 443 on the house still answered anyone who knew the address
and set the header — the claim and the configuration disagreeing, with the risk analysis
written against the claim.

Retirement SHALL NOT disturb the other hostnames the same server answers for.

#### Scenario: During the soak
- **WHEN** the tunnel is newly in service
- **THEN** the direct path still serves, and returning to it is one deliberate action

#### Scenario: After the soak
- **WHEN** the tunnel has been proven in service
- **THEN** a request arriving for this hostname other than through the tunnel is not served

#### Scenario: A neighbouring hostname
- **WHEN** the direct path is retired for this hostname
- **THEN** every other hostname on the same server is still served and still renews its certificate

### Requirement: The gateway records where a request came from

Every request SHALL be recorded with the address it originated from, as reported by the path
that carried it.

Nothing records this today. That was survivable while reaching the gateway meant being on the
house's network or knowing its address; it stops being survivable when there is one public
entrance and the credentials behind it are long-lived. An application token used from
somewhere it has never been used from is indistinguishable from an ordinary call, and the
only trace that would have shown it disappears at exactly the moment it becomes necessary.

The address SHALL be taken from the header the forwarding path supplies, since the connection
the gateway itself sees is the tunnel's.

#### Scenario: A request arrives through the tunnel
- **WHEN** the gateway serves a request forwarded from the far end
- **THEN** the originating address is recorded, not the tunnel's

### Requirement: Certificates keep renewing on both machines

Every hostname served by either machine SHALL continue to renew its certificate after the
public hostname moves.

The hostname acquires a second certificate — one at the far end that now terminates it, one at
the house that keeps the fallback able to serve — and a certificate that silently stops
renewing fails up to ninety days later, with nothing having changed on the day it broke.

A machine carrying many hostnames renews them together, so a renewal broken by this change is
not confined to this change's hostname. This requirement is what keeps that from being noticed
by an outage on somebody else's site.

#### Scenario: Renewal runs after the hostname has moved
- **WHEN** the renewal next runs on either machine
- **THEN** it succeeds

#### Scenario: A neighbouring hostname renews
- **WHEN** a hostname unrelated to this change renews
- **THEN** it renews successfully

### Requirement: Reachability survives a restart of the host

The inbound path SHALL be established again after the host restarts, including when the
primary uplink is already down at the time it starts.

A cold start is where unit ordering, enablement and dependence on an interface that is not up
yet all come due at once — and a host that comes back without its only entrance is unreachable
with no one able to tell, which is the same silent failure the supervision requirements exist
to prevent. The case that matters most is the one that will actually happen: a restart during
an outage, when the path must come up over the backup uplink rather than the wired one.

**Measured on 2026-08-01: about three minutes with the uplink dead from boot, and no
intervention.** Counted from boot: the tunnel interface exists at 14 seconds, the backup
session at 15, the first uplink check at 90, failover at 154, the far end's name resolves at
164, and the hostname is served over the backup by 187. With the uplink healthy the path is
back as soon as the host is.

Almost all of that is the uplink's own detection threshold — the first check waits ninety
seconds after boot and two more intervals must fail — so the figure to plan against is that
threshold, not anything this path does. What the figure hides is that the tunnel unit spends
those minutes blocked retrying name resolution rather than failing, and recovers because the
retry outlives the threshold by ten seconds. That margin is not designed and not documented,
which is why it is named as work rather than recorded as a property.

#### Scenario: An ordinary restart
- **WHEN** the host restarts with the primary uplink healthy
- **THEN** the inbound path is established without intervention

#### Scenario: A restart while the primary uplink is down
- **WHEN** the host restarts while traffic is on the backup uplink
- **THEN** the inbound path is established over it

### Requirement: The restart path does not rest on an undocumented margin

The moment the backup uplink can first take over after a restart SHALL be stated where it is
configured, and every other boot-time delay that assumes it SHALL be derived from it rather
than chosen independently.

On a restart with the primary uplink already dead there is no DNS: the backup's resolvers are
activated only on failover, so nothing can resolve a name until the uplink switches. The
tunnel is configured by hostname, and what carries it across that gap is not anything this
project built — the tunnel tool does not fail on an unresolvable endpoint, it blocks in its
own retry loop. Measured on 2026-08-01 it retried for 143 seconds and succeeded 10 seconds
after the failover freed DNS.

That margin is the whole of the cold-start path, and neither side knows about the other. The
retry budget belongs to a third-party tool, is not documented, and can change with a package
upgrade. The failover floor is the sum of two numbers in a timer that reads like a local
tuning decision. Raise either, or meet a build that gives up sooner, and the tunnel unit fails
instead of waiting — after which recovery falls to the tunnel watchdog and costs minutes
rather than seconds, with the host unreachable throughout.

Stating it is what can honestly be done: the dependency cannot be removed while the endpoint is
a name and DNS waits on failover, and both of those are wanted for other reasons. What must not
happen is that the margin is shortened by someone who had no way to know it existed.

#### Scenario: The uplink's failover timing is changed
- **WHEN** the first-check delay or the failure threshold of the uplink watchdog is changed
- **THEN** the derived boot-time delays that assume the old figure are changed with it

#### Scenario: A restart with no uplink but the backup
- **WHEN** the host restarts with the primary uplink dead
- **THEN** the tunnel is carrying without intervention, and without the operator having had to start it

### Requirement: The inbound path re-establishes itself when its uplink is replaced

The inbound path SHALL re-establish itself when the uplink carrying it changes, and the time
it takes to do so SHALL be a measured figure.

Failing over changes the address traffic leaves from, so the failover breaks every connection
the path holds. Whether the connector notices and how quickly it dials out again is not
stated by its documentation, and is in any case not the only factor: the gateway's own source
routing pins traffic from the primary interface to a table that fails over with it, so
sockets established before the outage are subject to a rule this project wrote. The figure is
therefore ours to measure, not the vendor's to promise.

What is recorded SHALL be the time to re-establish, counted from the moment the new uplink is
carrying traffic. The window during which the gateway is unreachable is that figure plus the
uplink's own detection threshold, which belongs to the uplink.

**Measured on 2026-07-30: under five seconds, and possibly none.** Sampling every five
seconds across a failover in both directions recorded no interrupted request at all — the
return to the primary uplink was covered continuously and showed no gap; the departure was
confirmed carrying within eighteen seconds, that being the resolution of the record rather
than a delay observed. The mechanism explains it: the session survives an address change, so
there is no handshake to redo — the far end learns the new endpoint from the first
authenticated packet. The figure to plan against is therefore the uplink's own detection
threshold, roughly ninety seconds, and not this.

#### Scenario: The uplink is replaced under an established path
- **WHEN** traffic fails over while the inbound path is up
- **THEN** the path re-establishes itself over the new uplink, without intervention, within the recorded time

### Requirement: An alert that cannot be delivered survives until it can

When no uplink can carry an alert, the evidence SHALL be retained and SHALL reach the
operator once a path exists.

The loudest failure is the one that silences its own reporting: with both uplinks down, the
connector restarts in a loop, the supervisor raises what it raises, and every alert takes the
path that is gone. Worse, the alert channel is shared and throttled across senders, so a
flapping uplink and a flapping connector suppress each other's messages and the operator
learns about neither.

#### Scenario: Nothing can carry an alert
- **WHEN** the operator cannot be reached while both uplinks are down
- **THEN** the evidence is retained rather than discarded, and is delivered once a path returns

#### Scenario: Two sources fail at once
- **WHEN** the uplink and the inbound path both fail in the same window
- **THEN** neither one's alerts suppress the other's
