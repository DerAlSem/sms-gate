ИТОГ: backed 51 · contradicted 3 · unbacked 0 — механика лестницы и денег держится, а падают три УТВЕРЖДЕНИЯ О КОДЕ: одна норма, которую носитель нарушает в одной ветке, и две аннотационные оговорки «это ещё никем не вызывается», устаревшие с появлением `placement.place`.

## Находки `contradicted`

### 1. «Подтверждённая проверка SHALL сопровождаться ровно одним `sendVerificationMessage` … SHALL NOT be abandoned» — нарушено

**Где:** `openspec/changes/route-sends-by-operator/specs/outbound-routing/spec.md:461-463`
против `app/verification/tg_carrier.py:123-133`.

**Сценарий отказа:** `check_send_ability` вернул `ABLE` (плата 0.01 уже понесена,
`request_id` получен, `balance.observe` и `set_rung_outcome` записали её — строки 111-121).
Дальше носитель перечитывает верификацию: `queries.get_verification` → `row["code"]`.
Если между проверкой и этой строкой верификация подтвердилась, истекла или была отменена
(стор обнуляет `code` в момент, когда верификация перестаёт быть подтверждаемой), носитель
возвращает `FAILED` и **не отправляет ничего**. `request_id` не использован ни разу.

**Чем это проявится:** плата остаётся невозвратной навсегда — возврат вендора привязан к
недоставке внутри `ttl`, а `ttl` начинается только с отправкой сообщения (это ровно тот
довод, которым сама норма и обоснована, строки 457-460). Деньги при этом УЧТЕНЫ
(`cost` записан на строку рунга), так что бухгалтерия не врёт; нарушена именно норма
«ровно одна отправка за подтверждение».

**Честно о характере находки:** ветка не случайна — она написана и прокомментирована
намеренно («the fee is spent and stays recorded; nothing is sent, because the code that
would have travelled no longer exists»), и отправлять код мёртвой верификации было бы хуже.
Но ни в `outbound-routing`, ни в `phone-verification` этого исключения нет ни в одном SHALL
(проверено грепом по `specs/`): норма написана как абсолютная. Разошлись спека и код, и
чинить надо одно из двух — либо оговорку в норме, либо ветку.

### 2. Аннотация требования 2: «⚠️ Implemented is not reachable: the gate has no production caller» — неверно

**Где:** `specs/outbound-routing/spec.md:607` против цепочки
`app/api/router.py:304` (`POST /verifications/{id}/route` → `_walk_the_ladder` →
`placement.place`) → `app/verification/placement.py:168`
(`gates=gates.for_paid_ladder(app_id, phone, rungs)`) → `app/verification/gates.py:188`
(`entitlement_gate(app_id)`).

**Чем это проявится:** гейт входа НЕ ждёт `verify-by-inbound-contact` — он уже стоит на
живом пути. Читатель, доверившийся оговорке, решит, что `may_spend` пока ни на что не
влияет, и (а) не станет заводить право ни одному приложению перед выкатом — а `may_spend`
отгружается нулём, значит ПЕРВАЯ ЖЕ платная верификация в проде будет отказана; (б) не
включит этот путь в дымовой тест выката. Оговорка устарела вместе с 4.56c/4.61.

### 3. Аннотация требования 3: «⚠️ Counted is not produced: the only caller today is `ladder.walk`, which has no production caller of its own» — неверно обеими половинами

**Где:** `specs/outbound-routing/spec.md:728-815` (блок аннотации о `refusals.py`) против:
- `ladder.walk` имеет продакшн-вызывателя — `app/api/router.py:304` через
  `app/verification/placement.py:162`;
- `refusals.record` имеет ВТОРОГО вызывателя, не `ladder.walk`, — `app/modem/manager.py:751`
  (отказ на пути отправки; он же описан там в комментарии как «это и есть те самые
  семьдесят в месяц»).

