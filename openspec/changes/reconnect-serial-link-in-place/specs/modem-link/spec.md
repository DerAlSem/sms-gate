## ADDED Requirements

### Requirement: A lost link is reopened in place before the service is restarted

The gateway SHALL attempt to reopen the serial port it lost, and SHALL restart the service
only when reopening has failed.

Reopening SHALL be attempted repeatedly with a delay between attempts, until a bounded
budget of **time** is spent, because what has to be waited out is the device's absence and
absence is a duration. A budget counted in attempts answers a different question: five
attempts three seconds apart is twelve seconds, which reads like a budget until it is
asked what it is a budget for.

That budget SHALL be at least the wait the gateway already applies to the same device at
startup. Both answer one question — how long can this device take to come back — and two
answers to one question drift apart, with the smaller one governing the path where it
matters more.

Each attempt SHALL additionally be bounded in time of its own, because a deadline for the
whole operation does not bound a single attempt that never returns: closing a transport
whose device has vanished, and opening a node udev is still finishing, can both block
indefinitely.

A device node that is absent, or present but not yet permitted to this process, SHALL be
treated as "not back yet" rather than as an error — a recreated node carries its ownership
and group only once udev has applied its rules, so the first attempts after a
re-enumeration can fail on permission rather than on absence.

Reopening SHALL take place with use of the modem suspended, on the gate that already
suspends sending and inbound reads during a recovery.

#### Scenario: The device returns after re-enumerating
- **WHEN** the link is lost and the device node reappears a few seconds later
- **THEN** the gateway reopens the port and resumes without restarting

#### Scenario: The device node is missing when reopening is attempted
- **WHEN** the first attempt finds no device node
- **THEN** the attempt fails without raising out of the loop, and another follows after the delay

#### Scenario: The node exists but is not yet permitted
- **WHEN** an attempt fails because the process may not open the node
- **THEN** it is treated the same as an absent node rather than as a fatal error

#### Scenario: An attempt blocks
- **WHEN** closing or opening the port does not return
- **THEN** the attempt is abandoned at its own bound and another follows

#### Scenario: The device takes longer to return than a few attempts
- **WHEN** the node is still absent after several attempts but within the budget
- **THEN** attempts continue, rather than the service being restarted over a device that is merely still coming back

#### Scenario: Reopening never succeeds
- **WHEN** the budget is spent with the device still gone
- **THEN** the gateway restarts the service, as it does today

### Requirement: A reopened link is not in service until its init sequence has completed

A reopened port SHALL have the full modem init sequence applied to it before it is
considered usable, and the URC subscription that delivers `+CDS` and `+CMTI` SHALL be part
of that sequence.

A port that opens successfully but is not re-initialised is the worst outcome available
here: it accepts commands, so every health check passes, while delivering no delivery
reports and no inbound notifications. Every message would expire and every inbound SMS
would be missed, and nothing would report a fault.

Reopening and initialising SHALL hold the serial lock for the whole operation, as one
indivisible act. No command may run against a port that is half replaced, and the init
sequence is itself made of commands — so it SHALL be issued through the path that assumes
the lock is already held, not the one that acquires it.

A reopen whose init sequence fails SHALL count as a failed attempt.

#### Scenario: The port reopens
- **WHEN** the gateway reopens the serial port after losing the link
- **THEN** the init sequence including the URC subscription is applied before the link is used

#### Scenario: The init sequence fails on a reopened port
- **WHEN** the port opens but the init sequence fails
- **THEN** the attempt is treated as failed and reopening continues

#### Scenario: A command arrives while the port is being replaced
- **WHEN** another caller issues a command during a reopen
- **THEN** it waits for the reopen to complete rather than acting on a half-replaced port

### Requirement: Reopening is cancellation-safe

Reopening SHALL leave the link either fully open and initialised, or explicitly marked
unusable — never in an undefined state, and this SHALL hold when the operation is
cancelled rather than completed.

