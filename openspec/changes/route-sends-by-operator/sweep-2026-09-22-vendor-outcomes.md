# Свип «код против спеки»: исходы вендора

ИТОГ: backed 39 · contradicted 2 · unbacked 0 — механика исходов вендора реализована и
охраняется, но две нормы расходятся с кодом: «голое `expired` не записывать» нарушено в
колбэке, а счёт лимитов «по рунгам, а не по верификациям» исключает собственный ход
верификации, то есть ровно тот случай, ради которого норма и написана.

Проверял: требования 278–358, 359–447, 509–554, 555–638 файла
`openspec/changes/route-sends-by-operator/specs/phone-verification/spec.md` — каждый SHALL
и каждое поимённое утверждение аннотации. Прогон точечный:
`tests/test_tg_callback.py tests/test_tg_rung_aftermath.py tests/test_per_number_limits.py
tests/test_flash_call_carrier.py tests/test_where_the_vendor_reports.py
tests/test_the_call_outcome_that_arrives_late.py tests/test_ucaller_adapter.py
tests/test_the_call_rung_is_reachable.py` — 141 passed.

---

## Находки `contradicted`

### 1. Голое `expired` всё-таки записывается — `app/verification/tg_callback.py:146-148`

Норма (spec.md:445): «The gateway SHALL therefore **never record** or act on a bare
`expired`: every reading of that word SHALL name which of the two fields it came from.»

Половина «act on» соблюдена: ветвь читает поле по имени —
`if status.delivery_status == "expired"` (`tg_callback.py:157`), и причина провала
верификации называет источник словами («the Telegram message expired undelivered»,
`tg_callback.py:164`). Половина «record» — нет.

**Сценарий отказа.** Подписанный колбэк с телом
`{"request_id":"req-1","phone_number":"7926…","delivery_status":{"status":"expired"}}`
доходит до `record_rung_delivery(status.request_id, route=TG_GATEWAY,
outcome=status.delivery_status or "unknown", reason=note, …)` (`tg_callback.py:146-148`).
В строку `verification_rungs` уезжает `outcome = 'expired'` — голое слово, а в `reason`
уходит не название поля, а заметка про возврат («the vendor said nothing about a refund»,
`tg_callback.py:189`). Поле, из которого слово пришло, в записи не названо ничем.

Дальше эта строка выводится оператору: `app/admin/templates/messages.html:171` печатает
`r.outcome` в колонке «Vendor outcome» в том же ряду, где
`app/admin/templates/messages.html:164` печатает `v.status` — а `v.status` принимает
значение `'expired'` от нашего собственного окна (`app/db/queries.py:1644`). Оператор
видит два слова `expired` рядом, и ни одно не говорит, чьё оно.

**Насколько это больно — честно.** Ущерб, которым норма мотивирована («a ledger that
confused them would refund a verification that was delivered»), сегодня не наступает:
возврат пишется из `is_refunded`, а не из слова (`queries.py:1311-1314`), и вендорский
`verification_status` не читается **вообще нигде** — он разбирается в
`app/verification/tg_gateway.py:202` и не встречается больше ни в одном чтении по `app/`.
То есть перепутать два вендорских поля код сейчас физически не может. Нарушена буква
«never record a bare `expired`», а не денежный исход. Правка — минимальная: либо
квалифицированная строка в `outcome` (`delivery:expired`), либо `reason`, называющий поле.

### 2. Лимиты не считают собственный ход верификации — `app/db/queries.py:1088`

Норма (spec.md:632-635): «the count SHALL be taken over the rung attempts of both paid
routes **rather than over verifications**: what the vendor counts is an authorisation
placed, **and one verification places more than one — that is what a ladder is**.»

`_PAID_FOR_NUMBER` — предикат, которым `claim_paid_rung` решает все три лимита, — несёт
`AND r.verification_id <> ?` (`queries.py:1088`), то есть исключает из счёта рунги той
самой верификации, которая сейчас идёт по лестнице. `_for_number` подставляет туда
`verification_id` (`queries.py:1093-1095`), и предикат используется всеми тремя клаузами
(`queries.py:1136-1138`).

