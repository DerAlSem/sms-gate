---
id: doc-7
title: admin-settings
type: specification
created_date: '2026-09-26 05:59'
updated_date: '2026-09-26 06:26'
---
# admin-settings Specification

## Purpose
The admin console's settings screen: how the runtime settings in `SETTINGS_SPEC`
(`app/settings_store.py`) are shown to the owner and saved. First described from the code at
`ea3e04f` (26.09.2026); SG-33.1 made saving per section and stopped a refusal from
discarding what was typed.

## Requirements
### Requirement: Every setting in SETTINGS_SPEC is shown, grouped by its section

`GET /admin/settings` SHALL list every entry of `SETTINGS_SPEC`, grouped under the entry's
`section`, each with its key and its `description`. A secret's stored value SHALL NOT appear
in the page; the field SHALL say only whether it is configured.

[descriptive · evidence: app/admin/router.py:529-550, app/admin/templates/settings.html · conf: high]

#### Scenario: A secret is shown as configured, never by value

- **WHEN** `alert_bot_token` is stored and the settings page is opened
- **THEN** the page names the field and says it is configured, and the token's value is
  nowhere in the page

### Requirement: The editor follows the setting's type

A boolean SHALL be edited as an On/Off switch whose unticked state saves `false`,
`phone_region` as a list of countries, the JSON-shaped types (`routes`, `oproutes`,
`templates`, `brands`, `limits`) as free text, a secret as a password field, and every
other type as a one-line text field.

[normative · evidence: app/admin/templates/settings.html, tests/test_admin_settings.py · conf: high]

#### Scenario: Clearing a switch saves false

- **WHEN** the owner unticks a boolean setting and saves its section
- **THEN** the setting is stored as `false`

### Requirement: A route's bearer is never shown back from the store

In `inbound_dispatch` and `delivery_dispatch` every stored non-blank `bearer` SHALL be
shown as a fixed placeholder. On save, a placeholder SHALL be replaced by the stored bearer
of the route with the same route key, matched in order among routes sharing that key; a
placeholder with no such stored route SHALL be refused at the field. A refused save SHALL
show the routes back as submitted, so a bearer just typed is neither hidden nor reverted by
the next save.

[normative · evidence: app/admin/router.py (_mask_bearers, _resolve_bearer_sentinel) · conf: high]

#### Scenario: Saving the routes unchanged keeps the bearer

- **WHEN** the owner saves the routes text exactly as the page showed it
- **THEN** each route keeps its stored bearer, and no bearer value appears in the page

#### Scenario: A placeholder on a route the store lacks is refused

- **WHEN** a route whose key is not stored carries the placeholder as its bearer
- **THEN** nothing is stored and the field says the bearer must be entered

### Requirement: Each section is saved on its own

Every section SHALL be its own form with its own save button, sending only its own keys.
Every value SHALL be validated with `validate_raw` before anything is stored; if any is
refused, nothing SHALL be stored, the refused section SHALL show the values as submitted
(secrets excepted) with each error at its field and a mark that it is unsaved, and every
other section SHALL show the stored values.

[normative · evidence: app/admin/router.py (admin_settings_save), tests/test_admin_settings.py · conf: high]

#### Scenario: A refusal keeps what was typed

- **WHEN** the owner changes `blacklist_threshold` to 9 and `delivery_report_max_age_hours`
  to 0 in one section and saves
- **THEN** nothing is stored, the error stands at `delivery_report_max_age_hours`, and
  `blacklist_threshold` still shows 9

#### Scenario: Saving one section leaves another alone

- **WHEN** the owner saves one section
- **THEN** only that section's keys are stored

### Requirement: A rule spanning two settings is refused at both fields

`store.set_many` SHALL refuse, before its transaction opens, a
`messenger_brands`/`messenger_limits` pair in which a sender account has no rate bound
(`check_every_account_is_rate_bound`). The screen SHALL show that refusal at both fields,
keeping what was typed, and SHALL NOT answer with a server error.

[normative · evidence: app/settings_store.py:657-672, app/admin/router.py · conf: high]

#### Scenario: A brand without its limit is refused at both fields

- **WHEN** the owner saves `messenger_brands` naming an account that `messenger_limits` does
  not bound
- **THEN** nothing is stored, and both fields carry the error

### Requirement: The screen says what is saved and what is not

After a save that stores, the screen SHALL return to the saved section and show "Saved"
there. A section edited but not saved SHALL be marked unsaved, and leaving the page while
any section is unsaved SHALL ask for confirmation; saving one section SHALL NOT clear that
guard for the others. A refused save SHALL bring its first error into view.

[normative · evidence: app/admin/templates/settings.html (script) · conf: medium — driven in jsdom, not a real browser]

#### Scenario: Leaving with another section unsaved asks first

- **WHEN** the owner edits two sections and saves one
- **THEN** leaving the page asks for confirmation
