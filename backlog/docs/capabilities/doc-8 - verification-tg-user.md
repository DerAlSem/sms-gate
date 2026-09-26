---
id: doc-8
title: verification-tg-user
type: specification
created_date: '2026-09-26 15:37'
updated_date: '2026-09-26 15:52'
---
# verification-tg-user Specification

## Purpose
The `tg_user` rung of the verification ladder: a verification code sent as a Telegram
message from the application's own support account (for GM+, `@gmplus_support`), ahead of
the rungs the routing rule gives the number's operator. Code: `app/verification/tg_user_carrier.py`
(ladder semantics), `app/routing/tg_user.py` (the wire), `app/verification/placement.py`
(wiring and the ladder it continues into). Introduced by SG-32; verified live 26.09.2026
(verification 7, `rung_ledger` row `message_id=-7`, `outcome=accepted`).

Scope: this document covers only the `tg_user` rung. The rest of the verification door
(`POST /verifications`, route selection, `/check`) is not yet described here; the
consumer-facing contract is `docs/contracts/gmp-verification.md`.

## Requirements
### Requirement: The account is the application's, read from the brand map

The gateway SHALL choose the Telegram account a verification is sent from only through
`messenger_brands` (application → brand → one account per messenger), read per call. An
application with no `tg_user` account there SHALL NOT be offered the rung and SHALL raise
nothing about it.

#### Scenario: An application without an account
- **WHEN** an application absent from `messenger_brands` creates a verification
- **THEN** `tg_user` is not among the offered `routes`
- **AND** the journal says nothing about the rung

### Requirement: An unwired rung is absent and spends no allowance

The rung SHALL be put on the ladder only when `TG_API_ID`, `TG_API_HASH` and
`TG_SESSION_DIR` are all set and the session file `<TG_SESSION_DIR>/<account>.session`
exists. Otherwise the rung SHALL be absent (not present and refusing), no allowance of the
account SHALL be claimed, and the journal SHALL say
`tg_user route is configured but not wired: <what is missing>` — once per verification
assembly, not at startup.

#### Scenario: The session file is missing
- **WHEN** an application with a `tg_user` account creates a verification and the session file does not exist
- **THEN** the rung is not placed and the account's hourly and daily counts are unchanged
- **AND** the journal names the missing file

### Requirement: The code travels inside the application's words, with an introduction the first time

The message SHALL be the application's verification template with the code, read from
the store at the moment of sending. The first message from an account to a number SHALL be
prefixed by the brand's recorded introduction; "already written" is decided by an
`accepted` row in `rung_ledger` for the pair (route, account). A brand that owes an
introduction and records none SHALL make the rung `INCAPABLE` before Telegram is asked
anything. An application with no verification template SHALL likewise be `INCAPABLE`.

#### Scenario: First code to a number
- **WHEN** `@gmplus_support` has never written to +7… and brand `gmplus` records the introduction `Это Сервисный Аккаунт GM+.`
- **THEN** the person receives `Это Сервисный Аккаунт GM+.`, a blank line, then the template with the code (`s-g: 7329`)

#### Scenario: The verification ended before the send
- **WHEN** the verification's code is gone by the time the rung composes its message
- **THEN** nothing is sent, the claimed allowance is released, and the rung answers `FAILED`

### Requirement: Telegram's four answers map onto the ladder

| wire outcome | ladder | effect |
|---|---|---|
| `accepted` | `CARRIED` | the verification is carried by `tg_user` |
| `miss` (no Telegram on the number) | `DECLINED` | the ladder moves to the next rung |
| `unavailable` (session, ban, flood, our failure) | `REFUSED` | loud alert naming the account; the ladder moves on |
| `indeterminate` (no answer in time) | `UNANSWERED` | the ladder moves on; a duplicate code is accepted |

A `tg_user` refusal SHALL NOT withhold the modem (`sms_out`); only a paid vendor's refusal
does. A deadline that expires SHALL NOT cancel the offer: the ladder stops waiting and the
offer finishes on its own bound, so the session file is never left locked.

#### Scenario: The number has no Telegram
- **WHEN** the selected `tg_user` answers `miss`
- **THEN** the ladder carries the code by the next rung the routing rule gives the operator, and the response's `route` names that rung

#### Scenario: Our own limit refuses
- **WHEN** the account's hourly allowance is spent
- **THEN** the rung answers `REFUSED`, the alert says the limit is ours (fixed in `messenger_limits`), not Telegram's

### Requirement: A selected tg_user continues into the operator's ladder

`tg_user` SHALL stand in front of the routing rule, not inside it: the ladder for a
selected `tg_user` is `[tg_user] + <the rule's rungs for the operator>`. `tg_user` SHALL
NOT be written into `operator_routes`, because the `/send` modem sender reads the rule's
first rung and would refuse all ordinary traffic.

#### Scenario: МегаФон number, Telegram misses
- **WHEN** a МегаФон number selects `tg_user` and Telegram answers `miss`
- **THEN** the ladder continues with МегаФон's rungs from `operator_routes`, excluding `tg_user`

### Requirement: Account limits are durable

Every send SHALL first claim the account's allowance in `messenger_rate_claims`
(per hour, per day, per recipient window from `messenger_limits`) atomically; the claim
SHALL survive a process restart. Ledger ids for verifications SHALL be the verification id
negated, so they never meet message ids in `rung_ledger` or `messenger_rate_claims`.

#### Scenario: Restart between two sends
- **WHEN** the service restarts after an account used its hourly allowance
- **THEN** the next verification in that hour is still refused by the limit

### Requirement: Each worded rung writes the code into its own template

`verification_templates` entries SHALL carry `app_id`, `template` and an optional `route`
(`sms_out` or `tg_user` — the rungs that carry a code inside our words; any other route is
refused at save). A rung SHALL read the entry for `(app_id, route)`, else the application's
entry with no `route`, else it has no template and is `INCAPABLE`. Two entries for one pair
SHALL be refused at save. A template SHALL carry exactly one of `{code}` (digits) or
`{code_words}` (capitals, one word per digit, space-separated: `1204` → `ОДИН ДВА НОЛЬ
ЧЕТЫРЕ`). The accept door's `no_template` refusal SHALL ask each offered rung for its own
template. Introduced by SG-34 (owner, 26.09.2026: SMS codes go spelled out).

#### Scenario: GM+ with a template per rung
- **WHEN** `gmp_app` has `{"route":"tg_user","template":"… {code}"}` and `{"route":"sms_out","template":"GM+: {code_words}"}`, and Telegram misses
- **THEN** the Telegram offer carried `… 1204`, and the SMS the modem sends reads `GM+: ОДИН ДВА НОЛЬ ЧЕТЫРЕ`

#### Scenario: Only a Telegram template, only the modem left
- **WHEN** an application's only template names `tg_user` and the only offered rung is `sms_out`
- **THEN** `POST /verifications` answers `422 no_template`