**Сценарий отказа.** Номер X, верификация V. Лестница правила для оператора —
`[tg_gateway, flash_call]`. `ladder.walk` берёт платный рунг `tg_gateway` через
`limits.claim` (`ladder.py:208`) — строка записана, t=0. `checkSendAbility` отвечает
`PHONE_NUMBER_NOT_AVAILABLE` → `DECLINED` → лестница идёт дальше и через секунду берёт
`flash_call` тем же `limits.claim`. Клауза паузы
(`(_PAID_FOR_NUMBER) = 0` при `gap_seconds = 15`, `queries.py:1136`) собственную строку V
не видит, потому что исключила её по `verification_id`, — и вторая платная авторизация по
тому же номеру уходит вендору внутри пятнадцатисекундного промежутка, который спека
объявила действующим «to the ladder as a whole» (spec.md:623-630).

**Что за этим стоит и почему это не ложное убийство.** Исключение осознанное и подробно
объяснено в коде (`queries.py:1119-1124`): счёт, читающий собственный ход, сделал бы
лестницу неспособной продвинуться вообще — вторая ступень всегда берётся при возрасте
первой строки ноль секунд. Довод верный. Расходится не код с собой, а **код со спекой**:
текст требования не содержит этого исключения нигде, а приведённое им обоснование
(«one verification places more than one») описывает ровно тот случай, который код из счёта
вынул. Вендорский потолок при этом фактически не пробивается — за один ход лестница ставит
не более одной авторизации у каждого вендора, — но собственное, более строгое чтение
«лимиты ограничивают лестницу целиком» не исполняется. Чинится текстом спеки (оговорить
исключение и почему оно не ослабляет вендорский потолок), а не кодом.

---

## Требование 278–358 — «A placed call is not a delivered code» · **backed**

SHALL'ы:

- **`call_status: 1` — аналог отправленного SMS, не подтверждения; подтверждает только
  `/check`.** `app/verification/flash_carrier.py:161-166` возвращает `ladder.CARRIED` и
  ничего не подтверждает; единственный писатель `confirmed` — `queries.check_verification`
  (`app/db/queries.py:1548-1561`), и он требует `status = 'pending'`. Сторож —
  `tests/test_flash_call_carrier.py`, мутации 1–3 в `bite-flash-call.sh`.
- **Ожидание `-1` ограничено, неразрешённый исход записывается как неизвестный.**
  `flash_carrier.py:87` строит дедлайн из `seconds_left` лестницы (не из константы рунга),
  `flash_carrier.py:175-193` опрашивает до него и возвращает `None`,
  `flash_carrier.py:146-150` пишет `ladder.UNRESOLVED`. `ladder.py:241-250` на этом
  исходе **не** продвигает лестницу и **не** проваливает верификацию. Опровергающий проход:
  неверная реализация, которая тоже «ограничивает», — это таймаут вендорского вызова вместо
  бюджета лестницы; здесь это не она (граница — `deadline` рунга), и ровно эту подмену
  кусает мутация 4 `bite-flash-call.sh` («граница вендорская, а не лестницы»).
- **Правило про код вендора не переносится на другие маршруты.** Ни `tg_carrier.py`, ни
  `sms_carrier.py` не читают вендорский `code`: `tg_carrier.py:123-138` берёт код из
  хранилища и отдаёт его вендору. backed.
- **Сверяется код, который вендор назвал, и при расхождении — провал с этой причиной плюс
  будильник оператору.** Обе точки, где вендор называет код, прочитаны:
  `flash_carrier.py:141` (`initCall`) и `flash_carrier.py:157` (`getInfo`). Ветвь —
  `_mismatch`, `flash_carrier.py:206-231`: `ladder.FAILED` + `notify("routing", …)`.
  Выбрана та из двух разрешённых норм альтернатив, что проваливает, а не усыновляет, —
  спека это позволяет явно. `_digits_changed` (`flash_carrier.py:196-203`) не считает
  расхождением отсутствие поля, что верно: спека говорит про «differs», а не про «absent».
  Мутации 5 и 6 `bite-flash-call.sh`.
