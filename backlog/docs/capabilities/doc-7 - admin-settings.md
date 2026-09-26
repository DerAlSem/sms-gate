---
id: doc-7
title: admin-settings
type: specification
created_date: '2026-09-26 05:59'
updated_date: '2026-09-26 06:00'
---
# admin-settings Specification

## Purpose
The admin console's settings screen: how the runtime settings in `SETTINGS_SPEC`
(`app/settings_store.py`) are shown to the owner and saved. Described from the code as it
stood at `ea3e04f` (26.09.2026), before SG-33 reworked the screen.

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

A boolean SHALL be edited as a true/false choice, `phone_region` as a list of countries, the
JSON-shaped types (`routes`, `oproutes`, `templates`, `brands`, `limits`) as free text, a
secret as a password field, and every other type as a one-line text field.

Route lists (`inbound_dispatch`, `delivery_dispatch`) are JSON text whose items carry a
`bearer` field; that field is shown in the text as stored.

[descriptive · evidence: app/admin/templates/settings.html:14-31 · conf: high]

### Requirement: A save is validated field by field before anything is stored

`POST /admin/settings` SHALL take every known key present in the form, skip a secret left
blank (blank = keep), and validate each value with `validate_raw` for its type. If any value
is refused, nothing SHALL be stored and the page SHALL be rendered again with each error
under its field.

The re-rendered page shows the STORED values, not the submitted ones: every edit on the
page, including the valid ones, is discarded along with the refused one.

[descriptive · evidence: app/admin/router.py:552-575 · conf: high]

#### Scenario: One invalid value discards the whole submission

- **WHEN** the owner changes `blacklist_threshold` and also types invalid JSON into
  `delivery_dispatch`, then saves
- **THEN** nothing is stored, the JSON error is shown under `delivery_dispatch`, and
  `blacklist_threshold` shows its old value again

### Requirement: A rule spanning two settings is checked at the store

`store.set_many` SHALL normalise and re-validate the changes, then refuse, before its
transaction opens, a `messenger_brands`/`messenger_limits` pair in which a sender account has
no rate bound (`check_every_account_is_rate_bound`). The route handler does not catch this
refusal, so it surfaces as a server error rather than as a field error.

[descriptive · evidence: app/settings_store.py:657-672, app/routing/config.py:391 · conf: high]

#### Scenario: A brand without its limit is refused with a server error

- **WHEN** the owner saves `messenger_brands` naming an account that `messenger_limits` does
  not bound
- **THEN** nothing is stored and the response is HTTP 500

### Requirement: A successful save redirects back to the page

After a save that stores, the handler SHALL redirect (303) to `/admin/settings`. The page
carries no mark of what was saved.

[descriptive · evidence: app/admin/router.py:574-575 · conf: high]