**Чем это проявится:** счётчик `/admin/stats` объявлен пустым макетом, тогда как он уже
наполняется двумя путями. Оператор, прочитавший оговорку, спишет непустой отчёт на
тестовые данные; обратно — отчёт об отзыве правила (`review_step`) уже способен назвать
реальную цену, а аннотация говорит, что называть ему нечего.

---

## Требование 1 — «A paid ladder tries its rungs in order…» (строки 405-566)

**Исход: 24 backed · 1 contradicted · 0 unbacked.**

Нормы:

1. `backed` — порядок рунгов — рула, не кода. `app/verification/ladder.py:169` (`for route
   in rungs`), список приходит параметром; `app/verification/placement.py:161` читает его
   `rule.route_for` на каждый вызов. Опровергающий проход: сортировки/перестановки в
   модуле нет; укус 3 `bite-ladder.sh` («телеграм первым, потому что так написано в коде»)
   существует и его якорь резолвится.
2. `backed` — каждый рунг не более одного раза. Единственный проход по `rungs`
   (`ladder.py:169`); дубликаты запрещены на разборе правила — `app/verification/rule.py:111`
   (`len(set(routes)) != len(routes)` → `UnreadableRule`).
3. `backed` — продвижение ТОЛЬКО на отказ нести. `ladder.py:77` (`_ADVANCING`), 225-239
   (`CARRIED` → выход), 241-250 (`UNRESOLVED` → выход), 252-259 (всё прочее → провал).
4. `backed` — «понёс и упал» останавливает лестницу и называет рунг.
   `ladder.py:252-259`: `reason = f"{route} accepted this verification and then failed"`,
   затем `fail_verification`. `FAILED` намеренно вне `_ADVANCING` (`ladder.py:69,77`).
5. `backed` — «не может нести ИМЕННО ЭТО» записывается отдельно и не считается отказом
   абонента. `app/verification/tg_carrier.py:91-98` (`ttl < TTL_MIN` → `INCAPABLE`),
   `ladder.py:67` (константа), `ladder.py:221` (пишется в строку рунга).
6. `backed` — строка рунга пишется ДО вендора и завершается после.
   `ladder.py:203-216` (`limits.claim` / `record_verification_rung` c `outcome=ATTEMPTING`)
   → `ladder.py:218` (`_attempt`, единственное место, где зовётся носитель) →
   `ladder.py:221-223` (`set_rung_outcome`). `app/db/queries.py:1227-1256` дописывает
   `cost`/`vendor_ref` через `COALESCE`, то есть уже записанная плата не стирается исходом.
7. `backed` — маршрут, который нечем нести: не пробуется, громко, лестница идёт дальше.
   `ladder.py:281-291` (`carriers.get(route) is None` → `notify("routing", …)` → `ABSENT`),
   `ABSENT` ∈ `_ADVANCING` (`ladder.py:77`). Громко на штатных настройках:
   `app/alerting.py:392` (категория `routing`) + `app/settings_store.py:79`
   (`notify_routing_errors` по умолчанию `True`).
   ⚠️ **Примечание, не находка.** Для ПЛАТНОГО маршрута строка рунга и расход лимита
   номера уже взяты `limits.claim` (`ladder.py:208`) до того, как выяснится, что носителя
   нет. Строка с исходом `absent` попадает в `paid_attempts_for_number` и
   `paid_attempts_since` (`queries.py:1085-1090`, `1175-1202`), то есть пустой токен
   Telegram съедает пятнадцатисекундный зазор номера и место под потолком. Букву нормы
   («не пробуется, алерт, продвижение») это не нарушает — вендора никто не трогал, и в
   `paid_attempts_since` такой учёт объявлен намеренным, — но норма о расходе разрешённой доли номера
   этот случай не разбирает вовсе.