- **🔴 Отказ опознаётся наличием `error`, а не значением `status`.**
  `app/verification/ucaller.py:483-489`: `error = envelope.get("error"); if error: return
  True, …` — и числовой `code` читается **только** внутри этой ветви, где он число.
  Мутации 1–3 `bite-ucaller-adapter.sh`. Опровергающий проход: разбор требует
  `"status" in envelope` (`ucaller.py:479`) — проверил по слепку ошибки
  `captures/uc-1.3-initRepeat-405.json`: `{"status":false,"error":"Method Not
  Allowed","code":405}`, `status` в конверте ошибки есть, так что классификация не
  проваливается в `UNANSWERED`.
- **`ucaller_id` записывается у любого ответа, который его несёт, что бы ни сказал
  `status`.** `flash_carrier.py:134-139` пишет `vendor_ref` через `set_rung_outcome`
  **до** ожидания исхода. Мутация 7 `bite-flash-call.sh`.
- **Разбираются обе формы конверта.** `ucaller.parse_placed` (`ucaller.py:320-328`) читает
  `code` как строку и `status` как факт, а не как дискриминатор; `Placed.status`
  сохранён (`ucaller.py:181`).

Побочная проверка урока ветки («снятая ветвь ≠ изменённый исход»): `ucaller.classify`
(`ucaller.py:300-306`) отдаёт неизвестный код в `UNCLASSIFIED`, а не в `DECLINED` и не в
`REFUSED`; `flash_carrier._OUTCOME` (`flash_carrier.py:61-66`) переносит это в
`ladder.UNCLASSIFIED`, который продвигает лестницу **и** будит оператора
(`flash_carrier.py:72`, `_alert`). Отказ абонента, выпавший из `ABOUT_THE_SUBSCRIBER`,
становится `unclassified`, а не отказом НАМ — модемный рунг не удерживается
(`ladder.py:176`). Верно.

Аннотация:

- «live samples 22.09.2026, both outcomes, in `captures/uc-1.3-*.json`» — есть:
  `captures/uc-1.3-initCall-reachable.json` (`status:true`) и
  `captures/uc-1.3-initCall-unreachable.json` (`status:false`, `ucaller_id`, наш `code`
  строкой). Находки — `captures/ucaller-samples-1.3.md`. backed.
- «the vendor reference … captured in `captures/ucaller-reference-2026-09-22.md`» — файл
  на месте, раздел 7 несёт таблицу кодов ошибок, из которой набраны `ABOUT_US` и
  `ABOUT_THE_SUBSCRIBER` (`ucaller.py:133-152`). backed.
- «The parser is `app/verification/ucaller.py`, the rung is
  `app/verification/flash_carrier.py`» — оба на месте. backed.
- «guarded by `tests/test_ucaller_adapter.py`, `tests/test_flash_call_carrier.py` and
  `tests/test_the_call_rung_is_reachable.py`» — все три существуют и зелёные. backed.
- «14 and 18 mutations in `bite-ucaller-adapter.sh` and `bite-flash-call.sh`» — посчитал:
  14 и 18 (во втором нумерация идёт до 19 с пропуском 13, укусов ровно 18). backed.
- «**Still unbacked: the `-1` bound.** `call_status: -1` was not observed once» — сверено
  со слепками: `captures/uc-1.3-getInfo-reachable.json` несёт `call_status:1`,
  `captures/uc-1.3-getInfo-unreachable.json` — `call_status:0`. `-1` нет ни в одном.
  Самооговорка честная. backed как оговорка.
- «the ladder ships with ten seconds» — `app/settings_store.py:132`,
  `verification_ladder_bound` по умолчанию `10.0`. backed.
- «read by `flash_carrier.resolve_outstanding`, from the sweep that announces every other
  ending and **before the expiry in the same pass**» —
  `app/verification/dispatch.py:88` (подметание) стоит **до**
  `dispatch.py:95` (`expire_due_verifications`) и до цикла объявлений
  (`dispatch.py:101`). backed.
- «`tests/test_the_call_outcome_that_arrives_late.py`, 11 mutations in
  `bite-late-call-outcome.sh`» — файл есть, укусов ровно 11. backed.
