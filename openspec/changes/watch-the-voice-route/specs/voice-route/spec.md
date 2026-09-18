## Purpose

Whether this gateway's own SIM can be reached by an incoming voice call, and whether anyone
would find out if it stopped being reachable. An incoming call is a way to authorise a
person, so the route's availability is a fact the gateway owes an operator — separately from
the serial link underneath it and from its ability to send SMS.

## ADDED Requirements

### Requirement: The module's IMS state is read while the gateway is in service

The gateway SHALL read whether the module is registered to IMS as part of the read-only
diagnostic sweep it performs over the command port, with the service running, using a
command the firmware in service answers.

Today the only way to learn it is to stop `sms-gate` so something else can hold the command
port. This gateway carries live customer traffic, so measuring costs exactly the outage the
measurement exists to detect, and the reading is therefore never taken. The whole point of
watching IMS is that it must be observable at the moments nobody is willing to cause an
outage — which is all of them.

The reading SHALL carry two facts kept apart: whether IMS is **enabled on the module**, and
whether the **network has admitted it**. They fail for different reasons and have different
cures. A module with IMS switched off is a setting somebody must change and a reboot
somebody must accept; a module the network refuses is the operator's business with the
carrier, and nothing local will fix it. Collapsing them into one "IMS is down" reports the
wrong cure at the moment a person is deciding what to do.

A firmware that does not know the command SHALL be reported as not measured rather than as
not registered. `AT+CIREG?` answers `ERROR` on the build in service and the vendor has
confirmed the command is absent from it; a gateway that reads that as "not registered to
IMS" reports the negative of a fact it never obtained, which is the reading that cost this
project three days and very nearly a replacement module.

#### Scenario: The sweep runs while the gateway is serving
- **WHEN** the diagnostic sweep reads the module's IMS state
- **THEN** it is read through the command port's ordinary locking, with no send interrupted and no service stopped

#### Scenario: IMS is enabled but the network has not admitted the module
- **WHEN** the module has IMS switched on and the network has not admitted it
- **THEN** the two facts are reported separately rather than as one condition

#### Scenario: The firmware does not know the command
- **WHEN** the command used to read IMS is refused by the firmware
- **THEN** the state is reported as not measured, and not as an IMS registration that is absent

### Requirement: Losing the voice route raises an alert, and being off the network does not

The gateway SHALL raise an operator alert when the voice route becomes unavailable, on
entering that condition rather than once per poll, and SHALL notify once when it returns.

IMS is what makes this module reachable for an incoming voice call, and an incoming voice
call is a way to authorise a person. Losing it takes that route away silently: every other
reading stays healthy, SMS continues to arrive, and the first witness would be a person who
cannot log in. The link already has this shape — an alert on entering the condition so a
long absence does not become a stream of notifications, and a notification when it is
restored so whoever was woken learns it is over without opening a page.

**The two conditions are alerted separately, and only one of them is gated.**

The gateway SHALL NOT report the network's admission as lost while the module is not
registered to the network. The vendor reading's second digit is zero on an unregistered
module whether or not the network would admit it — measured 2026-09-18, where the module
sat outside the network for about three minutes after a reset and read zero throughout. A
watcher without this gate announces a lost voice route after every modem reset, every radio
cycle and every recovery, which is the surest way to make the alert ignored before the first
real one arrives. An unregistered module is already the watchdog's condition and has a
ladder of its own.

IMS being **disabled on the module** SHALL be alerted whether or not the module is
registered, because that digit is a local setting the radio state does not affect, and
because the state that produces it — a module whose stored setting did not survive a reset
or a replacement — is both the more alarming condition and one that occurs precisely while
the module is off the network and rebooting. Gating it would silence the change's most
valuable alert in the one scenario that generates it.

**A route already lost when the gateway starts is an episode too.** Episode state does not
survive the process, and the process ends itself on the recovery ladder's top rung and on
every deploy. A gateway that only alerts on a transition it personally witnessed says
nothing about a module that has been unreachable since before it started — which is the
exact state of 2026-09-18 and the state this change exists to end. The first reading that
establishes the condition after startup SHALL raise the alert, once for that episode.

**Watching does not depend on the modem watchdog being enabled.** That switch exists so an
operator can take over judgement about *remedies* — whether to cycle the radio, whether to
reset the module. Observing and reporting is not a remedy, and an operator silencing the
watchdog to investigate a flapping registration must not thereby opt out of ever learning
the voice route is gone. This capability's live neighbour already refuses the same coupling
for the link, and requires that any switch given to it be a separate one; the same holds
here.

**Observing SHALL NOT be able to break the thing it observes.** A reading that fails is an
unmeasured reading, not an exception: it SHALL NOT stop the recovery ladder advancing, SHALL
NOT prevent an escalation being carried out, and SHALL NOT prevent the service exiting when
the ladder has decided it must.

#### Scenario: The network stops admitting the module
- **WHEN** a module registered to the network and admitted to IMS stops being admitted
- **THEN** one alert is raised for that episode

#### Scenario: The module is off the network
- **WHEN** the module is not registered to the network
- **THEN** no alert is raised about the network's admission, and the condition is left to the watchdog

#### Scenario: IMS is switched off while the module is off the network
- **WHEN** the module reports IMS disabled and is not registered to the network
- **THEN** the alert about IMS being disabled is still raised

#### Scenario: The route was already lost when the gateway started
- **WHEN** the first reading after startup finds the voice route unavailable
- **THEN** the alert is raised for that episode, rather than waiting for a transition this process did not witness

#### Scenario: The route comes back
- **WHEN** the voice route becomes available again
- **THEN** one notification says so, the reported state clears, and a later loss can alert again

#### Scenario: The watchdog is switched off
- **WHEN** the modem watchdog is disabled and the voice route is lost
- **THEN** the alert is still raised

#### Scenario: Reading the voice route fails during a recovery
- **WHEN** the IMS reading raises while the recovery ladder is escalating
- **THEN** the rung is still carried out, the ladder still advances, and the reading is recorded as unmeasured

### Requirement: A voice route that stopped being measured is not reported as healthy

The gateway SHALL report when the voice route was last measured, and SHALL alert when it has
not been measurable for long enough that its state is no longer known.

Every mechanism this change installs fails silent. The gate is opened by a registration
answer that is itself `False` whenever the modem does not answer at all, so an unanswerable
modem produces no IMS reading and no alert, indefinitely. A firmware change that alters the
response format produces an unparseable reading, which by the convention this project
already follows becomes "not measured" — and the requirement that stops a refusal looking
like a fault makes that silence quiet on the page as well.

A watcher that has gone permanently silent is otherwise indistinguishable from a voice route
that is permanently fine, and the second is what everyone will assume. The link is already
required to report when it was last known good, for this reason.

#### Scenario: The reading has not been obtainable for a long time
- **WHEN** the voice route has not been successfully measured for longer than the threshold, while the gateway is running
- **THEN** an alert is raised saying the state is unknown, distinct from an alert saying the route is lost

#### Scenario: An operator asks when it was last known
- **WHEN** the voice route's state is reported
- **THEN** it carries the time it was last successfully measured

#### Scenario: The reading becomes unparseable
- **WHEN** the response to the IMS query can no longer be parsed
- **THEN** it counts as not measured and feeds the staleness threshold, rather than being read as a value
