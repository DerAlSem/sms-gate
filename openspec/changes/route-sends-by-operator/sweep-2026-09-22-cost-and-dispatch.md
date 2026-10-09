# Свип «код против спеки»: деньги и оповещение

ИТОГ: backed 34 · contradicted 1 · unbacked 2 — перепись писателей `messages.status` считает ФУНКЦИИ, а не записи статуса, поэтому вторая запись внутри уже переписанной функции проходит мимо неё зелёной; всё остальное по трём требованиям держится, кроме отчётности по потраченному (агрегата спенда нет вовсе).

---

## contradicted

**1. `tests/test_delivery_hooks.py:58` (`test_status_writer_census`) считает не ту единицу.**
Требование: «Every **code path** that writes `messages.status` SHALL trigger a delivery
notification, and a test SHALL enumerate **those paths** and fail when one of them does
not». Перепись же сравнивает `_functions_writing_message_status() == set(KNOWN_STATUS_WRITERS)`
(`tests/test_delivery_hooks.py:60`) — то есть **множество имён функций**. Объявленный в
словаре статус (`"set_message_delivered": "delivered"`, строки 29–39) не сверяется ни с чем:
`set(...)` берёт только ключи.

Сценарий отказа, воспроизведён: в `app/db/queries.py` в тело уже переписанной
`set_message_delivered` (строка 438) добавляется вторая запись —
`UPDATE messages SET status = 'rejected' WHERE id = ? AND app_id IS NULL` — и никакого
`spawn_delivery_dispatch` для неё. Тогда:

* `_functions_writing_message_status()` возвращает ровно тот же набор из шести имён →
  `test_status_writer_census` **зелёный** (замер: `MUT1 census passes: True`);
* `test_every_known_writer_is_dispatched_at_its_call_site` (строка 67) смотрит
  `app/modem/manager.py` и видит `spawn_delivery_dispatch(message_id, "delivered")` рядом
  с вызовом — **зелёный**;
* приложение переходов в `rejected` не услышит никогда, набор при этом чист.

Положительный контроль на ту же машинку: НОВАЯ функция в `queries.py`, пишущая
`messages.status`, перепись роняет (`MUT2 census passes: False`), и снятие одного
`spawn_delivery_dispatch` из `manager.py` роняет вторую проверку
(`after dropping one spawn: ['set_message_delivered']`). То есть сторож жив — просто его
единица счёта крупнее единицы требования ровно на тот случай, который требование называет
«code path».

🔴 Верификационная половина этой же нормы **сделана правильно** и это доказывает, что речь
о поправимой асимметрии, а не о вкусовщине: `KNOWN_VERIFICATION_TERMINAL_WRITERS`
(`tests/test_verification_outcome_reaches_the_app.py:196`) хранит писателя **вместе с
множеством статусов**, и сверка идёт по словарю целиком (строка 271). Замер: добавление
второго `UPDATE verifications SET status = 'expired'` внутрь существующей
`confirm_by_inbound_call` перепись роняет (`MUT3 census passes: False`). Гипотеза ветки —
«один писатель держит две концовки, и перепись писателей это прячет» — на
верификационной половине НЕ подтвердилась (`check_verification: {confirmed, failed}` виден
как две концовки), а на сообщенческой подтвердилась полностью.

## unbacked

**2. «Счёт возможно-оплаченного читается рядом с приписанным спендом» — читать негде.**
Норма: «The gateway SHALL also record, separately from both, what it spent **without
getting anything for it**», сценарий «A fee that bought nothing … **and the count is
readable beside the attributed spend**». Событие записывается: неотвеченная проверка
оставляет рунг с исходом `unanswered` (`app/verification/tg_carrier.py:105-108` — ранний
возврат без `set_rung_outcome`, исход кладёт ходок; сторож
`tests/test_ladder_walk.py:147`). Но **ни счёта, ни приписанного спенда рядом не
существует**: во всём `app/` нет ни одного `SUM(cost)` и ни одной функции агрегации;
единственная поверхность со стоимостью — подробность по номеру
(`app/admin/templates/messages.html:173,185`), где печатается `cost` отдельного рунга.
Аннотация это не утверждает (она «partly backed»), так что это честная дыра, а не ложь.

