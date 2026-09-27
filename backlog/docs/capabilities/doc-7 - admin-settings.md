---
id: doc-7
title: admin-settings
type: specification
created_date: '2026-09-26 05:59'
updated_date: '2026-09-26 18:16'
---
# admin-settings Specification

## Purpose
The admin console's settings screen: how the runtime settings in `SETTINGS_SPEC`
(`app/settings_store.py`) are shown to the owner and saved. First described from the code at
`ea3e04f` (26.09.2026); SG-33.1 made saving per section and stopped a refusal from
discarding what was typed; SG-33.2 grouped the screen by the owner's tasks,
named each setting in the interface language and added the Telegram account card;
SG-33.3 put forms in place of hand-written JSON and checked the rung order's names.

## Requirements
### Requirement: Every setting is shown once, in a section named for the owner's task

`GET /admin/settings` SHALL list every entry of `SETTINGS_SPEC` exactly once, in the section
`app/admin/settings_layout.py` places it in: Modem and sending, Telegram notifications, Number
verification, Routes by operator, Vendors, Limits and money protection, Webhooks, and
Advanced. The grouping is display only: `Spec.section` SHALL stay what `store.set_many`
keys its change hooks on. The page SHALL open with a list of links to every section. A
secret's stored value SHALL NOT appear in the page; the field SHALL say only whether it is
configured.

[normative · evidence: app/admin/settings_layout.py (SECTIONS), app/admin/router.py (_settings_view_rows), tests/test_admin_settings_layout.py · conf: high]

#### Scenario: A setting added to SETTINGS_SPEC without a place is caught

- **WHEN** a key is in `SETTINGS_SPEC` but in no section of the layout, or in two
- **THEN** the test suite fails, naming the key

#### Scenario: A secret is shown as configured, never by value

- **WHEN** `alert_bot_token` is stored and the settings page is opened
- **THEN** the page names the field and says it is configured, and the token's value is
  nowhere in the page

### Requirement: A setting is named in the interface language, its key only in small print

Each setting SHALL be shown with a human name and an explanation that states its units and
what blank or zero means, both in the interface language (RU and EN through babel). The key
SHALL be shown in small monospace for whoever knows it. `Spec.description` SHALL NOT be shown.

[normative · evidence: app/admin/settings_layout.py, app/admin/translations/ru/LC_MESSAGES/messages.po · conf: high]

#### Scenario: The owner finds settings without reading keys

- **WHEN** the owner opens the page in Russian
- **THEN** «Куда приходят алерты — чат Телеграма» and «Лимит платных проверок в час» are on it

### Requirement: Rare settings are folded away, and say when they are not at their defaults

The Advanced section SHALL be closed by default. Its heading SHALL show «изменено: N» when N
of its settings differ from their defaults (a secret counts when set), and nothing when none
do. It SHALL open by itself when a refused save put an error inside it, when it was the
section just saved, or when the page's address points into it.

[normative · evidence: app/admin/settings_layout.py (is_changed), app/admin/templates/settings.html · conf: medium — opening by address driven in jsdom, not a real browser]

#### Scenario: An error in a folded section is not hidden

- **WHEN** a save in Advanced is refused
- **THEN** the page comes back with Advanced open and the error in view

### Requirement: The Telegram account's environment is reported, never shown

The Vendors section SHALL carry a Telegram account card that says, for `TG_API_ID`,
`TG_API_HASH` and `TG_SESSION_DIR`, only whether each is set — never a value; whether
`tg_user` is in `verification_route_order`; for each application with a `tg_user` account,
whether the rung is wired or why not (`tg_user_carrier.unwired_reason`); one line on whether
the `tg_user` rung is enabled and, if not, the first reason; and a folded explanation of how
to set the three in the `.env` named by the service unit. The three stay in `.env` by the
owner's decision of 26.09.2026. A failure to read any of this SHALL be shown on the card and
SHALL NOT take the page down.

[normative · evidence: app/admin/settings_layout.py (tg_account_overview), app/admin/templates/settings.html, tests/test_admin_settings_layout.py · conf: high]

#### Scenario: The API hash never reaches the page

- **WHEN** `TG_API_HASH` is set and the settings page is opened
- **THEN** the card says it is set, and its value is nowhere in the page

### Requirement: The editor follows the setting's type

A boolean SHALL be edited as an On/Off switch whose unticked state saves `false`,
`phone_region` as a list of countries, a secret as a password field, the settings named below
as forms, `messenger_brands` and `messenger_limits` as JSON text, and every other type as a
one-line text field.

[normative · evidence: app/admin/templates/settings.html, tests/test_admin_settings.py · conf: high]

#### Scenario: Clearing a switch saves false

- **WHEN** the owner unticks a boolean setting and saves its section
- **THEN** the setting is stored as `false`

### Requirement: A form writes the same value the text field would

