## ADDED Requirements

### Requirement: A message is not transmitted while the modem is known to be off the network

Before transmitting, the gateway SHALL determine whether the modem is currently
registered, and SHALL hold the message back when the answer is a definitive negative.

The determination SHALL be made at send time rather than taken from the watchdog's
periodic sample: refusing to send is a decision that must not rest on information that
may be a minute old.

A held message SHALL NOT have an attempt counted against it, and SHALL be rescheduled to
be tried again shortly. Holding costs a message time, never chances — spending its retry
budget on a period when delivery was impossible would leave it finally failed having
never been transmitted at all.

A check that cannot be completed — an error, a timeout, an unparseable reply — SHALL NOT
hold the message. Not knowing is not a refusal, and a gateway that stops sending whenever
it cannot ask a question is worse than one that tries and reports a real failure.

Holding SHALL remain bounded by the existing pending deadline, so a message the gateway
declines to attempt still reaches a terminal status and its application is still told.

#### Scenario: The modem is off the network
- **WHEN** a message is due and the modem reports it is not registered
- **THEN** the message stays `pending` with its attempt count unchanged, and is tried again shortly

#### Scenario: The network comes back
- **WHEN** a message was held and the modem is registered on the next try
- **THEN** it is transmitted normally

#### Scenario: The registration check itself fails
- **WHEN** the registration query times out or raises
- **THEN** the message is attempted rather than held

#### Scenario: The outage outlives the message
- **WHEN** the modem stays unregistered until the message is past its deadline
- **THEN** the message becomes `failed` and its application is notified, rather than being held indefinitely

#### Scenario: A multipart send during an outage
- **WHEN** a two-part message is due while the modem is not registered
- **THEN** no part is transmitted, so the message cannot end up with one part delivered and no way to retry
