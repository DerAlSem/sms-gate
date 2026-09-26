# Contract: GM+ login codes through the sms-gate verification door

For: the Claude session working in the GM+ codebase (`gmp_app`). Written from the gateway's
code at `sms-gate` commit `a8324ed` (branch `feature/tg-user-verification`, task SG-32);
every value below is read from `app/api/router.py`, `app/api/schemas.py` and
`app/db/queries.py`, not from memory. When this file and the gateway disagree, the gateway
is right — ask its owner, do not guess.

## 0. Task in one paragraph

GM+ today sends its login code as plain text with `POST /sms/send`. Replace that, for
login codes only, with the verification door: the gateway mints the code, delivers it as a
Telegram message from GM+'s own service account (route `tg_user`), falls back on its own to
SMS or the Telegram Gateway, and checks what the person types. Every other SMS GM+ sends
stays on `POST /sms/send` unchanged.

## 1. Transport

- Base URL and bearer token: **the same ones GM+ already uses for `POST /sms/send`**. No
  new credential.
- Header: `Authorization: Bearer <token>`. Missing/invalid → `401 {"detail": "Invalid or missing token"}`.
- JSON in, JSON out. `phone` in E.164 (`+79991234567`); the gateway normalises with region
  `RU` and answers `422` (pydantic shape) on an invalid number.
- **Ignore unknown response fields.** The gateway adds fields without notice.
- All business refusals are `422` with `detail` an object carrying `error` (string key).
  A foreign or unknown `id` is `404 {"detail": "Verification not found"}`.

## 2. Endpoints

### 2.1 Create — `POST /verifications`

Request (`extra="forbid"`: any other field → 422; supplying `code` → 422):
```json
{"phone": "+79991234567"}
```
200:
```json
{"id": 9, "status": "pending",
 "routes": [{"route": "tg_user", "instruction": "Open Telegram…", "number": null},
            {"route": "sms_out", "instruction": "Wait for an SMS…", "number": null}]}
```
- `routes`: rungs that can carry this number now, in the gateway's configured order.
- `instruction` is English and is **not** for display to GM+ users (see §4).

422 `detail.error` on create:
| `error` | meaning | GM+ action |
|---|---|---|
| `number_blacklisted` | the gateway will not send to this number | tell the user the code cannot be sent to this number |
| `no_route_available` | nothing can carry this number right now | tell the user to try later |
| `no_template` | GM+ has no template configured at the gateway | operator problem: log loudly, show a generic error |

503 `detail.error = "no_code_available"`: too many open verifications for this number → try later.

### 2.2 Select a route — `POST /verifications/{id}/route`

Request: `{"route": "<one of routes[].route>"}`.

**Selection rule (mandatory): if `routes` contains `tg_user`, send `tg_user`. Otherwise send
`routes[0].route`.** Do not hard-code any other route name.

200:
```json
{"id": 9, "route": "sms_out", "status": "pending", "reason": null, "code": null}
```
- `route` in the response is the rung that **actually carried** the code. It differs from
  the one selected whenever Telegram could not deliver (no Telegram account, account
  limited, no answer): the gateway walks down on its own inside this one request. Drive
  the UI from the response's `route`, never from what was selected.
- `status` is `pending` (code on its way — the normal case) or `failed` (nothing could
  carry it; `reason` says why). It is never `confirmed` here.
- `code` is always `null` for the routes GM+ will get. The gateway never hands the code to
  the application on these routes.