- «Past the verification's own lifetime the rung stops being chased and keeps saying
  `unresolved`» — `flash_carrier.py:273-274` просит
  `unresolved_rungs(within_seconds=store.verification_ttl_seconds)`, а сам запрос
  (`queries.py:1450-1458`) фильтрует по `r.outcome = 'unresolved'` и по возрасту строки;
  более старая строка так и остаётся `unresolved`, истории ей не пишут. backed.

## Требование 359–447 — «Telegram's delivery report …» · **backed, кроме одного**

🔴 Аннотации у требования нет вовсе — проверял как заявленное целиком.

- **`delivery_status` записывается.** `tg_callback.py:146-148` →
  `queries.record_rung_delivery` (`queries.py:1273-1316`), матч по паре
  `(vendor_ref, route)`, а не по одной ссылке. backed.
- **`delivered` — свидетельство доставки, `read` — открытия, и ни то ни другое не
  подтверждение.** Дверь не имеет пути к подтверждению вовсе:
  `record_rung_delivery` трогает только `verification_rungs`, а единственный писатель
  `status='confirmed'` — `queries.check_verification` (`queries.py:1548-1561`). Сторожа:
  `tests/test_tg_callback.py:122`, `:357`, `:387`. backed.
- **`expired` проваливает верификацию с этой причиной.** `tg_callback.py:157-165`;
  на уже завершённой — не переоткрывает (`tg_callback.py:166-170`, сторож
  `test_tg_callback.py:289`). backed.
- **Возврат записывается из `is_refunded`, а не предполагается.**
  `tg_callback._refund_note` (`tg_callback.py:177-189`) различает три состояния вендора
  при двух состояниях колонки; `queries.py:1305-1314` утверждает только положительное, а
  слова вендора кладёт в `reason`. Сторожа: `test_tg_callback.py:150`, `:164`. backed.
- **Терминальная верификация просит отозвать сообщение.**
  `dispatch.py:104` зовёт `_withdraw_outstanding_message` внутри единственного прохода,
  видящего все окончания; `dispatch.py:133-147` отзывает по каждому рунгу `tg_gateway`,
  держащему `vendor_ref`. Все три окончания покрыты параметризованным сторожем
  `tests/test_tg_rung_aftermath.py:81-104` (`confirmed`, `expired`, `no_attempts_left`);
  «out of attempts» действительно терминальна — `queries.py:1574-1576` ставит
  `status='failed', reason='no_attempts_left'`. backed.
- **Ответ вендора не считается свидетельством, и гарантия на нём не стоит.**
  `tg_gateway.request_revocation` (`tg_gateway.py:311-338`) возвращает «запрос принят», и
  `dispatch.py:144` даже не смотрит на возврат; отказ вендора не задерживает объявление
  (`dispatch.py:145-147`, сторож `test_tg_rung_aftermath.py:136`). Гарантию держит
  терминальное состояние: `queries.py:1553` требует `status='pending'` для совпадения кода.
  backed.
- **🔴 «never record … a bare `expired`»** — **contradicted**, находка 1 выше.

Наблюдения без вердикта (не SHALL, но относятся к делу):
`verification_status` разбирается (`tg_gateway.py:202`) и не читается больше нигде — то
самое `verification_status: expired` платного слепка `captures/probe-1.7-status-after-
revoke.json` ни на что не влияет; это согласуется с «What does not change is the
requirement», но означает, что защита от путаницы двух полей сегодня держится на том, что
второе поле просто не используется. И `delivery_status: "sent"`, который вендор отдаёт
прямо в ответе на отправку (`captures/sendVerificationMessage.json`), `tg_carrier.py:146`
выбрасывает — первый отчёт о доставке не записывается, записывается только тот, что придёт
колбэком.

## Требование 509–554 — «A callback nobody is told about never arrives» · **backed, чисто**

- **Адрес уходит с каждым сообщением, купленным на `tg_gateway`.**
  `placement.carriers_for:107` собирает его и передаёт в `tg_carrier.carrier:119-121`,
  тот — в `send_verification_message` (`tg_carrier.py:135-138`), тот — в тело
  (`tg_gateway.build_send_body:246-247`). Сторож читает **то, что дошло до адаптера**, а
  не то, что вернул носитель (`tests/test_where_the_vendor_reports.py:65-86, 100-111`).
  backed.