Recovery runs under an outer timeout, so a reopen that takes too long is cancelled where it
stands — possibly between closing the old port and opening the new one — while the gate
that suspends sending is reopened regardless. Without this requirement the sender resumes
against a link whose reader and writer are gone, and discovers it one command timeout at a
time.

The reopening budget SHALL sit well inside the recovery timeout that wraps it, so
cancellation is the exception rather than the ordinary outcome.

#### Scenario: Reopening is cancelled part-way
- **WHEN** the operation is cancelled after the old port was closed and before the new one is open
- **THEN** the link is marked unusable rather than left appearing open

#### Scenario: Sending resumes after a cancelled reopen
- **WHEN** the gate reopens after a cancelled reopen
- **THEN** the next send fails immediately as a lost link rather than waiting for a timeout

### Requirement: A restored link is reconciled with the modem's stored messages

After the link is restored in place, the gateway SHALL read the messages the modem stored
while the link was down, as it does when it starts.

Inbound SMS accumulate in the modem's memory during an outage and the `+CMTI` notifications
announcing them are lost with the link. Today the only cure is the restart, whose startup
scan drains them. Replacing the restart with a reopen removes that scan, so without this
requirement the change would leave inbound messages unread until some later restart —
making inbound delivery worse than before, in the exact way this capability exists to
prevent.

Indexes queued before the outage SHALL NOT be relied upon in place of the scan, since they
cannot account for what arrived while nothing was listening.

#### Scenario: Inbound arrives during an outage
- **WHEN** SMS reach the modem while the link is down and the link is then restored in place
- **THEN** they are read and delivered without waiting for a restart

#### Scenario: A notification was queued before the link died
- **WHEN** an index was announced before the outage and not yet read
- **THEN** it is covered by the scan rather than lost or read twice

### Requirement: Re-reading the modem's memory does not deliver an inbound message twice

Reading a stored message SHALL NOT deliver it to the owning application more than once,
however many times the modem's memory is scanned.

A stored message is deleted from the modem only after it has been persisted, so an
interruption between the two leaves it in memory to be found again by the next scan. This
change increases how often scanning happens, which makes an existing latent duplicate
likely rather than rare.

#### Scenario: The link dies between persisting and deleting
- **WHEN** an inbound message is persisted and the link is lost before it is deleted from the modem
- **THEN** the next scan does not deliver it to the application a second time

### Requirement: The unsolicited-result port recovers on the same terms

The port carrying unsolicited results SHALL be recovered by the same mechanism as the
command port, not by a second implementation of its own.

That port is opened directly today, with no lock, no shared failure classification and no
awareness of the recovery gate. Giving it an independent reopen loop would produce two
bounded budgets that can each decide to restart the service, and a second reopen racing a
deliberate modem reset — the settling period after a hard reset exists precisely so that
nothing touches a rebooting modem.

It SHALL wait on the recovery gate before attempting anything, and its exhaustion SHALL
lead to the same outcome as the command port's.

Whether it needs its own init sequence SHALL be settled explicitly: it has no writer today
and therefore cannot issue the URC subscription, which is applied through the command port.

#### Scenario: Both ports are lost together
- **WHEN** a re-enumeration takes both ports
- **THEN** they are recovered once, in one coordinated operation, rather than by two independent loops

#### Scenario: A deliberate modem reset is in progress
- **WHEN** the modem is being reset and its ports drop
- **THEN** the unsolicited-result port does not attempt to reopen until the reset has settled

### Requirement: The link's state is visible where an operator looks

The gateway's health snapshot SHALL report the state of the link, when it was last known
good, and how often it has been reopened.

The admin page today reports what the gateway believes about the *modem* — whether it is
recovering, whether sends have stalled — and nothing about the link underneath. During the
incident the only external symptom was silence, and the only evidence was a traceback in
the journal. A link that is being reopened repeatedly is exactly the condition an operator
needs to see without reading logs.

#### Scenario: The link has been lost
- **WHEN** an operator opens the diagnostics page while the link is down or being reopened
- **THEN** the link's state, the time it was last good, and the number of reopens are shown