- The request can take up to ~10 s (the gateway's ladder bound). Client timeout: **15 s**.

422 `detail.error` on select:
| `error` | GM+ action |
|---|---|
| `route_not_offered` | the offer decayed — create a new verification and select again |
| `already_selected` | a route is already chosen — do not select again; go to §2.3 |
| `refused` | nothing was sent (a limit or the routing rule) — tell the user to try later |
| `verification_failed`, `verification_expired`, `verification_confirmed` | this verification is over — create a new one |
| `expired`, `not_found` | same as above |

### 2.3 Check the code — `POST /verifications/{id}/check`

Request: `{"code": "4821"}` (string, as typed; four digits).

200: `{"id": 9, "status": "<status>", "outcome": "<outcome>"}`

| `outcome` | GM+ action |
|---|---|
| `confirmed` | log the user in |
| `wrong_code` | show "wrong code", allow retry |
| `no_attempts_left` | verification is over (5 wrong attempts) — offer a new code |
| `expired` | over (5 minutes passed) — offer a new code |
| `already_confirmed` | treat as confirmed only if this same session confirmed it; otherwise offer a new code |

404 → unknown id.

### 2.4 Status — `GET /verifications/{id}`

200 fields used by GM+: `status` (`pending|confirmed|failed|expired`), `route`, `reason`,
`expires_at` (ISO UTC). Optional: poll every 2–3 s while the code screen is open, to show
"not delivered" early when `status` becomes `failed`. Not required for correctness —
`/check` alone is enough.

## 3. The flow GM+ implements

```
login_code_requested(phone):
    v = POST /verifications {phone}              # §2.1, handle 422/503
    pick = "tg_user" if "tg_user" in [r.route for r in v.routes] else v.routes[0].route
    s = POST /verifications/{v.id}/route {route: pick}   # §2.2, timeout 15 s
    if s.status == "failed": show "code could not be delivered", offer retry (new verification)
    else: store v.id in the user's login session; show hint for s.route (§4)

code_entered(code):
    r = POST /verifications/{id}/check {code}    # §2.3

resend_pressed():
    create a NEW verification (a finished or pending one is never re-sent)
```

Store only the verification `id` against the login session. Never store or log the code —
GM+ never sees it.

## 4. What the user is shown (by the response's `route`)

| `route` | text (ru) |
|---|---|
| `tg_user` | «Код отправлен в Telegram от „Сервисный аккаунт GM+“» |
| `sms_out` | «Код отправлен по SMS» |
| `tg_gateway` | «Код отправлен в Telegram» |
| `flash_call` | «Вам позвонят. Не отвечайте: код — последние 4 цифры номера» |
| anything else | «Код отправлен» |

The same code may arrive twice (Telegram late, then SMS). Both are the same code; do not
warn the user about it.

## 5. Invariants — do not break

1. GM+ never generates, sends or stores a login code itself once this is live.
2. `POST /sms/send` stays for every non-code message.
3. Fallback to the old `/sms/send` code path **only** on transport failure or HTTP 5xx from
   `POST /verifications` — never on a 422. A 422 is an answer, and the old path would not
   reach МегаФон subscribers anyway.
4. No route names other than `tg_user` are hard-coded for selection.
5. Unknown response fields and unknown `route` values do not raise.

## 6. Acceptance (GM+ side)

Unit tests with the gateway mocked (httpx/respx or equivalent), one per line:

1. `tg_user` offered → selected; hint for the response's `route` shown.
2. `tg_user` offered, response `route = sms_out` → SMS hint, not the Telegram one.
3. `tg_user` absent → `routes[0]` selected.
4. select → `status: failed` → "not delivered" + retry creates a new verification.
5. each 422 key in §2.1 and §2.2 → the action in its table.
6. `/check` → each `outcome` → the action in its table.
7. 5xx / timeout on create → old `/sms/send` path used; 422 on create → it is **not**.
8. resend → a new `POST /verifications`, never a second select on the old id.
9. no code value appears in logs or storage.

Live check (owner only, never on customers' numbers): one login on `+79851600019`,
expected Telegram message from the GM+ service account, text starting
«Это Сервисный Аккаунт GM+.», then a successful `/check`.

## 7. Preconditions on the gateway side (owner, not GM+)

- `verification_templates` has an entry for `gmp_app` (otherwise `no_template`).
- `messenger_brands` / `messenger_limits` map `gmp_app` to the service account.
- `verification_route_order` contains `tg_user`; session signed in on the host.
- sms-gate commit `733d24d` or later is deployed (a selected `tg_user` falls back down the
  operator's rule).

Until all four hold, `tg_user` is simply not in `routes` and the flow above still works via
`routes[0]`.
