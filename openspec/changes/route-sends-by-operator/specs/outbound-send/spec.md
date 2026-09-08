## RENAMED Requirements

- FROM: `### Requirement: A message becomes `sent` when its first part is accepted by the modem`
- TO: `### Requirement: A message becomes `sent` when its route accepts its first part`

## MODIFIED Requirements

### Requirement: A message becomes `sent` when its route accepts its first part

A message SHALL move to `sent` when the route carrying it accepts responsibility for its
first part. What counts as acceptance is a property of the route, and the two differ:

- **Modem route.** Parts SHALL be transmitted sequentially within one serial session. Each
  part's `+CMGS` reference SHALL be recorded before the next part is transmitted, and the
  message SHALL move to `sent` on the first part's reference.
- **Provider route.** The message SHALL move to `sent` when the provider has accepted it for
  delivery and returned its own identifier for it. That identifier SHALL be recorded, since
  it is the only handle by which a later delivery report can be matched, and the `+CMGS`
  reference the modem route matches on does not exist here.

A provider acceptance SHALL NOT be recorded as a `+CMGS` reference. The two identifier
spaces are unrelated, and the attribution that matches reports to parts by reference would
otherwise match a provider's identifier against a modem's — silently, and only under load,
because collisions need two live messages to coincide.

[normative · evidence: app/modem/manager.py:123-132, app/modem/at_commands.py:145-180 · conf: medium — the provider branch is not yet implemented]

#### Scenario: A two-part message is transmitted
- **WHEN** part 1 of a two-part message receives `+CMGS: 10`
- **THEN** the message is `sent` and part 1 is recorded before part 2 is transmitted

#### Scenario: A provider accepts a message
- **WHEN** a provider-routed message is accepted and the provider returns its own message identifier
- **THEN** the message is `sent` and that identifier is recorded against it

#### Scenario: The two identifier spaces do not mix
- **WHEN** a provider identifier and a `+CMGS` reference coincide numerically
- **THEN** a delivery report from one route is never attributed to a message sent by the other
