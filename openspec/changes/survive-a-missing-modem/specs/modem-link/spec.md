## ADDED Requirements

### Requirement: Serving the console does not depend on the modem

The gateway SHALL serve HTTP whenever its process is running, and reaching the modem
SHALL NOT be a precondition for that.

The admin console reads the database, not the modem, and it is where an operator goes to
find out what is wrong. Establishing the link during startup makes the modem a
precondition for the console, so the one condition the console exists to report — the
modem being unreachable — is the condition that takes the console away. On 2026-08-28 an
unplugged modem produced `502 Bad Gateway` and no explanation.

Establishing the link SHALL therefore happen outside the startup path, as work the
gateway does while already serving, and a failure to establish it SHALL NOT stop or end
the process.

#### Scenario: The gateway starts with no modem attached
- **WHEN** the process starts while no device node exists
- **THEN** it serves the API and the admin console, and does not exit

#### Scenario: The modem is attached later
- **WHEN** the device appears after the gateway has been serving without it
- **THEN** the link is established and the gateway begins sending and receiving, with no restart

#### Scenario: The console is reachable throughout
- **WHEN** an operator opens any admin page while the modem is unreachable
- **THEN** the page is served

### Requirement: Establishing the link is one operation, whenever it happens

Bringing the link into service SHALL be one operation with one definition of completion,
used both when the gateway first establishes it and when it is re-established after a
loss. It SHALL open the command port, open the port carrying unsolicited results, apply
the init sequence including the URC subscription, and reconcile the modem's stored
messages. An attempt that completes only part of this SHALL count as failed.

This requirement carries the weight the process restart used to carry. The restart was
the remedy that reliably worked precisely because it did all of these things in one
sweep; retiring it without naming that work here would remove a crude remedy and put
nothing in its place.

Two paths that each establish the link separately drift apart — they already did once,
when the startup wait and the reopen budget had to be pinned to each other by hand after
a prod incident. One path cannot drift from itself.

The gateway SHALL NOT treat the link as usable until the operation has completed.

#### Scenario: The link comes up for the first time
- **WHEN** the gateway establishes the link after starting without a modem
- **THEN** the init sequence including the URC subscription is applied and the modem's stored messages are reconciled, exactly as after a reopen

#### Scenario: The init sequence fails on a freshly opened port
- **WHEN** the ports open but the init sequence does not complete
- **THEN** the attempt counts as failed and the link is not put into service

#### Scenario: Inbound arrived while there was no link
- **WHEN** SMS reached the modem before the gateway could establish the link
- **THEN** they are read and delivered once it is established, without waiting for a restart

### Requirement: A gateway without a link does not report itself healthy

While the gateway has no usable link it SHALL say so wherever it reports its state, and
SHALL raise an alert when it enters that condition.

Removing the restart removes the one loud symptom an unreachable modem used to produce.
A process that sits serving pages while unable to send or receive anything, and says
nothing about it, is worse than one that exits: the outage becomes silent. The spec
already refuses a process that "keeps running while reporting itself healthy", and that
refusal SHALL survive the restart's removal.

The alert SHALL be raised on entering the condition rather than once per attempt, so a
long absence does not become a stream of notifications.

#### Scenario: The modem is unreachable
- **WHEN** the gateway is serving with no usable link
- **THEN** its health snapshot reports the link as unusable, together with when it was last good

#### Scenario: The link goes away
- **WHEN** the gateway loses the link, or fails to establish it at startup
- **THEN** an alert is raised once for that episode

#### Scenario: The link comes back
- **WHEN** the link is established again
- **THEN** the reported state clears and a further loss can alert again

### Requirement: A lost link is reopened in place, and reopening does not end

The gateway SHALL attempt to reopen the serial port it lost, repeatedly and without a
terminal deadline, until the link is established or the process is stopped.

Attempts SHALL be spaced by a delay, and the delay SHALL widen up to a ceiling so that a
device absent for hours neither spins the processor nor fills the journal. Attempts SHALL
NOT stop while the process runs: the gateway has no remedy beyond waiting for the device,
so a budget that expires only converts waiting into giving up.

