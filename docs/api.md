# SMS Gate — API Reference

Base URL: `http://<server>:80`

All endpoints require `Authorization: Bearer <token>` header.
Each token is tied to an app_id (e.g. `sp_bot`, `rk_bot`).

---

## POST /sms/send

Send an SMS message.

### Request

```http
POST /sms/send
Authorization: Bearer abc123def456
Content-Type: application/json

{
  "phone": "+79991234567",
  "text": "Your code: 4821"
}
```

### Validation Rules

| Field | Type | Rules |
|-------|------|-------|
| phone | string | Required. Russian mobile only: must match `+79XXXXXXXXX` (11 digits, starts with `+79`) |
| text | string | Required. 1-160 characters (single SMS segment) |

### Response 200

```json
{
  "id": 42,
  "status": "pending"
}
```

### Response 422 (validation)

```json
{
  "detail": [
    {
      "loc": ["body", "phone"],
      "msg": "Phone must be a Russian mobile number in +79XXXXXXXXX format",
      "type": "value_error"
    }
  ]
}
```

### Response 422 (blacklisted)

Returned when the phone has accumulated 5+ permanent delivery failures and zero successful deliveries. Message is **not** queued. To clear, an operator must remove the phone from the blacklist via the admin UI.

```json
{
  "detail": {
    "error": "number_blacklisted",
    "phone": "+79991234567"
  }
}
```

### Response 401

```json
{
  "detail": "Invalid or missing token"
}
```

---

## GET /sms/{id}

Get SMS status by ID. App can only see its own messages.

### Request

```http
GET /sms/42
Authorization: Bearer abc123def456
```

### Response 200

```json
{
  "id": 42,
  "phone": "+79991234567",
  "text": "Your code: 4821",
  "status": "delivered",
  "created_at": "2026-04-17T12:00:00",
  "sent_at": "2026-04-17T12:00:01",
  "delivered_at": "2026-04-17T12:00:03",
  "error": null
}
```

### Status Values

| Status | Meaning |
|--------|---------|
| `pending` | Accepted, waiting to be sent to modem |
| `sent` | Sent via modem, awaiting delivery report |
| `delivered` | Delivery report received from operator |
| `failed` | Modem returned error or send timeout |
| `expired` | No delivery report within timeout (configurable, default 24h) |

A late `+CDS` arriving **after** a message has been marked `expired` will still update its status to `delivered` or `failed` (logged as "late +CDS").

### Response 404

```json
{
  "detail": "Message not found"
}
```

---

## Error Codes Summary

| HTTP Code | Meaning |
|-----------|---------|
| 200 | Success |
| 401 | Missing or invalid Bearer token |
| 404 | Message not found or belongs to another app |
| 422 | Validation error, OR phone is blacklisted (`detail.error == "number_blacklisted"`) |
| 503 | Modem unavailable (serial port error) |

---

## Admin UI

Browser-only admin at `/admin/...`, protected by HTTP Basic auth (credentials in `.env`: `ADMIN_USER`, `ADMIN_PASSWORD`).

| Path | Description |
|------|-------------|
| `/admin/messages` | Paginated list of all messages with status & phone filters |
| `/admin/blacklist` | Auto-populated bad-numbers list with manual unblock |
| `/admin/stats` | Status counts + 14-day breakdown |

### Blacklist policy

A phone is added to the blacklist after **5 permanent delivery failures** (TP-Status `0x40-0x5F` per GSM 03.40) **and** zero successful deliveries. Successful prior delivery is a permanent shield — that phone never gets blacklisted. Manual unblock via admin UI deletes the row entirely (counter resets).