- **Адрес — тот, который эта дверь обслуживает, и путь не написан дважды.**
  `tg_callback.PATH` (`tg_callback.py:49`) — единственное имя;
  `app/api/router.py:21,333` регистрирует дверь под ним же, `tg_callback.url_for:88-91`
  собирает адрес из базы и его. Сторож сверяет путь с **живой таблицей маршрутов**
  FastAPI, а не с исходником, и держит позитивный контроль
  (`test_where_the_vendor_reports.py:113-133`). backed.
- **Без публичного адреса — ни полуадреса, ни отказа: рунг покупает и шлёт, а потеря
  названа один раз там, где рунг собирается.** `placement.py:107-118` — предупреждение
  при пустой базе, `build_send_body:246` не кладёт пустой `callback_url` в тело. Сторож —
  `test_where_the_vendor_reports.py:156-173`, проверяет и то, что рунг всё-таки
  `CARRIED`, и то, что в теле ровно `""`. backed.
- Аннотация: «`tg_carrier.carrier` takes `callback_url` with **no default**» —
  `tg_carrier.py:60-62`, параметр без умолчания; сторож ловит это `pytest.raises(TypeError)`
  и держит позитивный контроль (`test_where_the_vendor_reports.py:175-190`). backed.
- Аннотация: «the address is assembled by `tg_callback.url_for` over `tg_callback.PATH`,
  which is the same name `app/api/router.py` registers the door under, and is supplied at
  `placement.carriers_for`» — все три места проверены поимённо выше. backed.
- Аннотация: «Guarded by `tests/test_where_the_vendor_reports.py`, which reads back what
  reaches the adapter … and checks the path against the live route table» — обе
  особенности в файле есть буквально. backed.
- Аннотация про вендорскую сторону («no callback has ever arrived») — утверждение о
  наблюдении, а не о коде; ни одного слепка колбэка в `captures/` действительно нет, что
  с оговоркой согласуется. backed как оговорка.

## Требование 555–638 — «The vendor's per-number limits …» · **backed, кроме одного**

- **Лимиты исполняются здесь и отказывают с причиной.** `limits.claim`
  (`app/verification/limits.py:50-70`) → `queries.claim_paid_rung`
  (`queries.py:1098-1145`), три клаузы одним оператором; причина составляется после факта
  (`limits._why:73-106`). Дверь отвечает отказом, а не 200 (`app/api/router.py:309-318`).
  backed.
- **Лимиты настраиваемые.** `app/settings_store.py:238` (`verification_min_gap_seconds`,
  15), `:240` (`verification_per_minute`, 4), `:242` (`verification_per_day`, 30),
  `:248` (`verification_day_window_hours`, 24); читаются в `limits.py:62-67`, а не зашиты
  в запрос. Сторож — `test_per_number_limits.py:193`, мутация 6 `bite-limits.sh`. backed.
- **Суточный потолок называет окно, которым считает.** `limits.py:98-102` возвращает
  «per_day_ceiling: N paid attempts on this number in the last {window_hours}h». backed.
- **Окно скользит назад от «сейчас», а не считает календарный день.**
  `queries.py:1089`: `r.started_at > datetime('now', ? || ' seconds')` с отрицательным
  сдвигом (`queries.py:1095`). Сторож — `test_per_number_limits.py:169`, мутация 5
  `bite-limits.sh`. Оговорка аннотации про 20:00 UTC верна и исполнена: скрипт печатает
  текущий час UTC (`bite-limits.sh:32`) с отсылкой к примечанию (`:73-80`). backed.
- **Лимиты ограничивают лестницу целиком, а не рунг `flash_call`.**
  `app/verification/routes.py:72`: `PAID_ROUTES = {FLASH_CALL, TG_GATEWAY}`;
  `queries.py:11-12` разворачивает их в плейсхолдеры, `queries.py:1088` — `r.route IN (…)`.
  Сторож — `test_per_number_limits.py:136`, мутации 1 `bite-limits.sh` и 7
  `bite-window-from-the-door.sh`. backed.
