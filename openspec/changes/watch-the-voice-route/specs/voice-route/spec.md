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

The reading SHALL carry two facts kept apart: **what the module is configured to do about
IMS**, and **whether the voice route is available**. They fail for different reasons and
have different cures, and collapsing them into one "IMS is down" reports the wrong cure at
the moment a person is deciding what to do.

The configuration is a local setting, held in non-volatile memory and taking effect at the
module's next reboot. It does not move with the radio — measured 2026-09-20, where it held
its value unchanged across a full soft recovery while the availability of the route went
from up to down and back. It has **three** states, not two: this gateway has asked for IMS
compulsorily, and the alternatives are an explicit compulsory disable and a factory position
that defers the decision to the carrier profile stored on the module. A gateway that reports
the configuration as a yes-or-no cannot tell "somebody disabled it" from "nobody decided,
and the profile is deciding" — two different conversations with two different people. The
state SHALL therefore be reported in the vendor's own three-way terms and not as a boolean.

The availability of the route is an outcome, and the gateway SHALL report it as one. It
SHALL NOT be reported as the carrier's verdict: the vendor's reference names this field the
capability of VoLTE in its parameter table and the IMS registration status in its prose one
page earlier, and neither of those is "the network refused this subscriber". Naming a cause
the gateway did not observe is already forbidden to this project's alerts, and it is
forbidden here.

A firmware that does not know the command SHALL be reported as not measured rather than as
not registered. `AT+CIREG?` answers `ERROR` on the build in service and the vendor has
confirmed the command is absent from it; a gateway that reads that as "not registered to
IMS" reports the negative of a fact it never obtained, which is the reading that cost this
project three days and very nearly a replacement module.

#### Scenario: The sweep runs while the gateway is serving
- **WHEN** the diagnostic sweep reads the module's IMS state
- **THEN** it is read through the command port's ordinary locking, with no send interrupted and no service stopped

#### Scenario: The configuration holds but the route is unavailable
- **WHEN** the module is configured for IMS and the voice route is not available
- **THEN** the two facts are reported separately rather than as one condition

#### Scenario: The configuration defers to the carrier profile
- **WHEN** the module's IMS configuration is neither a compulsory enable nor a compulsory disable, but the factory position that defers to the carrier profile
- **THEN** it is reported as that third state, and not as IMS being switched off

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

The gateway SHALL NOT report the route as unavailable while the module is not registered to
the network. That reading is negative on an unregistered module whether or not the route
would otherwise be available. Measured twice: on 2026-09-18 the module sat outside the
network for about three minutes after a hard reset and read negative throughout, and on
2026-09-20 a soft recovery was sampled end to end — thirty seconds off the network, eight
samples, every one of them reporting the module unregistered and the route unavailable
together, and both returning positive at the same sample. A watcher without this
gate announces a lost voice route after every modem reset, every radio cycle and every
recovery, which is the surest way to make the alert ignored before the first real one
arrives. An unregistered module is already the watchdog's condition and has a ladder of its
own.

**The configuration drifting from the one this gateway set** SHALL be alerted whether or not
the module is registered, and SHALL be alerted even while the route is still available.

This is a different statement from "IMS has been switched off", and the difference is the
point. The configuration this gateway wrote is a compulsory enable. It can move off that in
two ways, and both matter: an explicit compulsory disable, and a return to the factory
position that defers to the carrier profile. The second is not a fault in itself — a module
in that state whose profile enables VoLTE has a working voice route — but it is no longer
the state the gateway asked for, and it holds only for as long as that profile does. The
vendor's own reference says a profile activated or deactivated restores the setting to the
profile's default, and that profiles are selected automatically from the SIM's identity, so
changing the SIM is enough to disarm the route without anyone touching the setting.

Gating this condition on registration would silence it in the one scenario that generates
it: every state that moves the configuration arises while the module is rebooting and off
the network.

**Neither alert SHALL name a cause the gateway did not observe.** In particular the alert
SHALL NOT tell an operator that the carrier has refused the module: the gateway has no
reading that says so.

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

#### Scenario: The route stops being available
- **WHEN** a registered module whose voice route was available stops having it available
- **THEN** one alert is raised for that episode, naming the observation and not a cause

#### Scenario: The module is off the network
- **WHEN** the module is not registered to the network
- **THEN** no alert is raised about the route's availability, and the condition is left to the watchdog

#### Scenario: The configuration drifts while the module is off the network
- **WHEN** the module's IMS configuration is no longer the one the gateway set and the module is not registered to the network
- **THEN** the alert about the configuration is still raised

#### Scenario: The configuration drifts while the route still works
- **WHEN** the module's IMS configuration has returned to deferring to the carrier profile, and the profile leaves the voice route available
- **THEN** the alert about the configuration is raised, and no alert claims the route is lost

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
