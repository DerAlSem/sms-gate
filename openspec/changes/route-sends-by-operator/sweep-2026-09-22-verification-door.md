# Свип «код против спеки»: публичная дверь верификаций и секрет

ИТОГ: backed 40 · contradicted 3 · unbacked 0 — код верификации сам кладёт код в текст SMS, а `GET /sms/{id}` отдаёт этот текст владеющему приложению: секрет уходит в ответ API мимо сторожа, который перечисляет только двери `/verifications`.

Проверены четыре требования файла `openspec/changes/route-sends-by-operator/specs/phone-verification/spec.md`: строки 11–121, 122–169, 997–1049, 1050–1168 — каждый SHALL и каждое поимённое утверждение их аннотаций. Ничего не правилось; два замера выполнены отдельными пробниками в скретчпаде (вывод приведён дословно).

---

## Находки `contradicted`

### 1. Код верификации уезжает в ответ API через `GET /sms/{message_id}` (требование «The code never appears outside the matcher»)

**Где.** `app/verification/sms_carrier.py:79-81` складывает код в текст сообщения и создаёт строку `messages` с тем же `app_id`, что у верификации. `app/db/queries.py:84-95` (`get_message`) отбирает строку **только** по `id` и `app_id` — признак `verification_id` не спрашивается. `app/api/router.py:72-80` отдаёт её как `SmsStatusResponse`, а `app/api/schemas.py:33` включает в ответ поле `text`.

**Почему сторож этого не ловит.** `tests/test_the_code_and_who_may_spend_it.py:484` — перечисление снято с роутера, но перед самим утверждением стоит фильтр:

```python
if model is None or not getattr(route, "path", "").startswith("/verifications"):
    continue
```

Дверь `/sms/{message_id}` отсечена **до** проверки. Это ровно та форма, на которой обжёгся подтверждающий апдейт `check_verification`: проверка настоящая, но обесценена тем, что стоит перед ней. Аннотация говорит «перечислено от роутера, а не от списка» — и это правда как написано; неправда — вывод, что следующая дверь этой способности покрыта: покрыты только двери, чей путь начинается с `/verifications`, а код уходит соседней.

**Сценарий отказа.** Приложение открывает верификацию на чужой номер, выбирает рунг `sms_out`, затем перебирает `GET /sms/{n}` рядом с идентификатором своей последней обычной отправки (идентификаторы сквозные и целые, чужие дают 404, свои — 200) и читает код из `text`. Дальше `POST /verifications/{id}/check` подтверждает верификацию, **не дождавшись, чтобы SMS вообще дошла до человека** — то самое «a code returned here lets an application confirm a verification without the call ever reaching the person», ради которого требование написано.

**Замер** (`scratchpad/probe_sms_door.py`, база в памяти, реальный роутер и реальные миграции):

```
attempt: Attempt(outcome='carried', ..., vendor_ref='1', route='sms_out')
GET /sms/1 -> 200
body: {'id': 1, ..., 'text': 'Your code is 7351', ...}
CODE IN RESPONSE: True
check -> 200 {'id': 1, 'status': 'confirmed', 'outcome': 'confirmed'}
```

**Дыру завела эта заявка.** До `sms_carrier` (задача 4.27) код верификации в `messages.text` не попадал вообще, так что это не унаследованное состояние.

⚠️ Рядом, но НЕ находка: `app/admin/templates/messages.html:75` рисует тот же `m.text` оператору. Требование перечисляет ответ API, уведомление оператору и строку лога; консоль в этом перечне не названа, а панель верификаций код не показывает по построению (`queries.verifications_for_phone`, `app/db/queries.py:2112-2124`, колонки перечислены, `code` среди них нет). Оставляю наблюдением, а не приговором.

### 2. Нормализация `gateway_msisdn` обходится дверью `seed_from_env` (требование «A verification request names only the number…»)

**Утверждение аннотации:** «`gateway_msisdn` is a validated setting **type** (`msisdn`) … so **a second door that saves settings cannot be a door that forgot it**».

**Где ломается.** `app/settings_store.py:624-641` (`set_many`) действительно сперва зовёт `normalize_raw`, потом `validate_raw` — эта дверь чистая. Но `app/settings_store.py:658-675` (`seed_from_env`) пишет значение переменной окружения **сырым**:

