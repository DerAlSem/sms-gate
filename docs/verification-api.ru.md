# Коды подтверждения: переход с `/sms/send` на верификацию

## Зачем

С 22 сентября 2026 года шлюз не отправляет обычный текст абонентам МегаФона: `POST /sms/send` на такой номер заканчивается `failed`, и код этим путём не придёт. Через верификацию код дойдёт: в Telegram, а если Telegram не принял — звонком.

Всё остальное в API без изменений. Токен тот же.

## Поток

```
POST /verifications              → id и список маршрутов
POST /verifications/{id}/route   → выбрали маршрут, шлюз доставляет код
POST /verifications/{id}/check   → человек ввёл код
GET  /verifications/{id}         → статус (опрашивать)
```

Код генерирует шлюз. Своего кода не передавайте — запрос отклонят.

## 1. Создать

```http
POST /verifications
Authorization: Bearer <token>

{ "phone": "+79991234567" }
```

```json
{
  "id": 9,
  "status": "pending",
  "routes": [
    { "route": "call_in", "instruction": "Call <number> from…", "number": "<number>" },
    { "route": "tg_gateway", "instruction": "Open Telegram…", "number": null },
    { "route": "flash_call", "instruction": "Wait for a call…", "number": null }
  ]
}
```

`routes` — маршруты, которые сработают для этого номера сейчас, в порядке предпочтения. Берите первый или дайте человеку выбрать. Имена маршрутов не зашивайте: набор может меняться.

## 2. Выбрать маршрут

```http
POST /verifications/9/route

{ "route": "tg_gateway" }
```

```json
{ "id": 9, "route": "flash_call", "status": "pending", "reason": null, "code": null }
```

В ответе `route` — маршрут, который доставил код. Он может отличаться от выбранного: если Telegram отказал, шлюз сразу звонит. Показывайте подсказку по `route` из ответа.

## 3. Что показать человеку

| `route` | Что делает человек | Подсказка |
|---|---|---|
| `tg_gateway` | получает код в Telegram, вводит у вас | «Код отправлен в Telegram» |
| `flash_call` | ему звонят, код — последние 4 цифры входящего номера | «Вам позвонят. Не отвечайте: код — последние 4 цифры номера, с которого звонят» |
| `sms_out` | получает код по SMS, вводит у вас | «Код отправлен по SMS» |
| `call_in` | звонит на `number` со своего номера | «Позвоните на `number`, звонок бесплатный» |
| `sms_in` | отправляет код из поля `code` на `number` | «Отправьте код `code` по SMS на `number`» |

`instruction` приходит на английском. Номер для `call_in` и `sms_in` берите из поля `number`. Для неизвестного `route` покажите `instruction` как есть.

## 4. Проверить код

Только для `tg_gateway`, `flash_call` и `sms_out`: там человек вводит код у вас.

```http
POST /verifications/9/check

{ "code": "4821" }
```

```json
{ "id": 9, "status": "confirmed", "outcome": "confirmed" }
```

`outcome`: `confirmed`, `wrong_code`, `no_attempts_left`, `expired`, `already_confirmed`.

## 5. Статус

`call_in` и `sms_in` подтверждаются без вашего запроса. Поэтому опрашивайте `GET /verifications/{id}` раз в секунду, пока `status` = `pending`. Ответ:

```json
{
  "id": 9, "status": "confirmed", "route": "call_in", "method": "call_in",
  "reason": null, "routes": [], "attempts": 0,
  "created_at": "2026-09-21T09:14:05Z",
  "expires_at": "2026-09-21T09:19:05Z",
  "confirmed_at": "2026-09-21T09:14:41Z"
}
```

`status`: `pending`, `confirmed`, `failed`, `expired`.

## Не пришло

Верификация, которая закончилась `failed` или `expired`, не возобновляется: создайте новую. После `failed` в `routes` останутся маршруты, кроме несработавшего. Если человек нажал «не пришло», пока статус `pending`, тоже создайте новую верификацию и выберите следующий маршрут.

## Ограничения

- Срок жизни — 5 минут (`expires_at`).
- 5 попыток ввода кода.
- Telegram и звонок на один номер: не чаще раза в 15 секунд, до 4 в минуту и до 30 в сутки. Сверх лимита выбор маршрута вернёт `refused`.

## Ошибки

Везде `422` с `detail.error`, кроме `404` на чужой или несуществующий `id`.

| Где | `error` | Что делать |
|---|---|---|
| создание | `no_route_available` | сейчас доставить нельзя — сообщите человеку |
| создание | `number_blacklisted` | на этот номер код не отправить — попросите другой номер |
| создание | `no_template` | нужен ваш шаблон SMS — пришлите его нам |
| выбор | `route_not_offered` | маршрут больше недоступен — создайте новую верификацию |
| выбор | `already_selected` | маршрут уже выбран — опрашивайте статус |
| выбор | `refused` | код не отправлен, например превышен лимит (см. «Ограничения») |
| выбор | `verification_failed` / `verification_expired` | создайте новую |

Неизвестные поля в ответах игнорируйте: мы можем их добавлять.

## Пуш вместо опроса (необязательно)

Если нужен вебхук — пришлите нам `webhook_url` (`https://…`) и `bearer`. Когда верификация завершится, шлюз отправит POST:

```json
{
  "object": "verification", "verification_id": 9, "status": "confirmed",
  "method": "call_in", "reason": null, "occurred_at": "2026-09-21T09:14:41Z"
}
```

Пуш может прийти дважды. Источник правды — опрос.
