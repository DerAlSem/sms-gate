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

## Webhooks

Вместо опроса шлюз может **сам звонить** вашему приложению. Оба вебхука настраиваются
оператором на `/admin/settings` как JSON-список маршрутов; общие для обоих `POST retries`
и `POST timeout`. Аутентификация — `Authorization: Bearer <token>` из маршрута.

| Настройка | Направление | Маршрутизация | Тело |
|-----------|-------------|---------------|------|
| `inbound_dispatch` | входящая SMS → приложение | по первому слову текста (`prefix`) | `{phone, text, received_at?}` |
| `delivery_dispatch` | статус исходящего → приложение | по `app_id` сообщения | `{id, status, error, occurred_at, resent_from?}` |

Доставка вебхука — **best-effort**: до 3 попыток, затем сообщение отбрасывается, а
оператору уходит алерт в Telegram. `GET /sms/{id}` остаётся источником правды, поэтому
опрос — это пол, а вебхук — ускоритель поверх него. Полный контракт исходящих статусов
для приёмной стороны: [`delivery-webhook.md`](delivery-webhook.md).

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
| `/admin/messages` | Вкладка «СМС»: исходящие и входящие одним потоком за выбранный период, с фильтрами по номеру, статусу и направлению. Строка раскрывается в переписку с этим номером — там же ответ, переотправка, удаление и чёрный список |
| `/admin/inbound`, `/admin/dialogs`, `/admin/dialogs/{phone}` | Редиректы на вкладку «СМС» (были отдельными вкладками) |
| `/admin/blacklist` | Список плохих номеров: автоматический и ручной, с разблокировкой |
| `/admin/stats` | Подсчёты по статусам и входящим за выбранный период + разбивка по часам, дням или месяцам |
| `/admin/apps` | Управление клиентскими приложениями и их Bearer-токенами |
| `/admin/settings` | Настройки времени выполнения (например, `phone_region` для валидации номера) |

### Blacklist policy

Номер добавляется в чёрный список автоматически — после **5 постоянных ошибок доставки** (TP-Status `0x40-0x5F` по GSM 03.40) **и** ноля успешных доставок. Успешная предыдущая доставка — постоянная защита: такой номер уже никогда не попадёт в чёрный список автоматически.

Оператор может заблокировать номер вручную — прямо из переписки на вкладке «СМС». Ручная блокировка не трогает счётчик ошибок: это не ошибка доставки. Разблокировка снимает блокировку, **сохраняя** накопленную историю отказов, — иначе номер, заслуженно набравший порог, получал бы полный новый бюджет ошибок при каждой разблокировке.

Блокировка действует на всех путях создания сообщений, включая ответ через Telegram.

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

## Webhooks

Instead of polling, the gateway can **call your app**. Both webhooks are configured by the
operator on `/admin/settings` as a JSON list of routes and share the `POST retries` /
`POST timeout` settings. Auth is `Authorization: Bearer <token>` from the route.

| Setting | Direction | Routing | Body |
|---------|-----------|---------|------|
| `inbound_dispatch` | incoming SMS → app | first word of the text (`prefix`) | `{phone, text, received_at?}` |
| `delivery_dispatch` | outbound status → app | message's `app_id` | `{id, status, error, occurred_at, resent_from?}` |

Webhook delivery is **best-effort**: up to 3 attempts, then the message is dropped and an
operator alert is sent to Telegram. `GET /sms/{id}` stays authoritative, so polling is the
floor and the webhook is an accelerator on top of it. Full outbound-status contract for the
receiving side: [`delivery-webhook.md`](delivery-webhook.md).

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
| `/admin/messages` | The SMS tab: outbound and inbound in one stream over the selected period, filtered by number, status and direction. A row expands into the conversation with that number — reply, re-send, delete and blacklist live there |
| `/admin/inbound`, `/admin/dialogs`, `/admin/dialogs/{phone}` | Redirects to the SMS tab (they used to be tabs of their own) |
| `/admin/blacklist` | Bad-numbers list, automatic and manual, with unblock |
| `/admin/stats` | Status and inbound counts for the selected period + an hourly, daily or monthly breakdown |
| `/admin/apps` | Manage client apps and their Bearer tokens |
| `/admin/settings` | Runtime settings (e.g. `phone_region` for phone validation) |

### Blacklist policy

A phone is blacklisted automatically after **5 permanent delivery failures** (TP-Status `0x40-0x5F` per GSM 03.40) **and** zero successful deliveries. Successful prior delivery is a permanent shield — that phone is never blacklisted automatically.

An operator can also block a number by hand, from its conversation on the SMS tab. A manual block leaves the failure counter alone — it is not a delivery failure. Unblocking lifts the block while **keeping** the recorded failure history; deleting the row would hand a number that earned its threshold a fresh budget of failures on every unblock.

A block applies on every path that creates a message, including a reply arriving through Telegram.
