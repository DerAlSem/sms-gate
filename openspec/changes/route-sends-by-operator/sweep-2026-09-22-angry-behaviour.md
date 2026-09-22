ИТОГ злого прохода (поведение): выжило 6 · убито 0 · сужено 1 — владеющее приложение забирает собственный код через `GET /sms/{id}` и закрывает верификацию само, не дождавшись человека.

Прогон: `/Users/deralsem/dev/sms-gate/venv/bin/python`, ворктри `tg-gateway-rung`, стенды в
scratchpad сессии (в репозиторий ничего не писалось, `app/` не мутировался). Контрольный
прогон существующих сторожей —
`tests/test_the_code_and_who_may_spend_it.py`, `tests/test_delivery_hooks.py`,
`tests/test_routing_rule.py`, `tests/test_the_door_that_walks_the_ladder.py`,
`tests/test_the_gateways_own_number_is_normalised_when_saved.py` — **71 passed** при всех
семи воспроизведённых находках. Ни одна из них не красит набор.

---

## A1 — ВЫЖИЛА

**Требование:** «The code never appears outside the matcher»,
`openspec/changes/route-sends-by-operator/specs/phone-verification/spec.md:996-999` —
код «SHALL NOT appear in an API response» и читается только стороной, отвечающей на
`POST /verifications/{id}/check`.

**Воспроизведение (сквозное, до подтверждения).** Стенд: `FastAPI` + `app.api.router`,
шаблон для `app1`, правило `*`/`?` → `sms_out`.

```
create:  200  {'id': 1, 'routes': [{'route': 'sms_out', ...}]}
select:  200  {'route': 'sms_out', 'code': None}          ← дверь верификации кода не отдала
messages: [{'id': 1, 'text': 'SokolParking: 3164 is your code', 'verification_id': 1}]
GET /sms/1 → 200 {'text': 'SokolParking: 3164 is your code', ...}
app harvested code: 3164
CHECK: 200 {'id': 1, 'status': 'confirmed', 'outcome': 'confirmed'}
```

**Чем доказано в коде.** `app/verification/sms_carrier.py:79-81` кладёт
`template.compose(wording, code)` в `messages.text`;
`app/api/router.py:73-80` → `app/db/queries.py:84-95` — `SELECT ... text ... WHERE id = ? AND
app_id = ?`, и `app/api/schemas.py:33` объявляет `text: str` в `SmsStatusResponse`.
Скоуп по `app_id` дверь не закрывает: сообщение верификации заведено под тем же `app_id`,
то есть принадлежит именно тому, кому код нельзя отдавать.

**Почему сторож слеп.** `tests/test_the_code_and_who_may_spend_it.py:484` —
`if model is None or not getattr(route, "path", "").startswith("/verifications"): continue`.
Перепись берётся «из роутера, а не из списка» (это её собственное обоснование), но фильтр
по префиксу пути превращает её обратно в список: `/sms/{message_id}` в перепись не входит,
хотя несёт код в `text`. Поле `code` в `SmsStatusResponse` отсутствует — перепись ищет имя
поля, а утечка идёт полем `text`, так что сторож не поймал бы дверь и без фильтра.

**Убийцы не нашлось.** `app/modem/delivery_dispatch.py:75-77` действительно не пушит
message-status по сообщению, которым владеет верификация, — но это закрывает push, а не
опрос: docstring того же модуля (строка 10) прямо называет `GET /sms/{id}` авторитетным
полом для опроса. Идентификатор сообщения приложению угадывать не нужно в смысле перебора:
`messages.id` — сквозной автоинкремент, приложение знает id собственных обычных отправок и
читает соседние.

**Настоящая сила.** Полная отмена гарантии на рунге `sms_out`: владеющее приложение
подтверждает верификацию, до человека код может не доехать вовсе (в прогоне сообщение так и
осталось `pending`). Лечится **кодом**: не отдавать `text` (или отдавать вычищенным) для
сообщения с `verification_id IS NOT NULL`, и перечислять двери по response-моделям, а не по
префиксу `/verifications`.