`operator_routes`, `verification_route_order`, `send_retry_backoff` and `inbound_dispatch`
SHALL be edited as forms. The field the section posts SHALL stay the setting's own text field,
hidden while the form is shown: the form SHALL write its value there on every change, so the
server receives and validates exactly what it received before the forms, and SHALL mark the
section unsaved. Each form SHALL offer to edit the value as text and to go back; a value the
form cannot read — typed as text, or sent back by a refused save — SHALL open as text, with a
message, and the server's error SHALL stay at the field either way. Opening a stored value
and saving it untouched SHALL post a value equal to the stored one.

[normative · evidence: app/admin/templates/settings.html (script) · conf: medium — driven in jsdom, not a real browser]

#### Scenario: An unreadable rule opens as text

- **WHEN** a save of `operator_routes` with broken JSON is refused
- **THEN** the field shows the submitted text with the error, and the form is hidden

#### Scenario: An untouched form changes nothing

- **WHEN** the owner opens the page and saves the Routes section without editing it
- **THEN** `operator_routes` is posted equal to the stored rule

### Requirement: The routing rule is a row per operator

`operator_routes` SHALL be shown as one row per operator in stored order, each with its
operator name, its rungs in order with a human name, controls to move a rung up or down or
remove it, a choice to add a rung the row does not have yet, and an «Отказать» switch that
stores the row as `["refuse"]`. The rows for `*` («Любой другой оператор») and `?`
(«Оператор не определён») SHALL always be last, without a name field and without removal; a
rule that lacks either SHALL show it refused, which is what `rule.route_for` does for a
missing entry. A row with no rung and no refusal SHALL be posted as it is, for the rule's own
validation to refuse.

[normative · evidence: app/admin/templates/settings.html, app/verification/rule.py · conf: medium — driven in jsdom]

#### Scenario: Refusing an operator

- **WHEN** the owner ticks «Отказать» on a row and saves
- **THEN** that operator's entry is stored with routes `["refuse"]`

### Requirement: The rung order names only rungs the gateway knows

`verification_route_order` SHALL be edited as an ordered list of rungs with a choice to add
one not yet listed; an unknown name from the store SHALL be shown, marked unknown, rather than
dropped. On save, a name that is not in `routes.ALL_ROUTES`, or a rung named twice, SHALL be
refused at the field; empty parts between commas SHALL be ignored, and a blank value accepted.

[normative · evidence: app/settings_store.py (validate_raw, "rungs"), tests/test_settings_store.py · conf: high]

#### Scenario: A misspelt rung is refused

- **WHEN** the owner saves `verification_route_order` as `call_in,sms_outt`
- **THEN** nothing is stored and the field names `sms_outt` as unknown

### Requirement: Retry delays and inbound routes are rows

`send_retry_backoff` SHALL be edited as a row of whole-second fields, one per retry, with
removal and «Добавить повтор»; no row SHALL mean one attempt with no retry. `inbound_dispatch`
SHALL be edited as a table of prefix, webhook URL and bearer, with rows added and removed; with
no routes the screen SHALL say that inbound SMS is not forwarded anywhere. A stored bearer SHALL
show as an empty password field that keeps the stored bearer when left empty.

[normative · evidence: app/admin/templates/settings.html · conf: medium — driven in jsdom]

#### Scenario: Leaving a bearer empty keeps it

- **WHEN** the owner changes a route's URL and leaves its bearer field empty
- **THEN** the route keeps its stored bearer

### Requirement: The messenger JSON is readable and has an example

`messenger_brands` and `messenger_limits` SHALL be shown indented when read from the store (as
submitted after a refusal), in a monospace field, with a button that puts in an example and
asks before replacing a non-empty value.

[normative · evidence: app/admin/router.py (_format_json_for_display), app/admin/templates/settings.html · conf: medium]

#### Scenario: The example does not silently overwrite

- **WHEN** the owner presses the example button on a non-empty `messenger_limits`
- **THEN** the page asks before replacing it

### Requirement: A route's bearer is never shown back from the store

In `inbound_dispatch` (and in `delivery_dispatch` on the application's page, doc-9) every stored non-blank `bearer` SHALL be
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

### Requirement: What belongs to one application is not edited here

`verification_templates` and `delivery_dispatch` SHALL NOT be editable on the settings screen;
in their sections each SHALL be named with a pointer that it is set on the application's page
(doc-9). `messenger_brands` SHALL be shown without its `apps` key; on save the stored `apps`
SHALL be put back before validation, and a submitted `apps` SHALL be refused at the field.
Clearing a brand an application still names SHALL be refused by `validate_brands`.

[normative · evidence: app/admin/settings_layout.py (app_owned), app/admin/router.py (_strip_apps_for_display, _reinsert_messenger_apps), tests/test_admin_app_detail.py · conf: high]

#### Scenario: Saving Vendors keeps the applications' brands

- **WHEN** the owner saves the Vendors section
- **THEN** `messenger_brands.apps` is stored exactly as before
