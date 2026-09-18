## ADDED Requirements

### Requirement: A link that was never established holds a message on the same terms as one that was lost

A message due while the gateway has no link at all SHALL be held, not failed, on exactly
the terms already required for a link that was lost: no attempt counted against it,
rescheduled to be tried again shortly, and bounded by the existing pending deadline.

The spec already refuses to read a lost link as "not knowing", on the reasoning that it is
not a question the modem failed to answer but the absence of anything to ask. A link that
has never come up — because the device was absent when the gateway started, or was
unplugged — is the same absence, and the same reasoning governs it. Reading it as a send
failure instead would turn a brief unplug into lost SMS, and would report `failed` to the
owning application for messages the network was never offered.

The determination SHALL be made before an attempt is claimed. A link known to be absent is
known before anything is written, so the message need never have its attempt count or
schedule disturbed and then restored.

While the gateway has no link, held messages SHALL continue to accumulate as `pending`
rather than being rejected at the API, since accepting and queueing a send has never
required the modem.

#### Scenario: A message is due with no modem attached
- **WHEN** a message becomes due while the gateway has never established a link
- **THEN** it stays `pending` with its attempt count unchanged, and is tried again shortly

#### Scenario: The modem is attached later
- **WHEN** the link is established while messages are held
- **THEN** they are transmitted without having spent any of their retry budget

#### Scenario: A held message outlives its deadline
- **WHEN** the modem is still absent when a held message reaches its pending deadline
- **THEN** it reaches a terminal status and its application is told, as any other pending message would

#### Scenario: A send is requested with no modem attached
- **WHEN** an application submits a message while the gateway has no link
- **THEN** the request is accepted and queued, as it is when the modem is present