---

## A2 — ВЫЖИЛА

**Требование:** `specs/phone-verification/spec.md:1217` — «A route SHALL NOT be offered, selected,
recorded, and then left unplaced» (требование «Selecting a rung the gateway places walks the
ladder inside that selection»).

**Воспроизведение.** `operator_routes` = `{not a list` (нечитаемо), `tg_gateway_token` задан,
`may_spend` выдан:

```
rule raw: '{not a list'
create: 200 {'routes': [{'route': 'tg_gateway', ...}]}    ← рунг предложен
select: 500 Internal Server Error
verifications: [{'id': 1, 'status': 'pending', 'route': 'tg_gateway', 'reason': None}]
rungs: []
```

Ровно заявленное состояние: предложено, выбрано, заявка записана, ничего не размещено.

**Чем доказано в коде.** `app/verification/placement.py:137` — `named = rule.route_for(operator)`
без `except rule.UnreadableRule`, тогда как оба других читателя правила её ловят:
`app/modem/manager.py:695-699` и `app/verification/probes.py:157-163`.
Порядок в двери решает исход: `app/api/router.py:242` пишет `select_route` (заявку) **до**
`_walk_the_ladder`, а `ladder_from` зовётся в `placement.place` **до** `ladder.walk`, то есть
до ворот — так что ни ворота (`entitlement`, `ceiling`), ни `rule.refuses` не успевают.

**Почему не убивает probe.** `_sms_out_probe` нечитаемое правило ловит и рунг снимает
(`app/verification/probes.py:158-163`), но `_tg_gateway_probe` правило вообще не читает — он
держится на токене. Поэтому при нечитаемом правиле остаётся ровно один предложенный рунг, и
это тот самый, который падает 500.

**Предусловие достижимо конфигурацией, а не только руками в базе.** `store.set_many` прогоняет
`validate`, но `seed_from_env` (`app/settings_store.py:659-675`) — нет: `OPERATOR_ROUTES` из
окружения на первом старте ложится в `settings` сырым (проверено, см. A4).

**Настоящая сила.** Верификация зависает `pending` с занятой заявкой; повторный выбор
отвечает `already_selected` (`app/api/router.py:229-234`), новая верификация упирается в тот
же 500 — пока правило нечитаемо, рунг `tg_gateway` не размещается ни для кого, и ни одна
строка в `verification_rungs` этого не помнит. Лечится **кодом**: ловить `UnreadableRule` в
`ladder_from`/`place` и отказывать так же, как это делают два других читателя.

---

## A3 — ВЫЖИЛА

**Требование:** `specs/outbound-routing/spec.md:289-349`, ключевая строка 324 — «Nothing SHALL be delayed, held or
failed because the recipient's operator is unknown, unresolved **or stale**» и «The bound SHALL
be spent only where the cache holds no operator at all».

**Воспроизведение (замер).** В кеше есть оператор — строка просто протухла
(`checked_at` = −400 дней при `voxlink_cache_ttl_days = 7`), `voxlink.lookup` отвечает за 3 с:

```
cached row: {'operator': 'МТС', 'region': 'Москва', 'checked_at': '2025-08-18 12:59:53'}
create: 200 took 3.01s
DOOR WAITED ON A STALE-BUT-PRESENT ROW: True
```

**Чем доказано в коде.** `app/api/router.py:182` — `await record_operator(body.phone)` без
условия и без собственного бюджета; `app/lookup/operator.py:35-40` пропускает только
**свежую** строку (`cached is not None and not is_stale(...)`), а протухшую ведёт в
`voxlink.lookup` (строка 42), где бюджет — `store.voxlink_timeout` (значение по умолчанию
5.0 с, `app/settings_store.py:47`), а не `operator_lookup_bound` (5.0 с,
`app/settings_store.py:308`) и не `verification_probe_timeout`. Отправитель ту же развилку
проходит правильно: `app/modem/manager.py:605-608` сперва `_cached_operator`, и только на
пустоте тратит бюджет — с комментарием «A stale row is used as it stands», который в двери
не исполнен.