**3. Спенд за месяц и спенд по приложению не отвечаются ничем, кроме ручного SQL.**
Сценарии 764–893: «A month's spend is answerable» и «The spend is answerable per
application». Данные записаны — `verification_rungs.cost` (`app/db/queries.py:1077`) и
`verifications.app_id`, — но запроса, отчёта или страницы, дающих ответ, нет: ни в
`app/db/queries.py`, ни в `app/admin/`. «Answerable» держится только на том, что строки
лежат в базе.

---

## Требование 1 — «What verifications cost is visible before the bill is» (`specs/phone-verification/spec.md:764-893`)

Исход: **backed с двумя дырами** (перечислены выше как находки 2 и 3).

### SHALL'ы

* «record the vendor's reported cost of each paid verification» — **backed**.
  `app/verification/tg_carrier.py:111,119-121` (`cost = ability.status.request_cost`,
  записывается `set_rung_outcome`), `app/verification/flash_carrier.py:159,166,169,308,319,323`
  (`cost=info.cost` на каждом исходе). Проверено: стоимость берётся из подтверждающей
  проверки и пишется в тот же рунг, который её понёс.
* «raise an operator alert when the balance falls below a configured floor» — **backed**.
  `app/verification/balance.py:107-122`; сторож `tests/test_balance_floor.py:55`
  (`3.5` против пола `10` → `notify("routing", …)`, дедуп-ключ `balance_floor:<route>`).
* «on the `tg_gateway` rung read the balance **only** from a confirming `checkSendAbility`,
  and NOT from a send, a status or a decline» — **backed**.
  `app/verification/tg_carrier.py:105-118`: чтение стоит ПОСЛЕ раннего возврата
  `if ability.kind != tg_gateway.ABLE`. Проверено опровергающим проходом: `balance.observe`
  во всём `app/` зовётся из трёх мест — эта строка и две uCaller'ских
  (`flash_carrier.py:155,301`); в пути отправки и в `app/verification/tg_callback.py` его
  нет вовсе. Поведенчески: `tests/test_balance_floor.py:178` (проверка отвечает 2.5,
  отправка 9999 — срабатывает на 2.5 и «9999» в тексте запрещено) и `:227` (ноль на
  отказе не читается).
* «SHALL NOT place a check of its own merely to read it» — **backed**.
  В `app/verification/balance.py` нет ни одного вызова вендора; сторож стоит на
  транспорте, а не на исходе — `tests/test_balance_floor.py:261`.
* «два баланса, пол против каждого отдельно, никогда над суммой» — **backed**.
  `app/verification/balance.py:62-65` (карта настроек, а не форматируемый ключ);
  `tests/test_balance_floor.py:114` (пустой найден при полном соседе) и `:132`
  (дедуп раздельный).
* «Every alert SHALL name which vendor it is about» — **backed**.
  `app/verification/balance.py:54-57,97,116`; на неизвестном рунге называется маршрут
  (`:88-93`), сторож `tests/test_balance_floor.py:298`.
* «A paid rung whose floor is not configured SHALL be reported as unwatched rather than
  read as satisfied» — **backed**. Обе ветки: нет настройки вовсе
  (`app/verification/balance.py:79-94`) и настройка пустая/ноль (`:96-105`). Сторожа
  `tests/test_balance_floor.py:144,158,284,298`.
* «Being unwatched SHALL be answerable **without an event**, and SHALL be said **where the
  floor's own alerts are said**» — **backed**.
  `app/verification/balance.py:154-175` (`report_unwatched_rungs`), позвана в
  `app/main.py:53` до `yield` и до запуска петель; обе ветки `observe` теперь зовут
  `notify` (`:88`, `:103`). Сторожа: `tests/test_balance_floor.py:319` (рунг, ничего не
  нёсший, доложен) и `:363` — половина «на старте» проверена **как AST**: `await` этого
  имени внутри `lifespan` и до `yield`.
* «A rung this gateway holds no credential for is outside that report» — **backed**.
  `app/verification/balance.py:137-151,168`; контроль `tests/test_balance_floor.py:346`.
* «A refund SHALL lower the recorded spend … what the vendor said SHALL stay recorded in
  words beside it» — **backed**. `app/db/queries.py:1309-1315`
  (`cost = CASE WHEN ? THEN 0 ELSE cost END`, `refunded` пишется только утвердительно,
  слова вендора в `reason`); сторожа `tests/test_refund_lowers_spend.py:63,79`, контроль
  «недоставленное без отметки не обнуляется» — `:95,111`.
