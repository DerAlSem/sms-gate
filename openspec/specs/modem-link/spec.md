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

### Requirement: The service is restarted when the link cannot be used

When the link is lost and cannot be established, the gateway SHALL exit so its supervisor
restarts it.

A restart is the one remedy that reliably works, because it opens the port afresh, runs the
init sequence including the URC subscription, reconciles the modem's stored messages, and
recovers queued messages from the database — all of which the gateway already does at
startup. A process that has decided it can no longer reach the hardware SHALL NOT keep
running while reporting itself healthy.

#### Scenario: The link cannot be established
- **WHEN** the gateway cannot use the link
- **THEN** it exits so it is restarted, rather than continuing with an unusable link

#### Scenario: The link recovers before the ladder reaches the end
- **WHEN** the link answers again before escalation completes
- **THEN** the gateway continues running and does not exit

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
control: a restart provoked by a lost link lands while the device is still absent, because
a re-enumerating modem takes longer to return than a supervisor takes to restart a service.
Treating the startup case as fatal converts the remedy into the failure — the gateway
restarts, cannot open the port, exits, and repeats until its supervisor stops trying
altogether and the outage becomes indefinite.

Waiting for the device at startup SHALL be bounded, and the bound SHALL be reconciled with
the supervisor's restart limits so that the two cannot combine into a permanent stop.

#### Scenario: The port is absent when the service starts
- **WHEN** the gateway starts while the device node is not yet present
- **THEN** it waits for the device within its bound rather than failing to start

#### Scenario: The device returns during startup
- **WHEN** the device reappears while the gateway is waiting for it
- **THEN** the gateway opens it, completes its init sequence, and starts normally

#### Scenario: The device does not return
- **WHEN** the device is still absent when the bound elapses
- **THEN** the gateway exits, and its restarts remain within the supervisor's limits rather than exhausting them