```python
raw = env_val if env_val is not None else to_str(spec.type, spec.default)
...
await db.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, raw))
```

Ни `normalize_raw`, ни `validate_raw`. Это вторая дверь, сохраняющая настройки, и она именно «дверь, которая забыла». Вызывается на старте: `app/main.py:39`.

**Сценарий отказа.** `gateway_msisdn` — ключ, заведённый этой заявкой, значит на живом хозяйстве строки под него ещё нет, и первая же выкатка попадает в ветку сидирования. `GATEWAY_MSISDN=8 (926) 123-45-67` в окружении → значение уходит в `settings` как набрано → `Registry._number_for` (`app/verification/routes.py:356-358`) отдаёт его приложению как **данные** в `RouteOffer.number`. Отказ немой ровно так, как описан в самом требовании: приложение строит `tel:` по этой строке, абонент набирает адрес, который никуда не ведёт, окно закрывается, верификация рапортует `expired` — неотличимо от человека, который просто не позвонил.

**Замер** (`scratchpad/probe_seed.py`: `seed_from_env()` как в `app/main.py`, затем реальная дверь):

```
stored gateway_msisdn: '8 (926) 123-45-67'
200
  call_in | number = '8 (926) 123-45-67'
  sms_out | number = None
```

Сторож `tests/test_the_gateways_own_number_is_normalised_when_saved.py` спрашивает настройку и дверь, но не эту дверь, поэтому зелен. `bite-the-number-normalised-when-saved.sh` кусает пять мест и все пять — внутри `validate_raw`/`normalize_raw`; мутация «проверка снята с сидирования» не написана, потому что проверки там и нет.

**Оговорка честности.** Путь требует `GATEWAY_MSISDN` в окружении на хозяйстве, где строки ещё нет. Через админку значение нормализуется правильно. Требование при этом сформулировано абсолютно («SHALL be refused at the moment it is saved»), и аннотация утверждает невозможность забывшей двери — а она есть.

### 3. Первый SHALL требования 11–121 и два его сценария описывают одношаговую дверь, а код двухшаговый

**Что сказано.** «The gateway SHALL choose the method from the routing rule, SHALL return that choice in the same response together with the verification's id», и сценарии: «the response carries the verification id and names the call method, **and the call is placed**»; «the response names the Telegram method rather than the call, and no call is placed».

**Что в коде.** `app/api/router.py:128-188`: `POST /verifications` возвращает `VerificationCreateResponse` со **списком** `routes: list[RouteOffer]` (`app/api/schemas.py:87-92`), метод не выбран, и в собственной докстроке двери написано «place nothing». Метод называется и рунг кладётся только в `POST /verifications/{id}/route` (`app/api/router.py:191-330`).

**Сценарий отказа.** Приложение, написанное по этому требованию, шлёт `POST /verifications`, получает 200, читает «метод» — и его там нет; ждёт звонка — он не поставлен; верификация доживает до `expires_at` и гаснет. Чтобы что-то произошло, нужна четвёртая дверь, которой этот абзац не называет (его список владения перечисляет три: `POST /verifications`, `.../check`, `GET /verifications/{id}`).

🔴 **Средство, скорее всего, в спеке, а не в коде.** Двухшаговая форма — не самодеятельность: её отдельно требует «Selecting a rung the gateway places walks the ladder inside that selection» (строки 1215+) в этом же блоке `## ADDED`, и её же несёт контракт `docs/verification-api.md:18-21`. То есть два ADDED-требования одной дельты противоречат друг другу, и код следует более позднему. Остальные половины требования 11–121 (ладдер, «метод — тот рунг, что принял», номер как данные) с кодом согласны — они писались уже под двухшаговую дверь. Устарел вступительный абзац и два сценария.

---

## Требование 1 (строки 11–121): «A verification request names only the number, and the gateway answers with the method»

Исход: **contradicted** по двум пунктам (см. находки 2 и 3), остальное backed.

