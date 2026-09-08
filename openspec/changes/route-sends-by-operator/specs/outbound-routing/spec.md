## Purpose

Which way out a message takes. The gateway has two ways to reach a subscriber — the local
modem and a commercial SMS provider over HTTP — and this capability owns the choice between
them, the rule that expresses it, and what happens when the choice cannot be made. It exists
because the modem route has been withdrawn by operators before, at whole-estate scale, and
the replacement must be reachable by configuration rather than by deploying code during an
outage.

## ADDED Requirements

### Requirement: Every send is assigned exactly one route before it is transmitted

A message SHALL be assigned a route — `modem` or `provider` — at enqueue time, and that
assignment SHALL be recorded against the message. A message SHALL NOT be transmitted by a
route other than the one recorded, and SHALL NOT be transmitted by two.

The recorded route SHALL be readable afterwards, because the cost, the delivery-report
mechanism and the failure vocabulary all differ by route, and none of them can be
reconstructed from the message alone once it has been sent.

#### Scenario: A message is routed and recorded
- **WHEN** a send is accepted
- **THEN** its route is decided and stored before any transmission is attempted

#### Scenario: The recorded route is the one used
- **WHEN** a message carries a recorded route of `provider`
- **THEN** the modem sender does not pick it up, and the reverse for `modem`

### Requirement: The route is chosen by a configured rule keyed on the recipient's operator

Route selection SHALL be expressed as configuration read at send time, keyed on the
recipient's operator as recorded in `number_operators`. Adding, changing or removing an
operator's route SHALL NOT require a code change or a deploy.

No operator name SHALL appear in a branch in the sending path. The rule's initial content —
МегаФон to `provider`, everything else to `modem` — is data, and the change that introduces
it is not permitted to hard-code it, because the event this capability exists for is the
next withdrawal rather than this one.

#### Scenario: An operator with a configured route
- **WHEN** the rule routes МегаФон to the provider and a send is addressed to a МегаФон number
- **THEN** the message is routed `provider`

#### Scenario: An operator with no entry in the rule
- **WHEN** a send is addressed to an operator the rule does not mention
- **THEN** the message is routed `modem`, the configured default

#### Scenario: The rule changes without a deploy
- **WHEN** a second operator is added to the rule while the service is running
- **THEN** subsequent sends to that operator take the new route, with no restart and no code change

### Requirement: An unknown operator does not block the send

The operator lookup is enrichment and SHALL remain so. A send SHALL NOT be delayed, held or
failed because the recipient's operator is unknown, unresolved or stale: `record_operator`
never blocks a send today, and routing SHALL NOT be the thing that makes it blocking.

When the operator is not known at routing time, the message SHALL take the configured
default route and SHALL be recorded as having been routed without a known operator, so that
the case is countable rather than invisible.

This matters more than it looks: the numbers most likely to lack an operator row are the
ones never messaged before, and a first-time recipient is exactly who a confirmation code is
usually for.

#### Scenario: A first-time number whose lookup has not resolved
- **WHEN** a send is addressed to a number with no row in `number_operators`
- **THEN** the message is sent over the default route without waiting for a lookup, and the absence of the operator is recorded

#### Scenario: The lookup service is unreachable
- **WHEN** the operator lookup fails for every number for an hour
- **THEN** sending continues over the default route throughout, and no message is failed for want of an operator

### Requirement: A provider send reports delivery on the same contract as a modem send

The owning application SHALL observe the same statuses on the same webhook regardless of
route. `delivery-dispatch` is a product contract; the route is an operational detail, and
the application SHALL NOT be required to know which one carried its message.

Where the provider reports a delivery outcome the modem vocabulary has no word for, it SHALL
be mapped to an existing status rather than introducing a new one into the application's
contract, and the unmapped detail SHALL be recorded alongside for operators.

#### Scenario: A provider-routed message is delivered
- **WHEN** the provider confirms delivery
- **THEN** the application receives the same `delivered` notification it would have received from the modem route

#### Scenario: A provider-routed message fails
- **WHEN** the provider reports a failure
- **THEN** the application receives a `failed` notification carrying a decoded reason, and the provider's own code is retained for operators

### Requirement: A route that cannot be used fails loudly and does not silently fall back

If the assigned route cannot carry a message — the provider is unreachable, unauthenticated,
or out of credit — the message SHALL NOT be transmitted over the other route. It SHALL follow
the retry and expiry rules already governing sends, and the operator SHALL be alerted.

Automatic failover between routes is deliberately absent. Escalating into a paid channel
without a spend ceiling turns a modem fault into an unbounded bill, and the ceiling is not
specified here; until it is, the safe behaviour is to fail visibly.

#### Scenario: The provider rejects our credentials
- **WHEN** the provider answers a send with an authentication error
- **THEN** the message is not sent over the modem instead, the operator is alerted, and the message follows the existing retry rules

#### Scenario: The provider is out of credit
- **WHEN** the provider reports insufficient balance
- **THEN** the operator is alerted with that reason, and no message is rerouted
