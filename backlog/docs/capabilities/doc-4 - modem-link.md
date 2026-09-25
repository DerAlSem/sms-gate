---
id: doc-4
title: modem-link
type: specification
created_date: '2026-09-25 11:58'
updated_date: '2026-09-25 11:58'
---
# modem-link Specification

## Purpose
TBD - created by archiving change recover-from-serial-transport-loss. Update Purpose after archive.
## Requirements
### Requirement: A lost link is a different failure from a misbehaving modem

The gateway SHALL distinguish a failure of the serial link itself — the port cannot be
read or written at all — from a modem that answers badly or does not answer. The two
SHALL be separate classes, and the link failure SHALL NOT be a subtype of the AT failure.

This separation exists because the two have disjoint cures. Every remedy the gateway has
for a misbehaving modem is an AT command, and no AT command can reach a modem whose port
is gone; conversely, restarting the link does nothing for a radio that is merely
unregistered.

Making the link failure a subtype would defeat the distinction silently and in the worst
place. The registration query reports "could not tell" for an AT failure, and the send path
is required to read "could not tell" as permission to transmit. A lost link absorbed there
would make the gateway write messages into a port that no longer exists, with no line of
code looking wrong.

A link that closes cleanly SHALL be recognised as a lost link too. A closed stream does not
raise — it returns nothing, repeatedly and immediately — so a reader that only watches for
exceptions spins until its deadline and then reports an ordinary AT timeout, which routes
the fault straight back into the handling this requirement exists to bypass. An empty read
on a link that was open SHALL be classified as a lost link.

Both classes SHALL derive from one base, so a caller with no stake in the distinction can
handle both in one place. Only the callers whose behaviour differs SHALL name the classes
apart.

#### Scenario: The port disappears under an AT query
- **WHEN** the registration query fails because the underlying device is no longer readable
- **THEN** the failure is reported as a lost link, not as a modem that failed to answer

#### Scenario: The modem answers with an error
- **WHEN** an AT command returns `+CMS ERROR`
- **THEN** the failure is an AT failure and the link is not considered lost

#### Scenario: The link closes without raising
- **WHEN** reads on a previously open link begin returning nothing
- **THEN** the condition is classified as a lost link rather than as a command timeout

#### Scenario: A handler for AT failures does not absorb a lost link
- **WHEN** a lost link occurs inside an operation whose caller handles AT failures
- **THEN** the caller does not treat it as an answered-badly modem, and the lost link is handled on its own path

### Requirement: A link known to be lost is not used again

Once the link has been found lost, the gateway SHALL treat it as unusable until it has been
established afresh, and every attempt to use it SHALL fail immediately with a lost-link
failure rather than waiting for its own timeout.

Without this each consumer rediscovers the same dead link separately, paying a full command
timeout to learn what the gateway already knows, and a write to a closed stream may not
raise at all — leaving the caller to believe a command was sent that went nowhere.

#### Scenario: A second command follows a lost link
- **WHEN** a command is issued after the link has been found lost
- **THEN** it fails at once as a lost link rather than after its timeout

#### Scenario: A write against a closed link
- **WHEN** a write is attempted on a link known to be lost
- **THEN** it fails rather than appearing to succeed

### Requirement: A lost link is not repaired by AT commands

No remedy composed of AT commands SHALL be issued against a link that is lost, and failing
to issue one SHALL NOT stop the gateway escalating.

The recovery ladder's rungs are escalation levels, not fixed command sequences: the remedy
at each level SHALL be chosen by what is wrong. For a modem that is registered but
unhealthy the remedy is a radio cycle and then a modem reset; for a lost link the gentle
remedy is to establish the link again and the blunt remedy is to restart the service,
without an AT reset in either.

This is the defect that caused the incident, reached by a second route. Every rung of the
existing ladder writes to the port, so a lost link makes every rung raise; an implementation
that keeps the existing rung-to-command mapping and merely adds a new cause will spend its
whole escalation issuing AT commands into a port that is not there.

#### Scenario: The link is lost and the ladder escalates
- **WHEN** the ladder acts on a lost link
- **THEN** no radio cycle or modem reset is issued against the missing port

#### Scenario: A remedy cannot be carried out
- **WHEN** a remedy fails because the link is gone
- **THEN** it counts as attempted and escalation continues rather than stopping

### Requirement: Recovering the link does not depend on the watchdog being enabled

The gateway SHALL act on a lost link whether or not the modem watchdog is enabled.

The watchdog's switch exists so an operator can take over judgement about an unhealthy
*modem* — whether to cycle its radio, whether to reset it, whether to let the service
restart itself. A lost link is not a judgement call of that kind: there is no policy under
which the correct response to a port that does not exist is to keep writing to it. An
operator who silences the watchdog to investigate a flapping registration would otherwise
be silently opting out of ever recovering the port, and the gateway would stay unusable
until someone noticed.

If this coupling is given its own switch, that switch SHALL be separate from the
watchdog's, so disabling one does not disable the other.

The gateway SHALL NOT depend solely on the watchdog's periodic poll to notice a lost link
either. The send path meets the loss first and at the moment it matters; waiting up to a
full poll interval to begin acting on something already observed is time spent knowing the
answer.

#### Scenario: The watchdog is disabled and the link is lost
- **WHEN** the modem watchdog is switched off and the link to the modem is lost
- **THEN** the gateway still acts on the lost link rather than leaving the port unusable indefinitely

#### Scenario: The send path meets the loss first
- **WHEN** a send discovers the link is gone between two watchdog polls
- **THEN** that observation starts the response rather than being discarded until the next poll

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