| Утверждение | Исход | Доказательство | Что именно проверено |
|---|---|---|---|
| Принимает номер и ничего, что решает «как» | backed | `app/api/schemas.py:56` | `extra="forbid"` на модели запроса: поле с маршрутом/вендором/оператором даёт 422, а не частичное исполнение |
| Выбирает метод по правилу и возвращает его в том же ответе | **contradicted** | `app/api/router.py:183-188` | ответ несёт список предложений и `status="pending"`; метода нет, ничего не поставлено |
| Не принимает запрос, который заведомо не исполнит | backed | `app/api/router.py:146-177` | `unavailable(offers)` → 422 `no_route_available`; отдельная ветка `no_template`, ключённая на оставшиеся рунги, а не на правило |
| Ответ говорит, что делать человеку, и не называет SIM/модем/вендорский аккаунт | backed | `app/verification/routes.py:150-172`, `app/api/schemas.py:74-84` | инструкции — адреса («открой Telegram», «позвони на номер»); идентичности (какой аккаунт Gateway платил, какая симка) в модели нет |
| Способность остаётся владельцем трёх дверей | backed | `app/api/router.py:128,364,383` | все три на этом роутере, метод — вариант внутри, а не своя способность |
| Названный метод — рунг, который принял, а не первый попытанный | backed | `app/api/router.py:319-330`, `app/db/queries.py:987-1016` | ответ читается из хранилища после ходки; `set_carrying_route` перекрывает заявку фактом |
| Номер как данные на рунгах, где действует абонент | backed | `app/verification/routes.py:346-358`, `app/api/schemas.py:84`, `app/api/router.py:186,411` | `_number_for` ключён на `_NEEDS_GATEWAY_NUMBER` — тот же набор, что и предусловие `_is_offerable`; оба места ответа собирают поле |
| `null` там, где действует шлюз, и согласие с прозой | backed | `app/verification/routes.py:356`, `tests/test_the_call_rung_is_reachable.py:489-503` | сторож требует и равенства полю, и вхождения в `instruction`, и `None` на `sms_out`/`flash_call`/`tg_gateway` |
| Хранится в нормализованной форме, отказывается при сохранении | **contradicted** | `app/settings_store.py:658-675` | `seed_from_env` пишет значение окружения сырым, мимо `normalize_raw`/`validate_raw` (находка 2) |
| Аддитивность — свойство модели, а не двери | backed | `tests/test_the_call_rung_is_reachable.py:515-525` | сторож строит `Offer` без поля и читает `None`, то есть спрашивает умолчание, а не HTTP |
| `bite-the-number-as-data.sh` — четыре мутации | backed | `openspec/changes/route-sends-by-operator/bite-the-number-as-data.sh:48,55,62,67` | ровно четыре, и именно названные: поле теряется у двери, номер на всех рунгах, расхождение с прозой, снятое умолчание |
| Контракт несёт поле | backed | `docs/verification-api.md:74-105` | `number` в примере ответа на `call_in`/`sms_in` и `null` на `flash_call`, с абзацем «читай это, если пишешь свою формулировку» |

## Требование 2 (строки 122–169): «The gateway generates the code and never accepts one from the application»

Исход: **backed целиком.**

| Утверждение | Исход | Доказательство | Что именно проверено |
|---|---|---|---|
| Свой код от приложения отвергается, а не молча чтится | backed | `app/api/schemas.py:66-71` | валидатор поля бросает на любом не-`None`; ответ 422 до того, как что-то создано |
| Отказ раньше, чем появится строка | backed | `app/api/router.py:131` + `:179` | валидация тела — в подписи обработчика, `create_verification` строкой 179; `tests/…:143` проверяет и отказ, и что верификаций не открылось |
| Код — четыре цифры | backed | `app/api/router.py:112,119` | `f"{secrets.randbelow(10000):04d}"`, `0000` перечеканивается (вне диапазона uCaller), а не сужается диапазон розыгрыша |
| Любой маршрут умеет его нести | backed | `app/verification/tg_gateway.py:228`, `app/verification/sms_carrier.py:79`, `app/verification/ucaller.py:381` | 4–8 цифр у Telegram, композиция в текст у модема, строковый `code` у uCaller |
| Две открытые верификации на один номер не делят код | backed | `app/api/router.py:178`, `app/db/queries.py:942-955` | живое множество читается по номеру и статусу и действительно исключается в `_new_code` |
| На `tg_gateway` `code` всегда передан, `code_length` не используется | backed | `app/verification/tg_gateway.py:225-250` | тело собирается без `code_length` вовсе, а пустой/нечисловой `code` — `ValueError` до вызова вендора |
| `bite-code.py` существует и первые четыре мутации бьют сюда | backed | `openspec/changes/route-sends-by-operator/bite-code.py:35-50` | файл на месте, 19 мутаций, №1–4 — принятый чужой код, чеканка без опроса живых, прочитанное и проигнорированное множество, контроль на чужой номер |

