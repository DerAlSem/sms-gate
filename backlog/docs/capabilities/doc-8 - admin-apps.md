---
id: doc-8
title: admin-apps
type: specification
created_date: '2026-09-26 15:31'
updated_date: '2026-09-26 18:13'
---
# admin-apps Specification

## Purpose
The admin console's client-applications screen `/admin/apps`: which applications may talk
to the gateway, with which token, and whether they may spend on paid verification. First
described from the code at `3a720bf` (26.09.2026), before SG-33.4 added a page per
application. Application-specific settings (SMS template, delivery webhook, messenger
brands) were at that point edited as JSON on the settings screen (doc-7); SG-33.4 moved
them to the application's own page.

## Requirements
### Requirement: Every application is listed with its switches

`GET /admin/apps` SHALL list every row of `apps`, newest first, with its id, description,
the first six characters of its token followed by an ellipsis, its message count, and
whether it is active and whether it may spend. The full token SHALL NOT appear in the list.

[descriptive · evidence: app/admin/router.py (_render_apps), app/admin/templates/apps.html, app/db/queries.py (list_apps) · conf: high]

#### Scenario: The list never shows a whole token

- **WHEN** the owner opens the applications screen
- **THEN** each token is shown as its first six characters and an ellipsis

### Requirement: A new application's token is shown once

`POST /admin/apps/create` SHALL create an active application with a fresh `tok_` token
and show that token once on the answering page. A blank id or an id already taken SHALL be
refused with a message and nothing created.

[descriptive · evidence: app/admin/router.py (admin_apps_create), tests/test_admin_apps.py · conf: high]

#### Scenario: A duplicate id is refused

- **WHEN** the owner creates an application with an id that exists
- **THEN** nothing is created and the screen says the id already exists

### Requirement: Activity and spending are switched separately

The screen SHALL switch an application's `is_active` and its `may_spend` independently.
Granting spending SHALL ask for confirmation first; revoking SHALL NOT. Both take effect on
the next request without a restart. The `admin` application SHALL NOT offer these switches.

[descriptive · evidence: app/admin/router.py (admin_apps_toggle, admin_apps_entitlement), app/db/queries.py (get_app) · conf: high]

#### Scenario: Granting spending asks first

- **WHEN** the owner presses «Allow spending» on an application
- **THEN** the browser asks for confirmation before the entitlement is granted

### Requirement: Only an unused application can be deleted

Delete SHALL be offered, and SHALL act, only for an application other than `admin` with no
messages. Deleting SHALL remove the `apps` row only; entries keyed by its id in settings
(templates, delivery routes, brands) SHALL stay as they were.

[descriptive · evidence: app/admin/router.py (admin_apps_delete), app/db/queries.py (delete_app) · conf: high]

#### Scenario: An application with messages is kept

- **WHEN** a delete is posted for an application that has messages
- **THEN** the application stays

### Requirement: An application's own settings are edited on its page

`GET /admin/apps/<id>` SHALL show the application and three blocks, each its own form: the
SMS text a code arrives in (`verification_templates`), the delivery-report webhook
(`delivery_dispatch`) and the messenger brands it may send under (`messenger_brands` →
`apps`). The id in the list SHALL link to this page. An id with no application SHALL be
answered as not found. Storage is unchanged: each block edits this application's entry in
the same setting, through `validate_raw` and `store.set_many`.

[normative · evidence: app/admin/router.py (admin_app_detail*), app/admin/templates/app_detail.html, tests/test_admin_app_detail.py · conf: high]

#### Scenario: The list leads to the page

- **WHEN** the owner clicks an application's id in the list
- **THEN** its page opens at `/admin/apps/<id>`

### Requirement: Saving on an application's page touches only that application

A block's save SHALL replace or remove this application's entry only; every other
application's entries in the same setting, and their order, SHALL stay as they were. A blank
SMS text or a blank webhook URL SHALL remove the entry; no brand ticked SHALL remove the
application from `apps`. When the application has several delivery routes, the page SHALL
edit the first — the one `find_route` uses — keep the rest, and say that they do not act.

[normative · evidence: app/admin/router.py (_replace_app_entry, _save_app_entry_field), tests/test_admin_app_detail.py · conf: high]

#### Scenario: Another application's template survives

- **WHEN** the owner saves `sokol`'s SMS text while `gmp` also has one
- **THEN** `gmp`'s entry is stored exactly as before

### Requirement: The SMS text says its length, and a refusal keeps it

The SMS block SHALL say that the text carries exactly one `{code}` and that blank means no
code by SMS, and SHALL count characters and SMS parts as typed (GSM-7 160/153, otherwise
UCS-2 70/67; `{code}` counted as its own six characters). A refusal by any validator,
`set_many`'s rate-bound check included, SHALL be shown at the block's field with what was
typed kept and SHALL NOT answer with a server error.

[normative · evidence: app/admin/templates/app_detail.html (script), tests/test_admin_app_detail.py · conf: medium — counter driven in jsdom, not a real browser]

#### Scenario: Two codes are refused at the field

- **WHEN** the owner saves «{code} и {code}» as the SMS text
- **THEN** nothing is stored, the error stands at the SMS field, and the text is still there

### Requirement: The delivery webhook's bearer is write-only

The page SHALL NOT carry the stored bearer. A blank bearer on save SHALL keep the stored one;
only the «remove bearer» box SHALL clear it.

[normative · evidence: app/admin/router.py, tests/test_admin_app_detail.py · conf: high]

#### Scenario: Saving the URL alone keeps the bearer

- **WHEN** the owner changes the webhook URL and leaves the bearer blank
- **THEN** the stored bearer is unchanged and appears nowhere in the page

### Requirement: The list shows who gets no code by SMS

The list SHALL show, per application, whether it has an SMS text, and an application
without one SHALL be marked as getting no code by SMS. The gateway's own senders, `admin`
and `telegram`, send free text and never a code: without a text they SHALL be shown, muted,
as not needing one. An unreadable setting SHALL be shown as such and SHALL NOT take the
list down.

[normative · evidence: app/admin/router.py (_render_apps, _INTERNAL_SENDERS), app/admin/templates/apps.html, tests/test_admin_app_detail.py · conf: high]

#### Scenario: A missing text is marked

- **WHEN** an application has no entry in `verification_templates`
- **THEN** its row says the code by SMS will not reach it

#### Scenario: An internal sender is not flagged

- **WHEN** `admin` or `telegram` has no entry in `verification_templates`
- **THEN** its row says a text is not needed, without the red mark

### Requirement: Entries left by a deleted application stay reachable

Deleting an application leaves its entries in the three settings. `/admin/apps/<id>` SHALL
open for an id that has no application but still has an entry, say so, and let each entry
be removed; only an id with neither SHALL be not found. The list SHALL link every such id.
A block SHALL refuse to save, at its field, when the stored setting cannot be read, rather
than store this application's entry over the others.

[normative · evidence: app/admin/router.py, tests/test_admin_app_detail.py · conf: high]

#### Scenario: A deleted application's brand binding can be cleared

- **WHEN** application `shop` is deleted while `messenger_brands.apps` still names it
- **THEN** the list links `shop`, and its page can untick its brands