- **🔴 «counted over the rung attempts … rather than over verifications»** —
  **contradicted**, находка 2 выше.
- Аннотация: «`limits.claim` is the single conditional statement `ladder.walk` writes a
  paid rung with» — `ladder.py:203-213`: платный маршрут идёт через `limits.claim`,
  непла́тный — через `record_verification_rung`. Второго писателя платной строки нет:
  единственный внешний вызов `record_verification_rung` в двери
  (`app/api/router.py:262`) закрыт условием `if not placement.places_here(body.route)`
  (`router.py:261`), а `PLACED_HERE` (`placement.py:64`) содержит оба платных маршрута.
  backed.
- Аннотация: «`tests/test_per_number_limits.py` — eleven tests with four positive
  controls» — ровно 11 тестов; позитивных контролей четыре (`:102` после паузы, `:111`
  пустая история, `:150` три попытки не добирают минутный потолок, `:182` чужой номер).
  backed.
- Аннотация: «`bite-limits.sh` turns its seven red» — укусов ровно 7, перечень совпадает с
  аннотацией пункт в пункт (окно по одному рунгу, пауза, каждый из потолков, календарный
  день, зашитые числа, номер выброшен из выборки). backed.
- Аннотация: «`tests/test_the_call_rung_is_reachable.py` now drives real HTTP … and counts
  `ucaller.init_call` itself» — файл подменяет именно `ucaller.init_call`
  (`tests/test_the_call_rung_is_reachable.py:116,133`) и считает его вызовы; то же сказано
  в его собственном комментарии (`:273`). backed.
- Аннотация: «`bite-window-from-the-door.sh` turns **eleven mutations** red» — укусов ровно
  11, перечень совпадает с аннотацией пункт в пункт. backed.
- Аннотация: «🔴 That script [`bite-limits.sh`] was written on 22.09.2026 and the note here
  named it long before it existed» — файл существует и сам несёт этот урок в шапке
  (`bite-limits.sh:6-14`). backed.
- Аннотация: «The **numbers** remain the vendors' reference rather than a measurement» —
  в `captures/` нет ни одного слепка, где вендор что-либо ограничивал; оговорка честная.
  backed как оговорка.

---

## Чего я НЕ нашёл (отрицательные результаты, записаны намеренно)

- **Порядок проверок колбэка.** Урок ветки целил сюда, но само требование о подписи
  (спека 448–508) не в моём списке. Ради урока всё же посмотрел:
  `tg_gateway.callback_refusal` (`tg_gateway.py:435-447`) сначала отбрасывает пустой токен
  и пустую подпись, затем нечитаемую метку, затем окно, и только потом считает HMAC.
  Окно проверяется раньше подписи **осознанно** (`tg_gateway.py:430-433`) и состояния не
  двигает: `handle_callback` не читает тело, пока `callback_refusal` не вернул пустую
  строку (`tg_callback.py:120-133`). Инструмента «дотянуться до публичной двери» это не
  даёт — из двери наружу утекает только различение `stale`/`signature`, которое и есть цель
  задачи 4.66. Не находка.
- **Обе кромки временнóго окна.** `abs(now - sent_at) > tolerance` (`tg_gateway.py:441`) —
  дальняя кромка на месте, метка произвольно далеко в БУДУЩЕМ отвергается; сторож
  `tests/test_tg_callback.py:220`. Не находка.
- **Отзыв по маршруту.** `_withdraw_outstanding_message` выходит сразу при
  `row["route"] != TG_GATEWAY` (`dispatch.py:133`). Искал дыру: рунг `tg_gateway` с
  `vendor_ref`, пока верификация числится за другим маршрутом. Не нашёл — `route`
  перенаправляется только на `CARRIED` (`ladder.py:232`), а `tg_gateway`, получивший
  `request_id`, дальше уходит либо в `CARRIED`, либо в `FAILED`, и `FAILED` лестницу
  останавливает (`ladder.py:252-259`). Отказ абонента и неотвеченная проба `request_id` не
  дают вовсе. Дыра закрыта, хотя и косвенно — через колонку `route`, а не через наличие
  `vendor_ref`. Не находка, но место хрупкое.