Each attempt SHALL be bounded in time of its own, because a deadline for one attempt is
not supplied by the cadence around it: closing a transport whose device has vanished, and
opening a node udev is still finishing, can both block indefinitely.

A device node that is absent, or present but not yet permitted to this process, SHALL be
treated as "not back yet" rather than as an error — a recreated node carries its ownership
and group only once udev has applied its rules, so the first attempts after a
re-enumeration can fail on permission rather than on absence.

Reopening SHALL take place with use of the modem suspended, on the gate that already
suspends sending and inbound reads during a recovery.

#### Scenario: The device returns after re-enumerating
- **WHEN** the link is lost and the device node reappears a few seconds later
- **THEN** the gateway reopens the port and resumes

#### Scenario: The device node is missing when reopening is attempted
- **WHEN** an attempt finds no device node
- **THEN** the attempt fails without raising out of the loop, and another follows after the delay

#### Scenario: The node exists but is not yet permitted
- **WHEN** an attempt fails because the process may not open the node
- **THEN** it is treated the same as an absent node rather than as a fatal error

#### Scenario: An attempt blocks
- **WHEN** closing or opening the port does not return
- **THEN** the attempt is abandoned at its own bound and another follows

#### Scenario: The device is gone for a long time
- **WHEN** the device has been absent for hours
- **THEN** attempts continue at the ceiling interval, and the gateway keeps serving

#### Scenario: The device is returned after a long absence
- **WHEN** the device reappears after the delay has widened to its ceiling
- **THEN** the gateway establishes the link on the next attempt rather than needing to be restarted

## MODIFIED Requirements

### Requirement: A link absent at startup is the same fault as a link lost in flight

The gateway SHALL handle a port that cannot be opened when it starts on the same terms as
one lost while running, rather than failing to start.

The two are one fault seen at different moments, and the moment is not under the gateway's
control: a device that is re-enumerating takes longer to return than the gateway takes to
start. Treating the startup case as fatal converts the remedy into the failure — the
gateway starts, cannot open the port, exits, and repeats until its supervisor stops trying
altogether and the outage becomes indefinite.

Waiting for the device SHALL NOT be bounded by a deadline after which the gateway gives
up, at startup any more than in flight. Both moments are served by the same unending
reopen, so there is no bound left to reconcile with the supervisor's restart limits — the
gateway no longer spends them on an absent device.

#### Scenario: The port is absent when the service starts
- **WHEN** the gateway starts while the device node is not yet present
- **THEN** it serves HTTP and keeps trying for the device, rather than failing to start

#### Scenario: The device returns during startup
- **WHEN** the device appears while the gateway is waiting for it
- **THEN** the gateway opens it, completes its init sequence, and begins sending and receiving

#### Scenario: The device does not return
- **WHEN** the device is still absent long after the gateway started
- **THEN** the gateway keeps serving and keeps trying, reports the link as unusable, and does not exit

## REMOVED Requirements

### Requirement: The service is restarted when the link cannot be used

**Reason**: The restart cannot help when the device is genuinely absent — it reopens
nothing, and its only observable effect is to consume the supervisor's restart limits
until it stops trying, which is the indefinite outage this spec elsewhere warns against.
It also took the admin console down with it, so the operator lost the one page that could
have explained the fault.

**Migration**: The work the restart performed is now required of
`Establishing the link is one operation, whenever it happens` — the init sequence, the URC
subscription, and the reconciliation of the modem's stored messages. Queued messages need
no recovery step, since the sender reads them from the database and is now always running.
The refusal to run while reporting itself healthy is carried by
`A gateway without a link does not report itself healthy`.

### Requirement: A lost link is reopened in place before the service is restarted

**Reason**: Its terminal clause — reopening bounded by a budget that ends in a service
restart — is exactly what this change removes. Its remaining content (per-attempt bounds,
treating an unpermitted node as "not back yet", holding the recovery gate) is unchanged
and still required.

**Migration**: Replaced by `A lost link is reopened in place, and reopening does not end`,
which keeps every clause except the budget and the restart.