* «A refund once recorded SHALL NOT be undone by a later write» — **backed**, и правило
  стоит в ДВУХ местах записи, а не в комментарии: `app/db/queries.py:1252`
  (`cost = CASE WHEN refunded THEN cost ELSE COALESCE(?, cost) END` в `set_rung_outcome`)
  и `:1311-1312` (в `record_rung_delivery` `refunded` не снимается никогда). Сторож
  `tests/test_refund_lowers_spend.py:125`. Опровергающий проход: других писателей
  `verification_rungs.cost` в `app/` нет — только эти две функции и вставка
  `record_verification_rung` (`:1077`), которая создаёт строку.
* «record, separately from both, what it spent without getting anything for it» —
  **unbacked** в половине «читается рядом», см. находку 2.

### Сценарии

* «The balance runs low» — **backed** (`tests/test_balance_floor.py:55,114`).
* «Telegram's balance is read from the only call that tells the truth» — **backed**
  (`tests/test_balance_floor.py:178,227`).
* «A refunded request» — **backed** (`tests/test_refund_lowers_spend.py:63`).
* «A fee that bought nothing» — **unbacked** (находка 2).
* «A month's spend is answerable» / «The spend is answerable per application» —
  **unbacked** (находка 3).

### Аннотация `[backed since 22.09.2026 · …]`

* «`balance.report_unwatched_rungs` is awaited in `app/main.py`'s lifespan before anything
  can be verified» — **backed**: `app/main.py:53`, до `yield`, до `app.state.modem` и до
  создания петель.
* «both unwatched branches of `balance.observe` now wake the operator through `notify`» —
  **backed**: `app/verification/balance.py:88,103`. Уточнение, не находка: ветки зовут
  `notify` **и по-прежнему пишут `logger.warning`**; «rather than `logger.warning`» читается
  буквально как замена, а по факту это добавление — и это намеренно, о чём говорит сам
  сторож `tests/test_balance_floor.py:158-173` («что остаётся здесь — что лог всё ещё несёт
  это тоже»).
* «the startup half is asserted **as an AST** — an `await` of that name inside `lifespan`
  and before the `yield`» — **backed** дословно: `tests/test_balance_floor.py:372-393`,
  `ast.walk`, сравнение `called_at < yielded_at`.
* «`bite-nobody-is-watching.sh` turns seven red» — **backed, прогнан**: исходное 19 passed,
  мутации 1–7 дают 1/1/1/2/1/1/1 падений соответственно, финальный прогон снова 19 passed,
  рабочее дерево после прогона чистое.

### Аннотация `[partly backed · …]`

* «the floor is `app/verification/balance.py`, held per vendor from
  `tg_gateway_balance_floor` and `flash_call_balance_floor`» — **backed**
  (`app/verification/balance.py:62-65`, `app/settings_store.py:285,292`).
* «read by the carrier from a **confirming** ability check and from nowhere else» —
  **backed для Telegram** (`app/verification/tg_carrier.py:105-118`). Уточнение: у uCaller
  баланс читается из `getInfo` (`app/verification/flash_carrier.py:155,301`), а это не
  ability check; фраза аннотации не оговаривает вендора, хотя норма над ней оговаривает.
  Не находка — расхождение в широте формулировки, не в коде.
* «guarded by `tests/test_balance_floor.py`, which drives the carrier through a check
  reporting 2.5 and a send reporting 9999» — **backed** дословно
  (`tests/test_balance_floor.py:196,203,219-222`).
* «The refund lowering the spend is `record_rung_delivery` in `app/db/queries.py`, guarded
  by `tests/test_refund_lowers_spend.py`» — **backed** (`app/db/queries.py:1274`, файл
  сторожа существует и весь зелёный: 9 тестов).
* «`app/verification/ucaller.Info.balance_after` subtracts `cost` and the carrier watches
  that rather than the vendor's figure» — **backed**: `app/verification/ucaller.py:208-216`
  (`balance` документирован как «до списания»), оба чтения идут через `balance_after`
  (`flash_carrier.py:155,301`).
* «watched as it stands the floor would fire one verification late, which mutation 9 of
  `bite-flash-call.sh` turns red» — **backed, проверено**: мутация 9 применена в памяти
  (`Info.balance_after` возвращает `balance_before`) → красным становится ровно
  `tests/test_flash_call_carrier.py::test_the_balance_watched_is_the_one_after_this_call_is_charged`,
  контроль без мутации — 56 passed.