8. `backed` — на `tg_gateway` отказ — это недостижимый абонент либо неответ в границе.
   `app/verification/tg_gateway.py:111` (`DECLINE_ERRORS = {"PHONE_NUMBER_NOT_AVAILABLE"}`),
   `tg_carrier.py:47-52` (`_OUTCOME`), `ladder.py:77`.
9. `backed` — лестница кончается тем, что несёт или валит. `ladder.py:261-267`:
   всё продвинулось → `_why_nothing_carried` + `fail_verification`; исключение — молчание
   последнего рунга (`_IN_FLIGHT`, `ladder.py:98`), что и есть норма о «в полёте».
10. `backed` — КАЖДЫЙ гейт до первого контакта с рунгом. `ladder.py:156-164` — цикл гейтов
    строго до цикла рунгов (166-169) и до ветви удержания модема (176).
    Поимённо: чёрный список — `gates.py:51-77`, всегда, при любых рунгах (`gates.py:186-187`);
    нормализация номера — `app/api/schemas.py:61-64` (валидатор Pydantic, то есть до
    создания верификации вообще); право приложения и потолок — `gates.py:188`;
    ЛИМИТЫ НОМЕРА — вне списка гейтов, но исполняются в `ladder.py:208` (`limits.claim`)
    до `_attempt` на строке 218, то есть норма «до первого контакта» соблюдена.
11. `contradicted` — «подтверждённая проверка → ровно одна отправка, не брошена».
    `tg_carrier.py:123-133`. См. находку 1.
12. `backed` — «не повторяется с тем же `request_id`». `tg_carrier.py:135-138` —
    единственный вызов `send_verification_message` в модуле, ретрая вокруг него нет.
13. `backed` — неответившая проверка = «возможно оплачена», считается отдельно от обоих
    исходов. `ladder.py:65` (`UNANSWERED`), `tg_carrier.py:51`, `ladder.py:298`
    (исключение носителя — тоже `UNANSWERED`, не отказ абонента), пишется в строку рунга
    `queries.py:1227`. Опровергающий проход: значение НЕ совпадает с `declined`, и укус 4
    `bite-ladder.sh` бьёт ровно по этому.
14. `backed` — `PHONE_NUMBER_NOT_AVAILABLE` читается как отказ АБОНЕНТА.
    `tg_gateway.py:111`, `tg_carrier.py:48`. Живой образец —
    `captures/probe-1.7-check-declined.json` (`{"ok":false,"error":"PHONE_NUMBER_NOT_AVAILABLE"}`).
15. `backed` — неразмещаемый `ok:false` → продвижение И алерт. `tg_gateway.py:92`
    (`UNCLASSIFIED`), `tg_carrier.py:50` (в `_OUTCOME`), `tg_carrier.py:57` (`_LOUD`),
    `tg_carrier.py:159-162` (текст алерта), `ladder.py:77` (в `_ADVANCING`).
16. `backed` — `ACCESS_TOKEN_INVALID` → отказ НАМ, не отказ рунга, алерт.
    `tg_gateway.py:110` (`FATAL_ERRORS`), `tg_carrier.py:49,57,155-158`. Опровергающий
    проход: различение живёт в карте `_OUTCOME`, а не в значении константы, — то есть
    мутация там не вырождается в тождество (это и есть переприцеливание, о котором
    аннотация говорит на строках 519-525).
17. `backed` — принял и не доставил в `ttl`: валит с этой причиной, без эскалации, возврат
    отражается в записанной стоимости. `app/verification/tg_callback.py:145-164`
    (`record_rung_delivery`, затем `delivery_status == "expired"` → `fail_verification`;
    вызова лестницы отсюда нет), `queries.py:1309-1315`
    (`cost = CASE WHEN ? THEN 0 ELSE cost END`).

Аннотация (строки 505-525):

18. `backed` — `captures/probe-1.7-check-declined.json` существует и содержит именно
    отказ, без стоимости.
19. `backed` — `captures/probe-1.7-check-able.json`: `request_cost:0.01`,
    `remaining_balance:99.99` — дословно.
