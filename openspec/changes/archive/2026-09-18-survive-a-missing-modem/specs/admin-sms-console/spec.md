## ADDED Requirements

### Requirement: An unreachable modem is shown on every page of the console

When the gateway has no usable link to the modem, every admin page SHALL carry a
prominent notice saying so, rather than the fact being available only on the diagnostics
page.

An operator who notices that SMS have stopped does not begin at the diagnostics page —
they begin wherever they were, most often the message list. Confining the fact to one
page means the console can look entirely normal while nothing is being sent or received,
which is precisely the state that needs announcing.

The notice SHALL be rendered from the same health snapshot the diagnostics page reads, so
that the two cannot disagree about whether the modem is reachable.

The notice SHALL be absent when the link is in service, so that its presence carries
information.

#### Scenario: The modem is unreachable
- **WHEN** an operator opens any admin page while the gateway has no usable link
- **THEN** that page carries a notice that the modem is not detected

#### Scenario: The modem is reachable
- **WHEN** an operator opens any admin page while the link is in service
- **THEN** no such notice is shown

#### Scenario: The notice agrees with the diagnostics page
- **WHEN** the notice is shown and the operator opens the diagnostics page
- **THEN** the diagnostics page reports the link as unusable as well

### Requirement: The console is served while the modem is unreachable

Every admin page SHALL be served whether or not the modem can be reached, and a page
SHALL NOT fail because the modem is absent.

The console's data comes from the database. Its dependence on the modem today is
incidental — a shared process whose startup awaited the link — not a dependence on modem
data. A page that cannot be opened reports nothing at all, which is the worst available
answer to "what is wrong with the modem".

Pages whose content is read from the modem itself, such as the diagnostics page, SHALL
render with that content reported as unavailable rather than failing.

#### Scenario: Opening the message list with no modem
- **WHEN** an operator opens the message list while the modem is unplugged
- **THEN** the page renders with its messages, carrying the not-detected notice

#### Scenario: Opening the diagnostics page with no modem
- **WHEN** an operator opens the modem diagnostics page while the modem is unplugged
- **THEN** the page renders, reporting that the values could not be read, rather than returning an error
