## ADDED Requirements

### Requirement: The diagnostics page does not paint a missing reading as a fault

The modem diagnostics page SHALL render a reading the modem refused, and one the modem did
not answer, distinctly from a reading that failed — and neither in the style the page uses
for faults. A reading that failed SHALL keep that style.

Three of the fourteen rows are permanently in the error style on a perfectly healthy modem:
`AT+CIREG?` and `AT+QCFG="servicedomain"` are refused by this firmware, and `AT+CLIP?` has
never answered. A page that is partly red whenever it is opened teaches its reader that red
means nothing there, and the next red row — the one that is a fault — is read the same way.
The page exists to be looked at during an incident, so this is the one place that cost is
paid in full.

**The page says what happened, not why.** A refused row reports that the modem refused the
command; it does not report that the firmware lacks it. The page is not where a cause is
inferred, and the inference is wrong for any command the modem refuses for a reason of its
own — a SIM that has failed refuses `AT+CPIN?`, and that row must stay a fault.

Each row SHALL show the modem's own response whatever the outcome, so a reader can tell a
firmware without the command from a gateway that has stopped asking properly.

A reading SHALL be rendered in words rather than as the raw fields it was decoded into. The
rows on this page are read by a person deciding what to do next, and `enabled=1 admitted=0`
asks them to remember a vendor's digit order; the decoders this page already renders supply
a named state beside the number for exactly that reason.

#### Scenario: A row's command is refused by the firmware
- **WHEN** an operator opens the modem diagnostics page and a command was refused
- **THEN** the row says the modem refused the command, not styled as a fault, and shows what the modem answered

#### Scenario: A row's command did not answer
- **WHEN** a command timed out
- **THEN** the row says nothing was measured, distinctly from a refusal and not styled as a fault

#### Scenario: The SIM has failed
- **WHEN** `AT+CPIN?` is answered with an error about the SIM
- **THEN** the row is shown as a fault, in the style the page uses for faults

### Requirement: The voice route's state is visible on the diagnostics page

The page SHALL show whether IMS is enabled on the module, whether the network has admitted
it, and when that was last successfully measured.

This is the page an operator opens when asking whether an incoming call can still reach this
SIM. The alert says the state changed; the page is where somebody checks the answer before
and after acting on it, where the two halves are told apart — a setting to change locally,
or a conversation with the carrier — and where a state that has not been measurable for
hours is distinguishable from one that is fine.

#### Scenario: An operator checks the voice route
- **WHEN** the modem diagnostics page is opened
- **THEN** it reports whether IMS is enabled on the module, whether the network has admitted it, and when it was last measured

#### Scenario: The state has not been measurable
- **WHEN** the voice route has not been successfully measured recently
- **THEN** the page says so rather than showing the last known value as if it were current