20. `backed` — `captures/probe-1.7-send.json` несёт ТОТ ЖЕ `request_id`
    (`222370177540343` в обоих файлах).
21. `backed` — `tests/test_tg_gateway_adapter.py` существует.
22. `backed` — драйвер (`ladder.py` + `tg_carrier.py`) сторожится
    `tests/test_ladder_walk.py` и `tests/test_tg_gateway_carrier.py`; прогон 22.09.2026 —
    зелёный (в общей пачке 75 passed).
23. `backed` — `bite-ladder.sh` — ДЕВЯТЬ мутаций, `bite-carrier.sh` — ВОСЕМЬ, и оба
    гоняют ОБА файла (`bite-ladder.sh:19` и `bite-carrier.sh:18` —
    `TESTS="tests/test_ladder_walk.py tests/test_tg_gateway_carrier.py"`).
    Опровергающий проход на «сторож, который не запускается»: все 17 якорей проверены
    машинно на текущем исходнике — каждый находится РОВНО один раз, ни один не осиротел.
24. `backed` — `is_refunded` не встречается ни в одном из 24 файлов `captures/`.
25. `backed` — различающее место — карта `_OUTCOME` носителя, и мутация 6 `bite-carrier.sh`
    прицелена именно на строку `tg_gateway.REFUSED: ladder.REFUSED,`.

## Требование 2 — «Spending … is an entitlement of the application, off by default» (строки 567-628)

**Исход: 11 backed · 1 contradicted · 0 unbacked.**

1. `backed` — право записано против приложения; отсутствующее или выключенное отказывает с
   причиной, называющей право. `app/db/migrate.py:515` (`apps.may_spend`),
   `app/verification/gates.py:80-99` — все три возврата начинаются со слова `entitlement:`
   и называют `app_id`. Сторож: `tests/test_paid_entitlement.py:70`
   (`test_every_way_of_refusing_names_the_entitlement_and_the_application`).
2. `backed` — по умолчанию выключено, включая свежий токен.
   `migrate.py:515` — `INTEGER NOT NULL DEFAULT 0`; `tests/test_paid_entitlement.py:49`.
3. `backed` — умолчание достаёт и существующие приложения. Это `ALTER` через
   `_add_column_if_missing`, а не `DEFAULT` на новых строках: SQLite проставляет `0` всем
   уже лежащим. Сторож строит таблицу в дореформенной форме и мигрирует —
   `tests/test_paid_entitlement.py:132`, и парный `:167` о том, что уже выданное право
   миграция не сносит.
4. `backed` — откат выкатом прежнего кода, а не снятием колонки. Грепом по `app/db/`
   нет ни одного `DROP COLUMN`.
5. `backed` — активность остаётся более сильным переключателем. `gates.py:89-94` —
   проверка `is_active` СТОИТ ПЕРЕД `may_spend`. Опровергающий проход: ветка достижима и
   сторожится — `tests/test_paid_entitlement.py:105`.
6. `backed` — отказ не трогает вендора, не выдаётся за отказ вендора и не сползает на
   `sms_out`. `ladder.py:156-164` возвращает `Walk(refused_by=…)` ДО цикла рунгов, то есть
   ни `carriers_for`, ни `_attempt` не достигаются; `app/api/router.py:309-318` отвечает
   422 `"refused"`, а не 200 и не ошибкой вендора. Сторожа:
   `tests/test_paid_entitlement.py:180` и `:204`.
7. `backed` — право не часть правила маршрутизации и меняется без рестарта.
   `app/verification/rule.py` не знает о `may_spend` (грепом); `gates.py:83` читает
   `queries.get_app` на каждый вызов гейта — сторож `tests/test_paid_entitlement.py:119`.
8. `backed` — аннотация: `apps.may_spend` добавлено `migrate.py` как `ALTER`. `migrate.py:515`.
9. `backed` — аннотация: гейт — `gates.entitlement_gate` в `app/verification/gates.py`,
   читается на вызов. `gates.py:80-101`.