* «the floor ships at zero» — **backed** для uCaller (`app/settings_store.py:292`, `0.0`).
  Telegram ships at `10.0` (`:285`) — речь в абзаце о uCaller, противоречия нет.
* «`is_refunded` has been absent from ten captures running … the tests drive the recording
  directly and claim nothing about having seen one» — **backed как оговорка**: тесты
  действительно зовут `record_rung_delivery` напрямую
  (`tests/test_refund_lowers_spend.py:68`), наблюдения возврата ни один из них не
  изображает.
* Мелочь на будущее, не находка: комментарий у `flash_call_balance_floor`
  (`app/settings_store.py:288-289`) всё ещё говорит «is **logged** as a vendor nobody is
  watching» — текст отстал от решения 22.09 о `notify`.

---

## Требование 2 — «The application learns a verification's outcome without polling the modem» (`specs/phone-verification/spec.md:736-763`)

Исход: **backed целиком.**

### SHALL'ы

* «learn that a verification was confirmed, failed or expired by a push to the route
  already configured for it in `delivery_dispatch`» — **backed**.
  `app/verification/dispatch.py:40-69` (`push_verification`, маршрут через
  `find_route(app_id)` из `delivery_dispatch`), `:72-112`
  (`announce_verification_outcomes`: истечение, затем ОДИН объявитель по
  `unnotified_terminal_verifications`, `app/db/queries.py:1415-1430`). Сторожа
  `tests/test_verification_outcome_reaches_the_app.py:74,118,143`.
* «or by asking `GET /verifications/{id}`» — **backed**.
  `app/api/router.py:383-415`: статус, метод, причина, `confirmed_at` — то есть «когда».
* «A push SHALL be distinguishable from a message status push, so that a receiver cannot
  mistake a verification id for a message id» — **backed**, и проверено опровергающим
  проходом. `app/verification/dispatch.py:49-62`: `object: "verification"`,
  предмет в `verification_id`, ключа `id` в теле нет вовсе. Сторож
  `tests/test_verification_outcome_reaches_the_app.py:441-494` сравнивает НАСТОЯЩУЮ
  рассылку сообщения с настоящей рассылкой верификации и требует, чтобы номер
  верификации жил ровно в одном поле.
  Три мутации, применённые в памяти (мой прогон, файлы не правились):
  вернуть `id` в тело верификации → красный; переименовать `verification_id` в
  `message_id` → красный; сдвинуть КОНТРАКТ СООБЩЕНИЯ (его `id` → `message_id`) → красный;
  контроль без мутации — зелёный.

### Сценарии

* «The outcome is pushed» — **backed**
  (`tests/test_verification_outcome_reaches_the_app.py:74,84,118`).
* «The outcome is polled» — **backed** (`app/api/router.py:408-415`, `confirmed_at`).

### Аннотация `[backed · …]`

* «`push_verification` in `app/verification/dispatch.py`» — **backed** (`:40`).
* «announced by `announce_verification_outcomes`» — **backed** (`:72`, вызов `:105`).
* «guarded by `tests/test_verification_outcome_reaches_the_app.py`» — **backed**, файл
  существует, 17 тестов, все зелёные.
* «The subject now travels in `verification_id` and `id` is absent» — **backed**
  (`app/verification/dispatch.py:57`; ключа `id` в словаре нет).
* «The guard compares a **real** message push against a real verification push rather than
  against a remembered description» — **backed**
  (`tests/test_verification_outcome_reaches_the_app.py:455-484`: реально зовётся
  `message_dispatch.dispatch_delivery`, и есть ловушка `assert message["id"] == message_id,
  "the message contract moved; re-read this test"`).
* «asserts the verification's number appears in exactly one field» — **backed**
  (`:490-494`).
* «five mutations bite, including one that moves the message contract underneath it» —
  **backed частично и по существу**: отдельного скрипта с этими пятью в заявке нет
  (`bite-late-call-outcome.sh` гоняет этот файл, но его одиннадцать мутаций — про поздний
  исход звонка, не про форму рассылки), так что число «пять» воспроизвести нечем. Три
  мутации, включая названную («moves the message contract underneath it»), я применил сам —
  все три красные. Не находка, но заявленное число опирается на незаписанный замер.
* «Measured on a file-backed database: message 1 and verification 1 collide from the first
  row of each table» — **backed по существу**: в самом стороже база `:memory:`, но обе
  таблицы в одной базе и обе начинают с 1, так что столкновение внутри теста настоящее, а
  не предположенное.

