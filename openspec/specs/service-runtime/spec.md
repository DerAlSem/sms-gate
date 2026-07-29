# service-runtime Specification

## Purpose
TBD - created by archiving change recover-from-serial-transport-loss. Update Purpose after archive.
## Requirements
### Requirement: A background loop cannot die unnoticed

The death of any long-running background task SHALL be logged with its traceback and SHALL
raise an operator alert. Collecting the tasks in a way that discards their outcomes SHALL
NOT be permitted.

This is the mechanism that hid the incident's second failure entirely: the loop delivering
delivery reports and inbound notifications raised, terminated, and left no line anywhere,
because the tasks are gathered with their exceptions returned and then dropped. No amount of
care inside a loop compensates for a collector that discards what the loop reports.

The requirement covers every background task, not only those that own a serial connection —
the sweep that expires messages, the one that re-queues retries, the one that flushes
partial inbound messages. Each of them failing silently produces a gateway that looks
healthy and has quietly stopped doing part of its job.

#### Scenario: A loop raises
- **WHEN** a background task terminates with an exception
- **THEN** its traceback is logged and an operator alert is raised

#### Scenario: A loop the gateway needs terminates
- **WHEN** a task the gateway cannot work without dies
- **THEN** the service exits so its supervisor restarts it

### Requirement: A task cancelled during shutdown is not a death

Task cancellation performed as part of an orderly shutdown SHALL NOT be reported as a
failure, SHALL NOT alert, and SHALL NOT trigger a service exit.

Shutdown cancels every background task by design. Supervision that cannot tell that apart
from a crash would alert on every task at every deploy and replace the shutdown path —
closing the modem, closing the database — with an immediate exit, turning routine
maintenance into a failure notification and an unclean stop.

#### Scenario: The service is stopped
- **WHEN** the gateway shuts down and cancels its background tasks
- **THEN** no alert is raised, no traceback is logged as a failure, and shutdown completes normally

### Requirement: A fatal alert is delivered before the process exits

The gateway SHALL deliver the alert explaining why it is exiting before the process ends,
whenever it exits because it has decided it cannot continue.

Alerts are queued and delivered by a background worker, and an immediate exit discards
whatever is still queued. An exit that reports itself only to a log the operator is not
watching is the same silence this change exists to remove — the gateway would restart
repeatedly with nobody told why.

#### Scenario: The gateway exits on an unrecoverable fault
- **WHEN** the gateway decides to exit
- **THEN** the alert naming the reason is delivered first, within a bounded wait

#### Scenario: The alert cannot be delivered
- **WHEN** the alert cannot be sent within that bound
- **THEN** the gateway exits anyway rather than staying up to keep trying

### Requirement: A notification that is dropped says so

A notification that cannot be queued or cannot be delivered SHALL be recorded, rather than
discarded silently.

The alerting path currently drops a notification when its queue is full and swallows every
exception in its delivery worker, both deliberately, to keep alerting from failing the
thing it reports on. Neither leaves any trace, so an alerting path that has stopped working
is indistinguishable from a system with nothing to report — and it is precisely during a
long incident, when notifications are most frequent, that the queue is most likely to fill.

#### Scenario: The alert queue is full
- **WHEN** a notification cannot be queued
- **THEN** the fact is recorded rather than passing unnoticed

#### Scenario: Delivery fails
- **WHEN** a notification cannot be delivered to its destination
- **THEN** the failure is recorded rather than swallowed

