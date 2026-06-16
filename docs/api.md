# SMS Gate — API Reference

> 🇷🇺 Документация на русском. **English version below ↓** — [jump to English](#english)

<!-- Russian translation: SAME headings/sections/tables/order as the English original -->

Базовый URL: `http://<your-host>:8000` (конкретный хост/порт зависит от вашего развёртывания)

Все эндпоинты требуют заголовок `Authorization: Bearer <token>`.
Каждый токен привязан к `app_id` (например, `my_bot`, `another_app`). Токены
управляются в админ-интерфейсе по адресу `/admin/apps`.

---

## POST /sms/send

Отправить SMS-сообщение.

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
| phone | string | Обязательное. Проверяется библиотекой `phonenumbers` относительно настроенного региона (по умолчанию `RU`). Ввод в национальном формате принимается и нормализуется в E.164 на входе. Регион настраивается в `/admin/settings`. |
| text | string | Обязательное. 1-1000 символов. Принимается любой Unicode — шлюз автоматически выбирает GSM 7-bit или UCS2 и разбивает длинный текст на составные (multipart) SMS. Точный лимит частей задаётся на стороне сервера настройкой `max_sms_parts`; слишком длинные сообщения отклоняются как `failed`. |

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
      "msg": "Invalid phone number for region RU",
      "type": "value_error"
    }
  ]
}
```

### Response 422 (blacklisted)

Возвращается, когда у номера накопилось 5+ постоянных ошибок доставки и ноль успешных доставок. Сообщение **не** ставится в очередь. Чтобы снять блокировку, оператор должен удалить номер из чёрного списка через админ-интерфейс.

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

Получить статус SMS по ID. Приложение видит только свои собственные сообщения.

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
| `pending` | Принято, ожидает отправки на модем |
| `sent` | Отправлено через модем, ожидается отчёт о доставке |
| `delivered` | Получен отчёт о доставке от оператора |
| `failed` | Модем вернул ошибку или истёк тайм-аут отправки |
| `expired` | Нет отчёта о доставке в пределах тайм-аута (настраивается, по умолчанию 24ч) |

Запоздавший `+CDS`, пришедший **после** того, как сообщение было помечено как `expired`, всё равно обновит его статус на `delivered` или `failed` (логируется как "late +CDS").

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
| 200 | Успех |
| 401 | Отсутствует или недействителен Bearer-токен |
| 404 | Сообщение не найдено или принадлежит другому приложению |
| 422 | Ошибка валидации ЛИБО номер в чёрном списке (`detail.error == "number_blacklisted"`) |
| 503 | Модем недоступен (ошибка последовательного порта) |

---

## Admin UI

Только браузерный админ-интерфейс по адресу `/admin/...`, защищённый HTTP Basic-аутентификацией (учётные данные в `.env`: `ADMIN_USER`, `ADMIN_PASSWORD`).

| Path | Description |
|------|-------------|
| `/admin/messages` | Постраничный список всех сообщений с фильтрами по статусу и номеру |
| `/admin/blacklist` | Автоматически наполняемый список плохих номеров с ручной разблокировкой |
| `/admin/stats` | Подсчёты по статусам + разбивка за 14 дней |
| `/admin/apps` | Управление клиентскими приложениями и их Bearer-токенами |
| `/admin/settings` | Настройки времени выполнения (например, `phone_region` для валидации номера) |

### Blacklist policy

Номер добавляется в чёрный список после **5 постоянных ошибок доставки** (TP-Status `0x40-0x5F` по GSM 03.40) **и** ноля успешных доставок. Успешная предыдущая доставка — постоянная защита: такой номер уже никогда не попадёт в чёрный список. Ручная разблокировка через админ-интерфейс полностью удаляет строку (счётчик сбрасывается).

---

<a id="english"></a>
## English

> 🇬🇧 Russian version above ↑

Base URL: `http://<your-host>:8000` (exact host/port depends on your deployment)

All endpoints require `Authorization: Bearer <token>` header.
Each token is tied to an `app_id` (e.g. `my_bot`, `another_app`). Tokens are
managed in the admin UI at `/admin/apps`.

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
| phone | string | Required. Validated by the `phonenumbers` library against the configured region (default `RU`). National-format input is accepted and normalized to E.164 on ingress. The region is configurable at `/admin/settings`. |
| text | string | Required. 1-1000 characters. Any Unicode is accepted — the gateway picks GSM 7-bit or UCS2 automatically and splits long text into concatenated (multipart) SMS. The precise part limit is enforced server-side by the `max_sms_parts` setting; over-long messages are rejected as `failed`. |

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
      "msg": "Invalid phone number for region RU",
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
| `/admin/apps` | Manage client apps and their Bearer tokens |
| `/admin/settings` | Runtime settings (e.g. `phone_region` for phone validation) |

### Blacklist policy

A phone is added to the blacklist after **5 permanent delivery failures** (TP-Status `0x40-0x5F` per GSM 03.40) **and** zero successful deliveries. Successful prior delivery is a permanent shield — that phone never gets blacklisted. Manual unblock via admin UI deletes the row entirely (counter resets).