---

## Требование 3 — «Every status writer notifies» (`specs/delivery-dispatch/spec.md:83-98`)

Исход: **одна находка `contradicted`** (см. выше), остальное backed. 🔴 У требования
**нет аннотации вовсе**, то есть оно заявлено как обоснованное целиком — и на
сообщенческой половине это неверно.

* «Every code path that writes `messages.status` SHALL trigger a delivery notification» —
  **backed для сегодняшнего кода**: писателей ровно шесть, все в `app/db/queries.py`
  (`:126,139,438,447,736,781`), все вызовы — в `app/modem/manager.py`, и рядом с каждым
  стоит `spawn_delivery_dispatch` (`:803,911,937,951,1243,1255,1800,1804`).
  Опровергающий проход: `UPDATE messages … status` вне `queries.py` во всём `app/` нет.
* «a test SHALL enumerate those paths and fail when one of them does not» —
  **contradicted**, находка 1: перепись считает функции, а не записи статуса.
* «except for messages belonging to a verification, which notify as verifications instead»
  — **backed**. `app/modem/delivery_dispatch.py:76-79` — при непустом `verification_id`
  рассылка статуса сообщения не делается вовсе, управление уходит в
  `_the_verification_takes_this_outcome` (`:111-140`), которая концовку сообщения
  превращает в `fail_verification`, а объявление оставляет одному подметальщику.
* «Every code path that writes a verification's state SHALL likewise trigger a
  notification» — **backed**. Механика: каждый терминальный писатель оставляет
  `notified = 0`, один объявитель забирает строки
  (`app/db/queries.py:1415-1430`, `app/verification/dispatch.py:101-107`), и никто не
  вправе пометить свою строку объявленной — сторож
  `tests/test_verification_outcome_reaches_the_app.py:278`.
* «the same enumerating test SHALL cover those paths and fail when one of them does not» —
  **backed по существу, разошлось в букве**. Переписей ДВЕ, в разных файлах:
  `tests/test_delivery_hooks.py:58` (сообщения) и
  `tests/test_verification_outcome_reaches_the_app.py:262` (верификации); «the same … test»
  дословно неверно — сообщенческая перепись не упадёт от нового верификационного писателя.
  Убивать за это не стал: обе концовки действительно переписаны и обе переписи кусаются.
* Сценарий «A new status writer is added without a notification → the test suite fails» —
  **backed для новой ФУНКЦИИ** (`MUT2`: перепись краснеет) и **contradicted для новой
  записи внутри уже известной функции** (`MUT1`: набор остаётся зелёным). Это и есть
  находка 1.
* Сценарий «A new verification state writer is added without a notification → the test
  suite fails» — **backed**, проверено мутацией: вторая запись
  `status = 'expired'` внутри `confirm_by_inbound_call` роняет перепись
  (`MUT3`), потому что её единица счёта — пара «писатель → множество статусов».

---

## Попутно проверено по прямому указанию (вне трёх требований)

Число «в полёте» в алерте о ротации кредентиала (`app/verification/tg_callback.py:206`,
`queries.rungs_awaiting_report`, `app/db/queries.py:1320-1339`) считает рунги ЭТОГО
маршрута, у которых есть `vendor_ref` и ещё нет окончательного исхода
(`outcome IS NULL OR outcome = 'carried'`), — то есть ровно те, чьи возвраты ротация
уронит. Утверждение проверено не «на числе», а на состоянии из трёх рунгов:
`tests/test_tg_callback.py:496-524` ставит рядом рунг в полёте, уже отчитавшийся и
никогда не купленный, и требует «1 message». Чисто.

---

## Что прогонялось

* `pytest tests/test_balance_floor.py tests/test_refund_lowers_spend.py
  tests/test_delivery_dispatch.py tests/test_delivery_hooks.py
  tests/test_verification_outcome_reaches_the_app.py` — 62 passed.
* `bite-nobody-is-watching.sh` — полностью, семь мутаций красные, дерево после прогона
  чистое.
* Мутации, применённые В ПАМЯТИ через pytest-плагин в скретчпаде (ни один файл репозитория
  не правился): три на форму рассылки верификации, одна на `Info.balance_after`
  (мутация 9 `bite-flash-call.sh`), три на переписи писателей (через подмену пути к
  разобранному AST-копии `queries.py`).