10. `backed` — аннотация: управляется на `POST /admin/apps/entitlement`.
    `app/admin/router.py:495-498`, форма — `app/admin/templates/apps.html:42-45`.
11. `backed` — аннотация: сторожится `tests/test_paid_entitlement.py` и
    `tests/test_admin_apps.py`, включая тест на дореформенную форму таблицы —
    `tests/test_paid_entitlement.py:132`. Оба файла зелены.
12. `contradicted` — аннотация «⚠️ Implemented is not reachable: the gate has no production
    caller». См. находку 2.

## Требование 3 — «What the rule costs is countable per operator» (строки 728-815)

**Исход: 16 backed · 1 contradicted · 0 unbacked.**

1. `backed` — счёт ведётся на оператора и виден без базы.
   `app/verification/refusals.py:49-65` (`INSERT INTO route_refusals`),
   `refusals.py:77-117` (`counts`, группировка на `operator_key`),
   `app/admin/router.py:416-423` и `app/admin/templates/stats.html:69`.
2. `backed` — счёт отвечает и на приложение. `refusals.py:113` (`by_app`), там же
   `by_route`; отдаётся в шаблон тем же вызовом.
3. `backed` — счёт не служит доказательством выздоровления, и вместо него есть второй
   инструмент: алерт о просроченном отзыве. `refusals.py:190-242` (`_report_stale`),
   текст алерта прямо говорит «nothing here can tell you so».
4. `backed` — `*` и `?` вне отчёта. `refusals.py:209` (`WHERE operator_key NOT IN (?, ?)`)
   с `rule.DEFAULT`/`rule.UNKNOWN` (`rule.py:50-51`). Опровергающий проход: это настоящий
   фильтр в SQL, а не комментарий, и укус 13 `bite-refusals.sh` целится ровно в эту строку.
5. `backed` — смена маршрутов записи перезапускает период. `refusals.py:176-182`
   (`in_force_since = CURRENT_TIMESTAMP, reviewed_at = NULL` при `stored[key] != as_stored`).
6. `backed` — выбывшая запись перестаёт отчитываться. `refusals.py:183-186` (`DELETE`).
7. `backed` — алерт приходит на штатной конфигурации и не висит на `notify_send_errors`.
   `refusals.py:70` — категория `routing`; `app/alerting.py:392` мапит её на
   `notify_routing_errors`; `app/settings_store.py:79` — умолчание `True`.
   Сторож честный: `tests/test_route_refusals.py:43-57` подменяет `_notifier`, а не сам
   `notify`, и `:135`/`:147` проверяют обе стороны тумблера.
8. `backed` — дедуп на операторе И маршруте, не на сообщении. `refusals.py:74`
   (`dedup_extra=f"refused:{key}:{route}"`). Укусы 7 и 8 `bite-refusals.sh` снимают маршрут
   и оператора по отдельности.
9. `backed` — отчёт раз в период, а не раз в тик. `refusals.py:211-212` (условие по
   `reviewed_at`) + `refusals.py:239-241` (проставление `reviewed_at` после алерта).
10. `backed` — алерт называет, во что запись обошлась с момента вступления в силу.
    `refusals.py:223-231` (`counts(since=entry["in_force_since"])` → `by_app`).
11. `backed` — аннотация: свёртка имени оператора в Python, никогда в SQL.
    `refusals.py:57` (`rule.fold(name)`), в SQL — только сравнение готового `operator_key`
    (`refusals.py:98`, `209`); ни `upper()`, ни `LIKE` по имени нет.
12. `backed` — аннотация: достижимо на `/admin/stats` рядом со счётчиками сообщений и под
    тем же контролем периода. `app/admin/router.py:404-423` — один `period =
    periods.resolve(period)` на весь обработчик, он же уходит в `counts(period=period)`.