**Настоящая сила, уже, чем «дверь медленная».** Ждут не редкие первые номера, а **любой номер,
которого не трогали неделю** — при шипованном TTL в 7 дней это обычный трафик. Потолок задержки
— один `voxlink_timeout` поверх уже потраченного `verification_probe_timeout`, то есть до ~10 с
на `POST /verifications` при недоступном воксинке. Маршрут от этого ожидания не меняется ни
разу (оператор в строке уже есть) — то есть это чистая трата. Ничего не падает: `lookup`
fail-open. Лечится **кодом**: ждать только при `cached is None`, и бюджетом двери, а не
вендора.

---

## A4 — ВЫЖИЛА

**Требование:** `specs/phone-verification/spec.md` — номер шлюза нормализован или отказан
**в момент сохранения**; `app/settings_store.py:149-160` держит это как тип `msisdn` и прямо
говорит, зачем: «the value goes out to applications as **data** — `RouteOffer.number` exists
precisely so a consumer can build a `tel:` on it».

**Воспроизведение.** `GATEWAY_MSISDN="8 (926) 123-45-67"` в окружении, `seed_from_env()` — то
самое, что зовёт `app/main.py:39`:

```
store.gateway_msisdn = '8 (926) 123-45-67'
create: 200
  offer: call_in number = '8 (926) 123-45-67'
```

Национальная форма доехала до `RouteOffer.number`, то есть до `tel:` на чужом экране.

**Чем доказано в коде.** `app/settings_store.py:669-675` — `env_val = os.environ.get(spec.key.upper())`
и сразу `INSERT INTO settings (key, value) VALUES (?, ?)`. Ни `normalize_raw`
(`app/settings_store.py:504`, ветка `msisdn` на 518), ни `validate_raw`
(`app/settings_store.py:400`, ветка `msisdn` на 460) здесь не зовутся — в отличие от
`set_many` (`app/settings_store.py:628-631`), где зовутся обе.

**Сторожа нет.** `tests/test_the_gateways_own_number_is_normalised_when_saved.py` целиком
ездит через `store.set_many` и `TestClient` поверх уже нормализованного значения;
`tests/test_seed_from_env.py` проверяет только приоритет env над умолчанием
(`ALERT_CHAT_ID`, `VOXLINK_TIMEOUT`) и нормализации не касается.

**Настоящая сила — шире заявленной, и это второй ключ той же двери.** Дыра не в одном
`gateway_msisdn`: `seed_from_env` пишет сырьём **любой** ключ спецификации, включая
`operator_routes` — в том же прогоне `OPERATOR_ROUTES="{not a list"` лёг в `settings` и дал
`store.get('operator_routes') == '{not a list'`, то есть ровно предусловие A2. Отказ по-прежнему
немой: подписчик набирает ничего, окно закрывается, верификация отчитывается `expired`.
Ограничение честное: это одноразовая миграция — только ключ, у которого ещё нет строки
(первый старт эстейта или новый ключ спецификации). Лечится **кодом**: прогнать
`normalize_raw` + `validate_raw` над значением из окружения, и отказать громко на старте, а не
принять молча.

---

## A5 — СУЖЕНА

**Требование:** `specs/outbound-routing/spec.md:461-463` (SHALL строк 461-463) — «A confirmed ability check SHALL be
followed by exactly one `sendVerificationMessage` carrying its `request_id`. It SHALL NOT be
abandoned».

