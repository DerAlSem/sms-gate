## ADDED Requirements

### Requirement: The gateway is reachable over whichever uplink is carrying traffic

The gateway SHALL be reachable at its public hostname while any uplink is up, including one
that has no public address of its own.

The backup uplink sits behind carrier-grade NAT. It has no address that can be resolved to,
and no port on it can be opened from outside — so reachability over it cannot be arranged
by pointing a record at it, however the record is managed. A connection dialled *outward*
from the gateway is the only shape that survives, because the return traffic rides a
connection the operator's network already permitted.

#### Scenario: The wired link is up
- **WHEN** the primary uplink is carrying traffic
- **THEN** the public hostname answers

#### Scenario: The wired link is down and the backup is carrying traffic
- **WHEN** the primary uplink has failed over to a backup that is behind carrier-grade NAT
- **THEN** the public hostname still answers, without the operator being reachable at an address of its own

### Requirement: The inbound path is permanently established, not raised on failure

The connection carrying inbound traffic SHALL be established at all times, not started in
response to an uplink failing.

Three reasons, and the third is the one that decides it. A path raised on demand is started
at the moment the network has just degraded, which is the worst available moment to start
anything. Its addressing has to be switched to and back, and record propagation is not
something the gateway controls, so both transitions carry a window in which the hostname
resolves to somewhere that cannot answer. And a path exercised only during an outage is a
path never exercised: it is tested for the first time by the incident it exists to survive
— which is the same class of fault as a reader loop that dies in silence, or a backup
channel that reports itself connected and carries nothing.

A permanently established path is exercised by every ordinary request.

#### Scenario: An uplink fails
- **WHEN** traffic moves from one uplink to another
- **THEN** no addressing record is changed, and no connection is raised that was not already running

#### Scenario: The uplink is restored
- **WHEN** the primary uplink comes back and traffic returns to it
- **THEN** again nothing is switched, and the hostname resolves to the same place throughout

### Requirement: The inbound path is supervised and its loss is loud

The process holding the inbound path open SHALL be supervised, restarted when it dies, and
SHALL raise an operator alert when it cannot be kept up.

This requirement exists because the change creates the exposure it addresses. Before it,
the gateway was reachable whenever the wired link was up, and losing that was as obvious as
losing the link. Afterwards, one process is the only way in: the wired link can be perfectly
healthy, the service can be answering on its own port, every existing health check can pass,
and nothing outside can reach it. Making the gateway depend on a new component obliges the
change to make that component's failure at least as visible as the failure it replaced.

#### Scenario: The connector dies
- **WHEN** the process holding the inbound path exits
- **THEN** it is restarted automatically

#### Scenario: The connector cannot be kept up
- **WHEN** it fails repeatedly rather than transiently
- **THEN** the operator is alerted, rather than the gateway being quietly unreachable while looking healthy

### Requirement: Administrative access survives the loss of the primary uplink

The operator SHALL be able to reach the host administratively while the primary uplink is
down, over the same outward-dialled path that carries the service.

An outage that leaves the service running but the host unreachable is half a remedy: the
gateway keeps answering while the reason it failed over cannot be looked at, logs cannot be
read, and nothing can be corrected until the wired link returns on its own. The existing
administrative route is a port on the primary uplink's address and dies with it.

Administrative access published this way SHALL be gated by an access policy. Publishing it
otherwise makes it reachable by anyone who learns the hostname, which trades an outage for
an exposure.

#### Scenario: The wired link is down
- **WHEN** the operator needs to reach the host during a primary-uplink outage
- **THEN** administrative access is available over the tunnelled path

#### Scenario: Someone else learns the hostname
- **WHEN** a request for administrative access arrives without satisfying the access policy
- **THEN** it is refused before reaching the host

### Requirement: Certificates continue to renew once the direct path stops serving the hostname

Certificate renewal SHALL continue to work after the public hostname stops being served
over the direct inbound path, and the change SHALL prove renewal before the current
certificate expires rather than after.

Renewal today answers a challenge delivered to port 80 of the operator's address. Moving
the hostname to an outward-dialled path takes that port away from outside, so the challenge
is delivered to the tunnel and answered by nothing. The failure is silent and deferred: it
surfaces up to ninety days later, as an expired certificate, with nothing having changed on
the day it broke.

Renewal is shared with other hostnames on the same host, and those SHALL keep renewing.

#### Scenario: Renewal runs after the hostname has moved
- **WHEN** the renewal timer next fires
- **THEN** it succeeds, by a challenge type that does not depend on the direct inbound path

#### Scenario: Another hostname shares the renewal
- **WHEN** a hostname unrelated to this change renews
- **THEN** it is unaffected

### Requirement: The inbound path survives its uplink changing underneath it

The inbound path SHALL re-establish itself when the uplink carrying it is replaced, and the
time it takes SHALL be measured rather than assumed.

Failing over changes the address traffic leaves from, so every connection the path holds to
the outside is broken by the failover itself. Whether the connector notices, and how long it
takes to dial out again, decides the real recovery time — and it is not stated by the
connector's documentation, so it is a fact to be established on the hardware, not a
behaviour to be relied upon in advance.

The measured recovery time SHALL be recorded, so that the gateway's unreachable window is a
known quantity rather than a hope.

#### Scenario: The uplink is replaced under a running connection
- **WHEN** traffic fails over while the inbound path is established
- **THEN** the path re-establishes itself over the new uplink without intervention

#### Scenario: The recovery time is claimed
- **WHEN** the change states how long the gateway is unreachable across a failover
- **THEN** the figure comes from a measurement on the hardware, not from the connector's documentation

### Requirement: Rollback to the direct path is one deliberate step

Reverting to being reached over the direct inbound path SHALL be a single, documented
action, and the direct path SHALL be left able to serve.

This change removes the only way the gateway has ever been reached and replaces it with a
new one whose behaviour under failover is, at the time of the change, unmeasured. A remedy
that requires reconstruction under pressure is not a remedy.

#### Scenario: The new path proves unsuitable
- **WHEN** the operator decides to return to being reached directly
- **THEN** one documented change restores it, without the direct path having to be rebuilt first