13. `backed` — аннотация: `review_step` часовым неэссенциальным циклом `routing-review` из
    `main.py`. `app/main.py:88` — `("routing-review", route_refusals.review_loop(), False)`;
    `refusals.py:286-291` — `asyncio.sleep(3600)`.
14. `backed` — аннотация: ограничено настройкой `operator_route_review_days` (30).
    `app/settings_store.py:337`; читается на каждый проход — `refusals.py:202`.
15. `backed` — аннотация: сторожится `tests/test_route_refusals.py`, гоняющим настоящий
    `notify` поверх поддельного нотификатора. `tests/test_route_refusals.py:43-57`, файл
    зелёный.
16. `backed` — аннотация: `bite-refusals.sh` на ТРИНАДЦАТЬ мутаций. Ровно 13, все якоря
    резолвятся однозначно на текущем `refusals.py`.
17. `contradicted` — аннотация «⚠️ Counted is not produced…». См. находку 3.

---

## Что проверялось и оказалось в порядке (опровергающий проход, отдельно)

Два утверждения ветки, названные необкатанными, проверены прицельно и держатся:

**(а) `gates.for_paid_ladder` трёхаргументная, лимит номера ушёл на границу записи рунга.**
`app/verification/gates.py:153` — `for_paid_ladder(app_id, phone, rungs)`, умолчания у
`rungs` нет; `gates.py:186-188` — на свободной ходке остаётся ОДИН гейт (чёрный список),
денежные два не задаются. Остатка `limits.per_number_gate` в дереве нет (грепом по `app/`,
`tests/` и укусам — пусто), то есть двойного исполнения лимита не осталось.
`app/db/queries.py:1130-1145` — это действительно ОДИН условный
`INSERT INTO verification_rungs … SELECT ?,?,? WHERE (…)=0 AND (…)<? AND (…)<?`, три клаузы
на три лимита (зазор, минута, окно), номера лимитов приходят параметрами из
`limits.py:62-67`. Порядок параметров сверен с порядком подстановок `_PAID_FOR_NUMBER`
(`queries.py:1085-1095`) — совпадает. Успех определяется по `rowcount == 1`, то есть
протухший `lastrowid` не может выдать себя за запись.
Сторожа зелены: `tests/test_the_numbers_limits_are_taken_in_one_act.py` (4 passed),
`tests/test_a_free_walk_is_not_asked_about_money.py`.

**(б) Счёт исключает собственную строку.** `queries.py:1088` — `r.verification_id <> ?`, и
параметр — именно `verification_id` текущей ходки (`_for_number`, `queries.py:1093-1095`).
Опровергающий проход на «условие, сравнивающее значение с самим собой»: сравнение идёт не
со своей же строкой, а со строками ДРУГИХ верификаций того же номера; без исключения второй
платный рунг одной лестницы не заклеймился бы никогда (строке первого ноль секунд от роду
при зазоре в пятнадцать). Ровно это сторожит
`tests/test_the_numbers_limits_are_taken_in_one_act.py:149`
(`test_a_ladder_advances_from_one_paid_rung_to_the_next`), а
`:87` — обратную половину (две верификации на один номер доходят до вендора однажды).
В `paid_attempts_for_number` (`queries.py:1169`) исключение записано как
`excluding_verification or -1` — при `id` от единицы подмены не даёт.

**Прогнанные точечно и зелёные:** `tests/test_ladder_walk.py`,
`tests/test_tg_gateway_carrier.py`, `tests/test_a_free_walk_is_not_asked_about_money.py`,
`tests/test_paid_entitlement.py`, `tests/test_route_refusals.py`,
`tests/test_the_door_that_walks_the_ladder.py` — 75 passed;
`tests/test_the_numbers_limits_are_taken_in_one_act.py` — 4 passed.
Весь набор не гонялся. Ни код, ни спека, ни тесты не правились.