⚠️ Наблюдение (не находка): распознавание-и-чеканка у `_new_code` — это read-then-act. Две одновременные `POST /verifications` на один номер могут обе прочитать пустое множество; совпадение при этом требует ещё и одинакового розыгрыша — один из 9999. Требование говорит «SHALL NOT carry the same code», сценарий спеки последовательный, и ровно эту форму заявка уже вычистила там, где ценой были деньги (`claim_paid_rung`). Здесь цена — атрибуция одного ответа двум верификациям.

## Требование 3 (строки 997–1049): «The code never appears outside the matcher»

Исход: **contradicted** по первому SHALL (находка 1), остальное backed.

| Утверждение | Исход | Доказательство | Что именно проверено |
|---|---|---|---|
| Кода нет в ответе API | **contradicted** | `app/db/queries.py:84-95`, `app/api/router.py:72-80` | `GET /sms/{id}` отдаёт `text` сообщения, несущего код, владеющему приложению (находка 1) |
| Кода нет в уведомлении оператору | backed | `app/modem/manager.py:1350-1367` | `_spawn_dispatch` требует `redact` без умолчания и вырезает живые коды **из объявления**, оставляя трафик нетронутым; `tests/…:564` проверяет алерт при живом коде в строке |
| Кода нет в строке лога | backed | `tests/test_the_code_and_who_may_spend_it.py:533-562` | сторож гонит путь, где код **действительно** уехал вендору (`sends[0]["code"] == "9137"`), и только тогда читает логи на `app` при DEBUG |
| Читает только тот, кто отвечает на `/check`; `RouteSelectResponse` — единственное исключение и оно принадлежит рунгу | backed | `app/api/router.py:281-286,329` | `code` заполняется только при `body.route == SMS_IN` и читается ПОСЛЕ заявки маршрута; на ходке ладдера жёстко `code=None` |
| Уничтожение на всех терминальных окончаниях | backed | `app/db/queries.py:1055,1551,1575,1644` | четыре записи `code = NULL`: провал, подтверждение, исчерпание попыток, подметание; `tests/…:597` гонит все четыре в одном прогоне |
| `_without_the_code` на границе **записи**, три писателя | backed | `app/db/queries.py:878-896,1053,1074,1246` | замена видимая (`****`), код читается до обнуления, все три писателя свободного текста проходят через функцию |
| `record_verification_rung` guarded прямым вызовом | backed | `tests/test_the_code_and_who_may_spend_it.py:643-666` | сторож зовёт границу напрямую, потому что живого вызывающего с `reason` сегодня нет |
| Перечисление снято с роутера, а не со списка | backed как написано | `tests/test_the_code_and_who_may_spend_it.py:481-490` | ответные модели действительно берутся из `router.routes`; но фильтр `startswith("/verifications")` — причина находки 1 |
| Семь мутаций `bite-code.py` на это требование | backed | `openspec/changes/route-sends-by-operator/bite-code.py:97-128` | №13–19, ровно семь: четыре «хранит код дальше» и три «причина выносит код наружу» |

## Требование 4 (строки 1050–1168): «A verification request passes the same gates a send passes»

Исход: **backed целиком.**

