## MODIFIED Requirements

### Requirement: A background loop cannot die unnoticed

The death of any long-running background task *within the gateway process* SHALL be logged
with its traceback and SHALL raise an operator alert. Collecting the tasks in a way that
discards their outcomes SHALL NOT be permitted.

This is the mechanism that hid the incident's second failure entirely: the loop delivering
delivery reports and inbound notifications raised, terminated, and left no line anywhere,
because the tasks are gathered with their exceptions returned and then dropped. No amount of
care inside a loop compensates for a collector that discards what the loop reports.

The requirement covers every background task, not only those that own a serial connection —
the sweep that expires messages, the one that re-queues retries, the one that flushes
partial inbound messages. Each of them failing silently produces a gateway that looks
healthy and has quietly stopped doing part of its job.

The scope is the gateway's own process, and deliberately so. Separate processes the gateway
depends on — a tunnel connector, an uplink manager — are supervised by the service manager
rather than by a task collector, and the evidence of their health is different in kind: not
an exception that was discarded, but a process that is running and doing nothing. Reading
this requirement as covering them would suggest they are already handled, which is how a
component ends up with no supervision at all while appearing to have inherited some.

#### Scenario: A loop raises
- **WHEN** a background task terminates with an exception
- **THEN** its traceback is logged and an operator alert is raised

#### Scenario: A loop the gateway needs terminates
- **WHEN** a task the gateway cannot work without dies
- **THEN** the service exits so its supervisor restarts it

#### Scenario: A separate process the gateway depends on
- **WHEN** a process outside the gateway fails
- **THEN** this requirement does not govern it, and its own capability's supervision does
