## ADDED Requirements

### Requirement: A message whose operator's route cannot carry text is failed without touching the modem

When the routing rule assigns a message's recipient to a route that carries only verification
codes, the sender SHALL mark the message `failed` with an error naming the operator and the
route, notify the owning app on its `delivery-dispatch` route, and raise an operator alert —
without issuing any AT command and without consuming a retry.

The message SHALL NOT be sent over the modem instead. Rerouting it there is the automatic
failover this design refuses, and it would put traffic back on exactly the route an operator
has already been rejecting.

The message SHALL NOT be rejected at `POST /sms/send` with an HTTP error. Acceptance stays
synchronous and unchanged; the refusal arrives as a status like every other outcome, because
the applications affected — `gmp_app`, `mprz_bot`, `turbo_route_bot` — already handle
`failed` and do not handle a new HTTP code. What changes for them is that the failure comes
at once and carries a reason, instead of after the retry ladder with `service rejected
(temporary, st=99)`.

This is a refusal that applies to applications sending ordinary text, not codes. Measured on
08.09.2026: about seventy such messages a month are addressed to МегаФон, and the count is
growing. `phone-verification` is the door those applications would use instead if the traffic
were codes; it is not, so for them this is a route that has become unavailable, said out loud.

The alert SHALL arrive on the configuration the gateway ships with, and SHALL be deduplicated
on the operator and the route. The existing send-failure notification is governed by
`notify_send_errors`, which defaults to off — a refusal routed through it would be raised for
nobody on a stock install, which is every install that has this defect. Deduplication matters
for the opposite reason: the measured traffic is about seventy refusals a month and growing,
and one alert per refused message teaches the operator to ignore the channel that also carries
"the vendor is out of credit".

[unbacked · shape mirrors the existing part-budget refusal at app/modem/manager.py:109-121; the default-off toggle is notify_send_errors in app/settings_store.py]

#### Scenario: Free text addressed to an operator routed to the call route
- **WHEN** an application sends arbitrary text to a МегаФон number while the rule routes МегаФон to `call`
- **THEN** the message is `failed` with an error naming МегаФон and the route, the app is notified, an alert is raised, and no `AT+CMGS` is sent

#### Scenario: The refusal does not consume the retry ladder
- **WHEN** a message is refused for want of a usable route
- **THEN** it is not retried, because no retry could change the outcome

#### Scenario: The refusal is audible on a stock install
- **WHEN** a message is refused for want of a usable route on a gateway whose notification settings were never touched
- **THEN** the operator is alerted, and repeated refusals for the same operator and route are deduplicated within the alert window

#### Scenario: The rule is removed
- **WHEN** the operator's entry is removed from the routing rule
- **THEN** subsequent messages to that operator are sent over the modem again, with no code change