**Сценарий реален — воспроизведён.** Подтверждённая (оплаченная) проверка, и пока вендор
отвечает (замеренные 260 мс), владеющее приложение выжигает `verification_max_attempts`
неверными кодами через `POST /verifications/{id}/check`:

```
attempt: Attempt(outcome='failed', vendor_ref='req-1', cost=0.01,
                 reason='the verification ended before its code could be sent')
verification: status='failed' reason='no_attempts_left' code=None
sendVerificationMessage calls: []
FEE PAID AND NOTHING SENT: True
```

`app/verification/tg_carrier.py:122-133` — `row = await queries.get_verification(...)`,
`if not code:` → `ladder.FAILED` с записанным `cost`, и вызова отправки нет.

**Настоящие границы — уже, чем «подтвердилась/истекла/отменена».**

- **Истечение исключено кодом, а не вероятностью.** `app/verification/tg_carrier.py:91-98`
  отказывает рунгу до проверки способности, если остаток жизни меньше `tg_gateway.TTL_MIN`
  (`app/verification/tg_gateway.py:81` — 30 с). Значит в момент подтверждённой проверки окну
  оставалось ≥30 с, а от проверки до отправки — доли секунды; `expire_due_verifications`
  (`app/db/queries.py:1636-1648`) в эту щель не попадает.
- **«Отменена» — ветви не существует.** В `app/` нет двери, гасящей верификацию по команде;
  `grep` по `fail_verification` в `app/admin/` пуст.
- **«Подтвердилась» практически недостижима на этом рунге.** `confirm_by_inbound_call`
  (`app/db/queries.py:1358-1364`) держит `route = 'call_in'`, `confirm_by_inbound_message`
  (`1392-1398`) — `route = 'sms_in'`; заявка здесь `tg_gateway`, так что оба мимо. Остаётся
  верная догадка через `/check` — 4 цифры за 5 попыток.
- **Остаётся ровно одна достижимая ветвь:** исчерпание попыток (или та самая догадка) через
  `POST /verifications/{id}/check` внутри ~250-мс окна вендора, и совершить это может только
  владелец токена приложения.

**Настоящая сила.** Одна плата за `checkSendAbility` на случай, без пути к возврату (возврат
привязан к недоставке внутри `ttl`, а `ttl` начинается с отправки), нанесённая приложением
самому себе; человек не теряет ничего — верификация к тому моменту уже кончилась. Деньги
записаны честно: `cost` и `vendor_ref` лежат на строке рунга. Лечится **спекой** (назвать
исчерпание попыток законным основанием не отправлять, раз отправка и так пошла бы в
оконченную верификацию) **или кодом** (отправить всё равно — второй вызов с тем же
`request_id` бесплатен и делает плату возвратной).

---

## A6 — ВЫЖИЛА

**Требование:** `specs/delivery-dispatch/spec.md:85` — «Every code path that writes
`messages.status` SHALL trigger a delivery notification, **and a test SHALL enumerate those
paths** and fail when one of them does not».

**Воспроизведение — настоящим сторожем, без мутации `app/`.** Копия `app/db/queries.py` в
scratchpad с добавленным вторым `UPDATE messages SET status = 'rejected'` **внутри уже
зарегистрированной** `set_message_delivered`; `tests.test_delivery_hooks.QUERIES_PY` наведён
на копию, вызваны сами тесты:

```
KNOWN_STATUS_WRITERS:      [complete_partly_reported_messages, expire_stale_messages,
                            set_message_delivered, set_message_delivery_failed,
                            set_message_failed, set_message_sent]
writers found in mutant:   (тот же набор)
census: GREEN  ← второй, недиспетчеризованный переход прошёл насквозь
call-site guard: GREEN
```