| Утверждение | Исход | Доказательство | Что именно проверено |
|---|---|---|---|
| Нормализация по правилу `POST /sms/send` | backed | `app/api/schemas.py:19-22` и `:61-64` | обе двери зовут один `validate_and_normalize(v, store.phone_region)` |
| Отказ заблокированному номеру, той же лексикой, ничего не создав | backed | `app/api/router.py:140-144` | проверка первой строкой обработчика, до `offer()` и до `create_verification`; словарь ответа идентичен таковому у `/sms/send` |
| Сторож с положительным контролем на той же двери | backed | `tests/test_verification_api.py:135-172` | утверждается и 422, и `verifications_for_phone(PHONE) == []`; контроль — тот же номер без блокировки открывает верификацию |
| Недозвон не идёт в счётчик постоянных отказов | backed | `app/db/queries.py:465`, `app/modem/manager.py:1267` | у `record_permanent_fail` ровно один вызывающий в приложении — путь отчёта о доставке модема; ни `flash_carrier`, ни `ucaller` его не трогают |
| Шесть мутаций `bite-call-is-not-a-bad-number.sh` | backed | `openspec/changes/route-sends-by-operator/bite-call-is-not-a-bad-number.sh:45-87` | ровно шесть и именно перевёрнутых: две ветки окончания, тронутый счётчик на успешном звонке, снятая блокировка и два контроля |
| Чёрный список спрашивается на границе платной лестницы, а не только у двери | backed | `app/verification/gates.py:51-77`, `app/verification/ladder.py:155-162` | гейт читает то же `bad_numbers`; `walk` гоняет гейты до цикла рунгов, то есть до первого контакта |
| Это гейт лестницы, а не проверка в каждой двери, и он первый | backed | `app/verification/gates.py:186-188` | обе ветки возврата начинаются с `blacklist_gate`, впереди `entitlement_gate` и `ceiling_gate` |
| Спрашиваемые гейты следуют рунгам ходки, а не двери | backed | `app/verification/gates.py:186`, `app/verification/placement.py:161-168` | `for_paid_ladder` принимает `rungs` **без умолчания** и решает по `any(r in PAID_ROUTES …)`; `place` читает лестницу один раз и отдаёт один список и в ходку, и в гейты |
| Сторож гонит это через реальную дверь на штатных настройках | backed | `tests/test_a_free_walk_is_not_asked_about_money.py:82,111-160` | `may_spend` в фикстуре НЕ выдан; контроли: платная ходка всё ещё отказана, блокировка ставится ПОСЛЕ открытия верификации (значит отвечает гейт, а не дверь), неблокированный номер идёт |
| Пять мутаций `bite-free-walk-asks-no-money.sh` | backed | `openspec/changes/route-sends-by-operator/bite-free-walk-asks-no-money.sh:62-80` | ровно пять и именно названные, включая «решение по ПЕРВОМУ рунгу» и «связка по своей ходке» |
| Лимиты номера берутся в одном акте на записи платного рунга | backed | `app/verification/ladder.py:200-210`, `app/db/queries.py:1098-1120` | `limits.claim` зовётся только в ветке `route in PAID_ROUTES`; бесплатная ходка о них не спрашивает по построению |
| Отказ гейта завершает верификацию этой причиной | backed | `app/verification/placement.py:173-180`, `app/api/router.py:309-318` | `fail_verification` с причиной гейта, и дверь отвечает 422 `refused`, а не 200 под опрос |
| Нормализация подтверждена у этой двери замером, а не наличием валидатора | backed | `tests/test_the_call_rung_is_reachable.py:427-464` | национальная форма гонится через реальную дверь, спрашивается, на каком номере открылась верификация и предложен ли платный рунг (он предложится, только если оператор разрешился) |
| Три мутации `bite-normalised-before-the-operator.sh` | backed | `openspec/changes/route-sends-by-operator/bite-normalised-before-the-operator.sh:46,57,73` | ровно три: валидатор снят, валидатор вырожден в проверку существования, приведение сломано у общего источника |

---

## Что прогонялось

```
/Users/deralsem/dev/sms-gate/venv/bin/python -m pytest \
  tests/test_the_code_and_who_may_spend_it.py \
  tests/test_a_free_walk_is_not_asked_about_money.py \
  tests/test_the_call_rung_is_reachable.py \
  tests/test_the_gateways_own_number_is_normalised_when_saved.py \
  tests/test_verification_api.py \
  tests/test_a_failed_call_is_not_a_bad_number.py -q
→ 92 passed
```

Все названные аннотациями файлы, символы, сторожа и укусы существуют, и заявленные числа мутаций сходятся (4 · 5 · 5 · 3 · 6 · 19). `unbacked` нет ни одного: в этой области спека нигде не обещает кода, которого нет, — она обещает код, который в двух местах обходится соседней дверью, и в одном месте описывает дверь позапрошлой формы.
