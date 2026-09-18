## ADDED Requirements

### Requirement: A refusal, a silence and a negative answer are three different readings

A diagnostic reading SHALL carry which of four things happened — the modem returned a value,
the modem refused the command, the modem said nothing, or the command failed — and that
outcome SHALL be decided where the modem's response is still in hand, not reconstructed
later from the text of an error.

This capability already separates a failure of the link from a modem that answers badly,
and requires that both derive from one base so callers who do not care can treat them alike.
This is the same axis one level finer, for the read-only sweep: a row that was refused and a
row that timed out are today both an `error` string, and by the time they reach anything
that could tell them apart the modem's own words have been normalised away.

The distinction is not academic here. On this build `AT+CIREG?` and
`AT+QCFG="servicedomain"` are refused always, and `AT+CLIP?` has never answered — at two
seconds or at eight. Neither says anything about the value asked for, and reading the first
of them as "no IMS" produced a standing verdict that this module had no voice path at all.

**A refusal is what the modem did, not why.** `ERROR` means the modem would not carry out
the command; it does not by itself mean the command is absent from the firmware's
vocabulary. That stronger claim is known for these two commands only because the vendor
confirmed it in writing, and the gateway SHALL NOT assert it from a result code. A modem
that answered with an error **about its own state** — a `+CMS ERROR`, or a `+CME ERROR`
other than the codes that mean the command is not supported or not allowed — SHALL be
reported as a fault, because that is what it is: `AT+CPIN?` answering `+CME ERROR: 13` is a
failed SIM, the exact fault of the 2026-09-06 outage, and rendering it as "nothing was
measured" would hide the one reading that names the cause.

The outcome SHALL be derived from what the modem answered, not from a list of commands
believed to be absent. A fixed list would hide the case that matters most — a command that
used to answer and has begun to refuse — and a command currently refused that starts
answering SHALL be reported from its answer, with no edit required to let it through.

The modem's own response SHALL be carried with the reading whatever the outcome, so a reader
can tell a firmware without the command from a gateway that has stopped asking properly.

#### Scenario: A command is refused
- **WHEN** a diagnostic command is answered with a bare `ERROR`, or with an error code meaning the command is not supported
- **THEN** the reading records a refusal, carrying the modem's response, and reports no value

#### Scenario: A command does not answer
- **WHEN** a diagnostic command times out
- **THEN** the reading records a silence, distinctly from a refusal

#### Scenario: The modem reports a fault about its own state
- **WHEN** `AT+CPIN?` is answered with `+CME ERROR: 13`
- **THEN** the reading records a failure, not a refusal and not a missing measurement

#### Scenario: A command answers in the negative
- **WHEN** a diagnostic command answers with a value meaning "no"
- **THEN** it is reported as that value and not as a missing reading

#### Scenario: A previously refused command begins to answer
- **WHEN** a command that used to be refused answers with a value
- **THEN** the value is reported, without any change to the gateway