**Чем доказано в коде.** `tests/test_delivery_hooks.py:43-55` собирает `found.add(node.name)`
— множество **имён функций**, и строка 60 сверяет `== set(KNOWN_STATUS_WRITERS)`. Значения
словаря (`"set_message_delivered": "delivered"` и т. д.) не читает никто: `KNOWN_STATUS_WRITERS`
встречается только на строках 29, 60 и 91, и на 91 — как `for writer in ...`, то есть снова по
ключам. Второй сторож (`tests/test_delivery_hooks.py:66-99`) разбирает только
`app/modem/manager.py` и ищет соседство вызова с `spawn_delivery_dispatch` — имя вызывается,
диспетчер рядом, зелено.

**Что показывает, что это не «так и задумано».** В этом же дереве соседняя перепись по той же
`queries.py` устроена на уровень строже: `tests/test_verification_outcome_reaches_the_app.py:245-259`
собирает `dict[str, set[str]]` — функция → множество написанных ею статусов — и поймала бы
вторую константу внутри уже известной функции. Сообщения такой переписи не получили.

**Настоящая сила — сторожевая, живого дефекта сегодня нет.** Замерено: все шесть писателей
живут в `app/db/queries.py` и все их вызовы — в `app/modem/manager.py` (`grep` по `app/`:
`UPDATE messages` вне `queries.py` не встречается, вызовы писателей вне `manager.py` — тоже).
То есть слепых зон у сторожа три — второй статус внутри известной функции, писатель вне
`queries.py`, вызов вне `manager.py` — и ни одна пока не занята. Требование при этом говорит
про «code path», а перепись считает функции. Лечится **кодом теста**: считать статус-литералы,
а не имена, по образцу переписи из `test_verification_outcome_reaches_the_app.py`.

---

## A7 — ВЫЖИЛА

**Требование:** `specs/phone-verification/spec.md:426` (абзац «Two different fields say `expired`…»,
внутри требования строк 359-447): «The gateway SHALL therefore **never record or act on a bare `expired`**: every
reading of that word SHALL name which of the two fields it came from».

**Воспроизведение — обычной, а не краевой последовательностью.** `ttl` сообщения выводится из
остатка жизни верификации, поэтому наше окно закрывается первым, а отчёт вендора о
**доставочном** истечении приходит следом:

```
swept: [1]                                  ← expire_due_verifications
callback: CallbackOutcome(accepted=True, verification_id=1, reason='expired')
v.status  = expired     (наше окно кода — про деньги не говорит ничего)
v.reason  = expired
r.outcome = expired     (истечение ДОСТАВКИ — возврат привязан к нему)
r.reason  = the vendor said nothing about a refund | refunded = 0
```

**Чем доказано в коде.** `app/verification/tg_callback.py:146-148` —
`outcome=status.delivery_status or "unknown"`, слово кладётся как есть, а поле, из которого
оно взято, остаётся в `reason` только косвенно (заметка про возврат).
`app/db/queries.py:1644` — `SET status = 'expired', reason = 'expired'` — вторая половина того
же: истечение **верификации** тоже записано голым словом.
`app/admin/templates/messages.html:164` и `:171` ставят `v.status` и `r.outcome` в соседние
ячейки одной строки, обе печатаются дословно.

**Настоящая сила — только половина «record»; «act on» держится.** Замерено `grep`'ом по `app/`:
ни одна ветка не сравнивает `verification_rungs.outcome` с `'expired'` (единственное сравнение
со словом — `app/verification/tg_callback.py:157`, и оно смотрит на именованное
`status.delivery_status`, то есть поле названо). Деньги тоже не путаются: возврат живёт в
отдельной колонке `refunded`, и в прогоне она заполнена правильно. Значит ущерб —
читательский: оператор в консоли (и любой будущий запрос по `outcome`) не отличит истечение
доставки от истечения окна кода, а это ровно те две вещи, из которых одна про возврат.
Лечится **кодом** (писать `delivery_expired` / `window_expired`, называя поле) — либо
**спекой**, если владелец решит, что `reason` рядом достаточно; но тогда требование надо
переписать, потому что сегодня код ему противоречит дословно.
