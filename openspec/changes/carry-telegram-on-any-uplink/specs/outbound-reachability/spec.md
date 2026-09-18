## Purpose

The gateway reaching the outside services it depends on, over whichever uplink is carrying
traffic. Which route is tried in what order, which vendors the far-end relay is allowed to
carry, how that relay is proved alive while the ordinary route still works, and what happens
to a message no route could carry.

## ADDED Requirements

### Requirement: Every call to a vendor the backup uplink cannot reach goes through the relay first

The gateway SHALL send every request to a vendor known to be unreachable over the backup
uplink through the far-end relay first, falling back to the direct route only when the relay
does not answer. No caller SHALL hold that vendor's address as a compiled-in constant.

Relay-first is the ordering, not relay-only. The route that must survive the outage is the
route ordinary traffic should exercise; a path used only when things are broken is first
tested by the breakage. The direct route stays as the fallback, which also covers the relay
itself being down.

The constant is the part that has actually failed. Three raisers of alerts each carried their
own copy of the delivery path, and when the relay was added it reached two of them — the
third kept posting directly for months while a README and a ticked task both said otherwise.
Copies do not drift evenly; they drift in whichever one nobody remembers. A caller reading
the base from configuration cannot drift this way, and a caller with the vendor compiled in
cannot be brought back without an edit nobody knows is due.

#### Scenario: The relay answers
- **WHEN** the gateway calls a vendor covered by the relay
- **THEN** the call is made through the relay, whichever uplink is carrying traffic

#### Scenario: The relay does not answer
- **WHEN** a call through the relay fails
- **THEN** the direct route is tried before the call is reported as failed

#### Scenario: A caller that predates the relay
- **WHEN** any code path in the gateway calls such a vendor
- **THEN** it takes its base address from configuration rather than from a constant

### Requirement: The relay carries named vendors, not whatever it is given

The relay SHALL forward to vendor hostnames it names explicitly, SHALL admit only the
gateway, and SHALL NOT record request paths.

An open forwarder on a machine with a route to blocked destinations is a thing other people
would like to have, and it sits on the busiest and most exposed host in the estate. Naming
each destination keeps the relay's reach equal to the gateway's need rather than to the far
end's routing table.

Paths stay out of logs because these vendors carry credentials in the path. Logged, every
call writes a live token into a web server's access log, where it survives rotation and every
backup of it. The useful record of a delivery already exists at the sender.

Adding a vendor is an explicit change to the relay's configuration, which lives in this
repository rather than only on the far end — so what the relay carries can be read without
logging in to it.

#### Scenario: A vendor the relay names
- **WHEN** the gateway calls a vendor the relay is configured for
- **THEN** the call is forwarded to that vendor

#### Scenario: A destination the relay does not name
- **WHEN** a request arrives for any other destination
- **THEN** it is refused rather than forwarded

#### Scenario: Any forwarded call
- **WHEN** the relay forwards a call
- **THEN** no request path is written to a log

### Requirement: The relay is proved by a probe that cannot be answered by the ordinary route

The gateway SHALL verify on a schedule that the relay still carries traffic, and that check
SHALL address the vendor by an address the relay resolves rather than by a name resolved at
the gateway. Failure SHALL be reported to the operator.

A name is not evidence here. The home router intercepts DNS on the wired link:
`gatewayapi.telegram.org` answers `198.18.13.246`, an address belonging to the router's own
proxy, and asking the carrier's resolver explicitly returns the same substituted answer — the
interception is on the path, not in the choice of server. A probe that resolves a name at the
gateway therefore measures the router's proxy and reports success whatever the relay is doing.

This is the failure mode the check exists for. On the wired link the direct route works,
through a substitution this project does not control and cannot be told about when it changes.
The relay can be dead for months with no symptom, and the first witness would be an outage
during which nothing could be reported — the one occasion when the discovery is useless.

Supervision is on carrying traffic, not on a process being alive: "alive and moving nothing"
has already cost this project two changes.

#### Scenario: The relay has stopped carrying traffic
- **WHEN** the scheduled check runs while the relay cannot reach the vendor
- **THEN** the check fails and the operator is told

#### Scenario: The wired link is up and the direct route works
- **WHEN** the scheduled check runs on the primary uplink
- **THEN** it still exercises the relay rather than being satisfied by the direct route

### Requirement: An alert that cannot be addressed is not discarded quietly

When the gateway holds an alert it cannot deliver for want of its own configuration — no
credentials to send with, or nowhere to send to — it SHALL report that as a fault in a form
that does not depend on the missing configuration, rather than logging the alert and exiting
successfully.

Exiting zero makes a configuration fault look like a delivered alert to everything upstream.
Observed three times on 19 and 20 August 2026: `no alert credentials; would have said:` and
then the whole text of an alert nobody received. Nothing retried, nothing was held, and the
sender reported success to the unit that called it.

This is the same class as the failures this gateway's alerting was built to survive, and it
is worse than all of them, because the mechanism that would report it is the mechanism that
is broken. The report therefore SHALL go somewhere reachable without credentials — a failed
unit state, a non-zero exit, a file the operator's checks already read.

#### Scenario: Credentials are missing
- **WHEN** an alert is raised and the gateway has no credentials to deliver it with
- **THEN** the failure is reported by a means that needs no credentials, and the caller is not told the alert was sent

#### Scenario: Credentials are present but no route works
- **WHEN** an alert is raised, credentials exist, and neither the relay nor the direct route answers
- **THEN** the alert is held for later delivery rather than reported as a configuration fault
