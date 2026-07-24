# Delivery webhook — integration contract

Status push for **outbound** SMS: the gateway calls your endpoint whenever a message you
sent changes status, so you learn the outcome in seconds instead of on your next poll.

This is the symmetric counterpart of the inbound webhook (`GMP <token>` → your
`/inbound`). Nothing about `POST /sms/send` or `GET /sms/{id}` changes.

## What we need from you

| | |
|---|---|
| `webhook_url` | full absolute URL, `https://…` |
| `bearer` | the token we will send as `Authorization: Bearer <token>` |
| `app_id` | your application id in the gateway (the one your API token maps to) |

The operator configures these in the gateway's admin settings. There is nothing to
deploy on your side beyond the endpoint itself.

## The request

```http
POST /webhooks/sms-gate/delivery HTTP/1.1
Content-Type: application/json
Authorization: Bearer <your token>

{
  "id": 57,
  "status": "delivered",
  "error": null,
  "occurred_at": "2026-07-24T09:14:05Z",
  "resent_from": 42
}
```

| field | always? | meaning |
|---|---|---|
| `id` | yes | message id, the one `POST /sms/send` returned |
| `status` | yes | `sent` \| `delivered` \| `failed` \| `expired` |
| `error` | yes | human-readable reason, or `null`. Set for `failed`, usually `null` otherwise |
| `occurred_at` | yes | when the status changed, ISO-8601 UTC |
| `resent_from` | **no** | present only when an operator re-sent an earlier message (see below) |

Reply **`200`** to anything you accept. We do not read the body.

## Semantics you need to handle

**`pending` is never pushed.** `POST /sms/send` already returns
`{"id": …, "status": "pending"}` synchronously, so a webhook for it would be a duplicate
that could even beat the HTTP response you are still reading.

**Order is not guaranteed — use `occurred_at`.** Notifications are independent, and a
failing one keeps retrying (tens of seconds against a slow or unreachable endpoint)
while a later one goes out immediately. So `delivered` can arrive **before** `sent`. If
you store "last update wins", you will overwrite a `delivered` with a stale `sent`.
Compare `occurred_at` against what you hold and ignore anything older.

**`expired` is not terminal.** A message can go `sent → expired → delivered`: we expire a
message that has been awaiting a delivery report too long, and the network sometimes
reports it afterwards anyway. Do not treat `expired` as final — the `occurred_at` rule
above resolves it.

**`resent_from` links an operator's re-send.** When a message fails, an operator can
re-send it from the gateway's admin UI. That creates a **new** message with a **new id**
(the failed attempt keeps its error as history). You never saw that id, because you did
not create it. `resent_from` carries the id of the original, so you can attribute the
outcome:

```
your message 42            → failed
operator re-sends          → new message 57
webhook {id: 57, status: "delivered", resent_from: 42}
                           → message 42 did eventually reach the person
```

Without reading this field you would show 42 as permanently failed although the person
got the SMS. Ignoring it is safe — you just lose that correction.

**Delivery is best-effort — keep polling as your floor.** We make up to 3 attempts
(configurable), 10 s timeout each, with 1 s then 4 s between them, and then drop it; a
gateway restart mid-retry also drops it. We do **not** persist a queue. `GET /sms/{id}`
stays authoritative, so anything lost self-heals on your next poll. Do not switch polling
off — lengthen the interval instead. The webhook is an accelerator, not a replacement.

**Be idempotent.** A status may arrive more than once. Applying the same update twice
must be a no-op.

**Unknown fields.** We may add fields. Ignore what you do not recognise rather than
rejecting the request.

## Failure handling on our side

A POST that fails every attempt raises an operator alert in Telegram (deduplicated per
url, so a dead endpoint alerts once per window rather than once per message). Your
message's status in the gateway is never affected by a webhook failure.

If your endpoint returns a non-2xx, we log the status and body (first 200 chars) and
retry. A `401` therefore shows up on our side as a failed dispatch — but note we cannot
tell your `401` apart from any other rejection, so if you rotate the bearer, tell us.
