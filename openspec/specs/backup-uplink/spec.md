# backup-uplink Specification

## Purpose
TBD - created by archiving change fix-backup-uplink-recovery. Update Purpose after archive.
## Requirements
### Requirement: The backup uplink survives the modem being replaced underneath it

The backup uplink SHALL recognise that the modem it talks to has been replaced — the
device node recreated by a USB re-enumeration — and SHALL renew its access to it rather
than continue issuing requests against a handle that refers to a device which no longer
exists.

The QMI proxy the uplink talks through is a long-lived process holding its own descriptor
to the device. It is therefore subject to the same staleness as any other consumer, and
being a separate process it does not fail visibly when the device is replaced: requests
are accepted and then time out. Renewing access SHALL include renewing the proxy.

Renewal SHALL be triggered by requests *timing out*, not by requests being *refused*, and
only after several consecutive timeouts. The distinction is the whole safeguard: a refusal
such as `no-service` is the network answering, and restarting the proxy in response to it
would make an ordinary carrier-side outage escalate into repeatedly killing a process the
uplink does not own. Renewal SHALL itself be bounded by the same allowance as any other
retry, so it cannot become a loop.

The gateway and the backup uplink are two consumers of one piece of hardware, and a single
re-enumeration invalidates both at once. Neither SHALL assume the other has dealt with it.

#### Scenario: The modem re-enumerates
- **WHEN** the modem's device node is recreated while the uplink is running
- **THEN** the uplink renews its access to the device rather than issuing requests against the old one

#### Scenario: Requests begin timing out
- **WHEN** QMI requests that previously answered begin timing out
- **THEN** a stale device handle is treated as a candidate cause and access is renewed before the failure is reported as a network fault

### Requirement: The data session is established from the modem's configured profile

A cold start of the data session SHALL use the modem's default profile rather than
supplying the APN and IP type as explicit parameters.

This is the observed difference between working and not working. With no session
established, a start request carrying an explicit APN and IPv4 type was refused with
`no-service` for six hours continuously, while a request against the default profile
succeeded on the first attempt — with the profile holding the identical APN and an
identical IPv4 PDP type. The values were never in dispute; the form of the request was.

An explicit APN SHALL remain available as configuration, for the case where the modem's
profile has to be overridden, but SHALL NOT be the default path.

#### Scenario: The session is started with no session present
- **WHEN** the uplink establishes the data session after an outage
- **THEN** it starts from the modem's default profile

#### Scenario: The profile has to be overridden
- **WHEN** an explicit APN is configured
- **THEN** it is used instead of the default profile

### Requirement: A liveness check reports the session that actually exists

The check deciding whether the data session is already up SHALL report a session that is
in fact established.

A check that answers "no session" while one is running sends the uplink down its full
cold-start path — tearing the interface down and requesting a new session — every time it
runs, which is the opposite of the idempotence the check exists to provide.

#### Scenario: A session is running
- **WHEN** the liveness check runs against an established session
- **THEN** it reports the session as present and the cold-start path is not taken

### Requirement: A QMI client is acquired once and reused, not per attempt

The uplink SHALL hold at most one QMI client for session management, reusing it across
attempts, and SHALL record it where a later teardown can find it.

Releasing on the failure path is not sufficient and is not always possible: the client id
is read out of the *successful* reply, so a refused request frequently reports no id at
all and there is nothing to release. Reuse is the mechanism that makes the guarantee
achievable — a client acquired once cannot leak once per attempt however many attempts
fail.

The modem's pool of clients per service is finite and an unreleased client is not
reclaimed while the connection lives. Exhausting the pool takes the whole service down
rather than merely the attempt: every request against that service then times out and no
diagnosis is possible through it, while other services on the same modem keep answering
and make the modem look healthy. That is what turned a recoverable outage into one that
required rebooting the modem.

#### Scenario: Establishing the session fails
- **WHEN** a request to start the session is refused
- **THEN** no additional client is left held, whether or not the reply named one

#### Scenario: Repeated failures
- **WHEN** the session fails to establish many times in succession
- **THEN** the number of clients held by the uplink does not grow with the number of attempts

### Requirement: A failure of the data session does not disable the failover check

A failure anywhere in session management SHALL NOT prevent the watchdog from testing the
primary uplink and switching over when it is down.

These are two independent duties sharing one invocation: keeping the backup session alive,
and deciding which uplink carries traffic. Aborting the whole run when the first fails
means that during a QMI outage the primary link is never tested, its failure counters never
advance, and failover never happens.

The incident hid this because only one thing was broken. Had the home connection dropped
during those six hours, the backup would not have taken over and nothing would have said
why.

#### Scenario: The session cannot be established while the primary is healthy
- **WHEN** session management fails during a watchdog run
- **THEN** the primary uplink is still tested and its counters still advance

#### Scenario: Both fail at once
- **WHEN** the session cannot be established and the primary uplink is also down
- **THEN** failover to the backup is still attempted rather than skipped

### Requirement: A live session is not a working channel without its addressing

The uplink SHALL verify that its network interface actually carries the session's
addressing, and SHALL re-apply it when the interface has none, even while the data
session reports itself connected.

A re-enumeration recreates the network interface, and its address goes with it — while
the QMI session can survive and keep reporting `connected`. Every check the uplink makes
then passes and no traffic moves: the worst outcome available here, because it is
indistinguishable from a healthy backup channel until the day the primary link fails.

This was repaired by accident before the liveness check worked: a check that always
reported "no session" sent every pass down the cold-start path, which re-applies
addressing on its way through. Correcting the check removed the accident, which is how
the gap came to light.

#### Scenario: The interface loses its address but the session survives
- **WHEN** the data session reports connected and the interface has no address
- **THEN** the addressing is re-applied rather than the pass being treated as healthy

#### Scenario: An ordinary pass over a healthy channel
- **WHEN** the session is connected and the interface carries its address
- **THEN** nothing is re-applied

### Requirement: The network interface is confirmed present before it is configured

The uplink SHALL confirm its network interface exists before bringing it down, setting its
mode, or assigning addressing to it, in the same way it already confirms the control
device.

A re-enumeration recreates the network interface as well as the control device, and it may
be absent for a period or return under a different name. Addressing applied to an interface
that is not there fails quietly, leaving a session the uplink believes is up and no traffic
path — a state indistinguishable, from the logs, from a working backup channel.

#### Scenario: The interface has not reappeared yet
- **WHEN** the uplink runs while its network interface is absent
- **THEN** it reports the interface as missing rather than proceeding to configure it

### Requirement: Retrying is bounded and reports itself

Repeated automatic attempts to restore the uplink SHALL be bounded. On reaching the bound
the uplink SHALL stop retrying on its normal schedule, SHALL raise an operator alert, and
SHALL make its state visible, rather than continue indefinitely.

An unbounded retry is not persistence but self-harm: 131 consecutive failed attempts
consumed the modem's client pool and turned a recoverable fault into one that required
rebooting the modem. A mechanism that cannot succeed and cannot stop makes the problem it
was built to solve strictly worse.

A restored uplink SHALL reset the bound, so a later, unrelated outage gets its full
allowance.

#### Scenario: The uplink cannot be restored
- **WHEN** attempts to restore the uplink fail up to the bound
- **THEN** retrying stops on its normal schedule and the operator is told

#### Scenario: The uplink comes back
- **WHEN** an attempt succeeds
- **THEN** the bound is reset for any future outage

#### Scenario: A bounded retry does not consume the modem
- **WHEN** the bound is reached
- **THEN** the modem's client pool is no more depleted than the bound allows

