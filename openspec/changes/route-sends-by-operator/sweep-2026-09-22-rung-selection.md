# Свип «код против спеки»: выбор рунга и его лестница, 22.09.2026

ИТОГ: backed 34 · contradicted 2 · unbacked 0 — нечитаемое правило маршрутизации оставляет ровно тот дефект, который требование запрещает первой же фразой: рунг предложен, выбран, записан и не размещён.

Проверены два требования файла `openspec/changes/route-sends-by-operator/specs/phone-verification/spec.md`:
строки 1215–1365 («Selecting a rung the gateway places walks the ladder inside that selection»)
и 1498–1560 («A verification carried by the modem takes that message's outcome»).
Каждый SHALL и каждое поимённое утверждение аннотаций — отдельным пунктом.

Прогон сторожей: `test_the_numbers_limits_are_taken_in_one_act.py`,
`test_the_bound_is_a_deadline_not_a_duration.py`, `test_the_door_that_walks_the_ladder.py`,
`test_a_verification_owns_its_message.py`, `test_ladder_walk.py` — **45 passed**.

---

## Находки `contradicted`

### 1. Нечитаемое правило: рунг предложен, выбран, записан — и не размещён (500)

**Норма.** Строка 1217: «A route SHALL NOT be offered, selected, recorded, and then left
unplaced»; строка 1219: «the ladder SHALL be walked before the selection is answered, and
the answer SHALL state what became of it».

**Код.** `app/verification/placement.py:150` — `ladder_from` зовёт `rule.route_for(operator)`
**без обработки** `rule.UnreadableRule`. Это третий читатель правила в кодовой базе, и
единственный, который её не ловит: `app/modem/manager.py:695-703` ловит и отказывает
громко, `app/verification/probes.py:157-162` ловит и отвечает `Proof(holds=False)`.
Исключение уходит из обработчика FastAPI наружу, а маршрут к этому моменту **уже заявлен**
(`app/api/router.py:241`, `queries.select_route`).

**Сценарий отказа (воспроизведён, не выведен).** Настройка `operator_routes` содержит
нечитаемое значение — путь штатный: `app/settings_store.py:659-676`, `seed_from_env`
вставляет `OPERATOR_ROUTES` из окружения **без какой-либо валидации** (валидация есть
только в `set_many`, строка 631). Проба `sms_out` при этом отказывает сама, а проба
`tg_gateway` правило не читает — поэтому рунг Telegram **предлагается**. Далее:

```
POST /verifications            → 200, offered: ['call_in', 'tg_gateway']
POST /verifications/1/route    → 500 Internal Server Error
verification: {'status': 'pending', 'route': 'tg_gateway', 'reason': None}
rungs: []
```

Верификация остаётся открытой с заявленным маршрутом и ничем не размещённым, и через ttl
истечёт с пустой причиной — дословно дефект 4.56, «одной дверью глубже», который для отказа
гейта уже закрыт (`placement.place`, хвост) и сторожится
`test_an_application_with_no_entitlement_is_refused_and_the_verification_does_not_hang`.
Для этой ветви сторожа нет.

Заметить стоит и то, что `walk` сам ловит отказ правила через `rule.refuses` (`ladder.py:149`)
— то есть ветвь «правило ничего не предлагает» обработана, а ветвь «правило не читается»
пропущена ровно на один уровень выше, в `ladder_from`.

### 2. Аннотация: «The second rung is `flash_call` and nothing carries it»

**Утверждение** (аннотация требования 1, последний `[backed]`-блок):
«🔴 **The second rung is `flash_call` and nothing carries it** (task 4.17, blocked on 1.1),
so today a declined subscriber ends in the loud-skip path rather than in a call».

**Код говорит обратное.** `app/verification/placement.py:120-125`:

```python
bearer = ucaller.configured_bearer()
if bearer:
    carriers[FLASH_CALL] = flash_carrier.carrier(verification_id, app_id=app_id, bearer=bearer)
```

Носитель существует целиком: `app/verification/flash_carrier.py` (330 строк, дедлайн, запись
`ucaller_id` до ожидания исхода, `resolve_outstanding`), адаптер `app/verification/ucaller.py`
(489 строк, написан по образцам `captures/uc-1.3-*.json`), проба
`app/verification/probes.py:78` (`_flash_call_probe`). Задачи `4.17` и `1.1` в
`tasks.md:555` и `tasks.md:8` отмечены `[x]`. Собственный докстринг `carriers_for`
(`placement.py:105-109`) прямо опровергает аннотацию: «`flash_call` was absent here until
22.09.2026 … and is now present on exactly the same terms as the Telegram rung».

**Как проявится.** Читатель дельты считает вторую ступень платной лестницы инертной. На
любой установке, где держится ключ uCaller, абонент, которого Gateway отклонил, получает
**платный звонок**, а не громкий пропуск. Это утверждение про деньги, и оно устарело в
дорогую сторону. Сторож `test_a_declined_subscriber_with_no_second_carrier_fails_loudly…`
(door-тест, строка 243) описывает только установку без ключа и это расхождение не ловит.

---

## Требование 1 — «Selecting a rung the gateway places walks the ladder inside that selection»
Строки 1215–1365. Исход: **20 backed · 2 contradicted** (SHALL'ы + утверждения аннотаций).

### SHALL'ы

| # | норма | исход | доказательство | что проверено |
|---|---|---|---|---|
| 1 | route не бывает offered/selected/recorded и не placed (1217) | **contradicted** | `app/verification/placement.py:150` | см. находку 1: нечитаемое правило → 500 при заявленном маршруте |
| 2 | лестница пройдена до ответа на выбор (1219) | backed | `app/api/router.py:270-273`, `placement.py:161-181` | дверь зовёт `placement.place` внутри обработчика; `test_selecting_the_telegram_rung_actually_sends_the_code` |
| 3 | ответ говорит, что с рунгом стало (1219) | backed | `app/api/router.py:318-329` | `route`/`status`/`reason` перечитаны ИЗ ХРАНИЛИЩА, не из `Walk` |
| 4 | пройденная лестница — ответ правила для оператора, от выбранного рунга (1222) | backed | `placement.py:146-158` (`ladder_from`), `rule.route_for` читается на вызов | срез `named[named.index(route):]` |
| 5 | рунги впереди выбранного не пробуются (1223) | backed | `placement.py:150`; `test_the_door_that_walks_the_ladder.py:423` | правило `[flash_call, tg_gateway]`, выбран `tg_gateway` → записан ровно один рунг |
| 6 | рунг, не названный правилом, несётся в одиночку (1229) | backed | `placement.py:152-157`; тест:396 | `МТС` → правило шлёт на модем, выбран Telegram → `[(tg_gateway, carried)]`, алертов нет |
| 7 | маршрут заявлен до любой траты (1235) | backed | `app/api/router.py:241` перед 270; `queries.select_route` (`queries.py:970-976`, условный UPDATE по `route IS NULL`) | две одновременные заявки: вторая получает `already_selected` |
| 8 | рунг, который понёс, заменяет заявку (1235) | backed | `ladder.py:232`, `queries.set_carrying_route` (`queries.py:1006-1011`) | UPDATE без условия `route IS NULL` — иначе заявка побеждала бы; тест:200 |
| 9 | закрытую верификацию не двигают вовсе (1241) | backed | `queries.py:1008-1009` (`status='pending' AND expires_at > CURRENT_TIMESTAMP`) | тест:447 с положительным контролем «пока открыта — двигается» |
| 10 | это докладывается, а не записывается как доставка (1242) | backed | `ladder.py:233-238` | `outcome != "carried"` → `logger.warning`, верификация не перенаправляется |
| 11 | отказ гейта завершает верификацию с этой причиной (1244) | backed | `placement.py:174-181` | `fail_verification(reason=…)`; тест:536 — `status == failed`, причина содержит `entitlement` |
| 12 | и отвечается как отказ (1244) | backed | `app/api/router.py:311-318` | 422 `{"error": "refused", "reason": …}`, не 200 |
| 13 | рунг при отказе гейта не записывается (1245) | backed | `ladder.py:156-164` — `return` до любой записи | тест:559 `_rungs(...) == []` |
| 14 | это не отказ вендора и так не докладывается (1249) | backed | там же + `refusals.record` не зовётся для гейтов | причина — имя гейта, не вендора |
| 15 | собственная бухгалтерия шлюза не считается тратой у вендора (1251) | backed | `app/api/router.py:253-255` — `if not placement.places_here(body.route)` | тест:503 меряет обе счётные функции: `overall == 1`, `per_number == 1` |
| 16 | лимиты по номеру решаются и берутся одним актом (1259) | backed | `queries.claim_paid_rung` (`queries.py:1130-1145`) — один `INSERT … SELECT … WHERE` с тремя клаузами | `test_two_selections_for_one_number_reach_the_vendor_once` гонит две прогулки конкурентно |
| 17 | форма — одна условная операция, не «запись, потом чтение» (1269-1271) | backed | `queries.py:1130-1143`; `limits.py:64-70` — `_why` читает историю **после** решения и только чтобы назвать | мутация «решение и запись двумя операторами» — вторая в `bite-limits-in-one-act.sh` |
| 18 | собственные рунги прогулки против неё не считаются (1276) | backed | `queries.py:1088` — `r.verification_id <> ?` в `_PAID_FOR_NUMBER` | `test_a_ladder_advances_from_one_paid_rung_to_the_next` — второй платный рунг берётся при нулевом возрасте первого |
| 19 | один потолок раздаётся рунгам как остаток (1295) | backed | `ladder.py:166-174` — `deadline` считается один раз, `seconds_left = deadline - now` на каждой итерации | тест:274 — потолок 1.0 с, второму рунгу достаётся < 0.7 с; контроль на 4.0 с |
| 20 | носитель держит потолок как дедлайн, а не длительность (1295) | backed | `tg_carrier.py:89,101,138`; `flash_carrier.py:86,185,191` | оба берут `deadline` на входе и отдают `deadline - time.monotonic()` |
| 21 | второму вендорскому вызову — остаток, а не всё (1297) | backed | `tg_carrier.py:138` | `test_the_second_vendor_call_gets_what_is_left_of_the_bound` + положительный контроль |
| 22 | носитель без потолка не падает молча на дефолт вендора (1305) | backed | `test_the_bound_reaches_the_vendor_and_is_not_the_adapters_own_default` (тест:336) | потолок 2.0 с меряется против дефолтов 5 с и 10 с, плюс контроль на 8.0 с |

### Утверждения аннотации «backed since 22.09.2026» (лимиты одним актом)

- `queries.claim_paid_rung` — один `INSERT … SELECT … WHERE` с тремя лимитами клаузами —
  **backed**, `app/db/queries.py:1130-1143`: каждая клауза на своей строке со своим лимитом.
- `ladder.walk` пишет каждый платный рунг через него — **backed**, `ladder.py:203-213`:
  `if route in PAID_ROUTES: limits.claim(...)`, иначе `record_verification_rung`.
  Ветвь `WITHHELD` (`ladder.py:195`) пишет напрямую только для `_MODEM_ROUTES` — не платных.
- вопроса по номеру нет в `gates.for_paid_ladder` — **backed**, `app/verification/gates.py:186-188`:
  три гейта (чёрный список, право тратить, потолок), четвёртого нет.
- сторож гонит две прогулки по одному номеру конкурентно и считает вендора; контроль —
  две прогулки по **разным** номерам — **backed**,
  `tests/test_the_numbers_limits_are_taken_in_one_act.py:87-122`, `gates=()` (строка 82).
- `bite-limits-in-one-act.sh` краснит пять — **backed**: пять мутаций (строки 52, 59, 94, 98,
  103), якоря всех пяти присутствуют в текущем коде дословно; среди них именованные
  «решение и запись двумя операторами», «счёт видит собственные рунги» и контроль
  «клейм отказывает всем». Скрипт не запускался (правит файлы — вне мандата свипа).

### Утверждения аннотации «backed since 22.09.2026 for the deadline»

- `tg_carrier.carry` берёт `deadline` на входе — **backed**, `tg_carrier.py:89`
  (`deadline = time.monotonic() + max(0.0, seconds_left)`; `max(0.0, …)` — защита от
  отрицательного остатка, на утверждение не влияет).
- отдаёт `deadline - time.monotonic()` обоим вендорским вызовам — **backed**,
  `tg_carrier.py:101` и `:138`.
- «что `flash_carrier` делал всегда» — **backed** по существу, `flash_carrier.py:86,185`;
  ⚠️ первый вызов там берёт `max(0.1, seconds_left)` (строка 114), а не остаток дедлайна
  — см. наблюдение 2 ниже; SHALL 21 это не нарушает.
- сторож читает **собственный аргумент timeout** второго вызова — **backed**,
  `tests/test_the_bound_is_a_deadline_not_a_duration.py:41-54,92` — замеряется число,
  переданное `send_verification_message`, а не время двери.
- `bite-bound-is-a-deadline.sh` краснит четыре — **backed**: четыре мутации, все якоря
  совпадают с текущим `tg_carrier.py` дословно, включая контроль «пол 0.1 с».

### Утверждения последнего `[backed]`-блока

- дверь — `select_verification_route` над `placement.py` в `app/api/router.py` — **backed**,
  `app/api/router.py:193` и `:270-273`.
- перенаправление — `queries.set_carrying_route` — **backed**, `queries.py:987`.
- потолок — настройка `verification_ladder_bound`, 10 с — **backed**,
  `app/settings_store.py:132` (`Spec("verification_ladder_bound", "float", 10.0, …)`),
  читается в `placement.py:178`.
- `tests/test_the_door_that_walks_the_ladder.py`, шестнадцать тестов — **backed**, ровно 16
  функций `test_*`.
- verify-прогон из `HANDOFF.md`, 41 спровоцированное утверждение — **backed**,
  `HANDOFF.md:1306-1311` («файловая БД с настоящими миграциями … 41 утверждение
  спровоцировано, ни одного падающего»).
- «Twenty mutations bite» — **не опровергнуто и не перепроверяемо**: `HANDOFF.md:1297`
  говорит, что `bite-door.py` жил в скрэтчпаде сессии и умер вместе с ней, а имена мутаций
  перечислены в сообщении коммита `fbee656`. Ставить `unbacked` не за что — утверждение
  честно помечено местом хранения; но прогнать его заново нельзя, в отличие от остальных
  укусов заявки.
- 🔴 «The second rung is `flash_call` and nothing carries it» — **contradicted**, находка 2.

### Сценарии требования 1

Все восемь имеют сторожа: 1 → тест:173 · 2 → тест:200 · 3 → тест:396 · 4 → тест:423 ·
5 → тест:536 · 6 → тест:503 · 7 → тест:336 · 8 → тест:447.

---

## Требование 2 — «A verification carried by the modem takes that message's outcome»
Строки 1498–1560. Исход: **чисто — 14 backed, ни одного contradicted или unbacked**.

### SHALL'ы

- верификация на `sms_out` владеет своим сообщением; сообщение помечено принадлежностью —
  **backed**, `app/verification/sms_carrier.py:80-81` — `create_message(..., verification_id=verification_id)`.
- смены статуса такого сообщения не пушатся приложению как статусы сообщения —
  **backed**, `app/modem/delivery_dispatch.py:74-77` — ранний возврат `False` до
  `find_route`/`deliver`; сторож `test_a_verifications_message_raises_no_message_status_push`
  гоняет все четыре статуса, положительный контроль — обычное сообщение той же двери.
- `sent` оставляет верификацию открытой — **backed**,
  `delivery_dispatch.py:38,130` (`_ENDS_A_VERIFICATION = {"failed", "expired"}`);
  сторож `test_a_sent_code_leaves_the_verification_open` гоняет `sent` и `delivered`.
- `failed`/`expired` валят верификацию с этой причиной — **backed**,
  `delivery_dispatch.py:134-137`; причина несёт текст ошибки модема.
- приложение извещается под **идентификатором верификации** — **backed**,
  `app/verification/dispatch.py:40-57` (`"object": "verification"`, субъект в
  `verification_id`, никогда в `id`), через развязку `announce_verification_outcomes`
  (`dispatch.py:72-111`), которая **действительно запущена**: `app/modem/manager.py:1724`.
  Сторож: `test_a_failed_code_fails_the_verification_under_its_own_id` — параметризован по
  `failed` и `expired`, проверяет `[p["verification_id"]] == [vid]`.
- рунг чтится всю жизнь сообщения, а не только в момент размещения — **backed**,
  `app/modem/manager.py:688-690` — `if await queries.verification_of_message(...) is not None:
  return False`, стоит **первым** в `_refuse_what_the_rule_routes_elsewhere`, до
  `_operator_for` и до чтения правила.
- прочитано из БД, а не из очереди (чтобы пережить resume после рестарта) — **backed**,
  там же; докстринг называет ровно эту причину, и запрос идёт по `message_id`.
- обычный текст для того же оператора по-прежнему отказывается — **backed**,
  `manager.py:707-733`; сторож
  `test_an_ordinary_message_is_refused_by_that_same_re_pointed_rule` требует `failed` и
  имя платного рунга в `error`.

### Утверждения аннотации

- `sms_carrier.py` — составляет из шаблона приложения, создаёт сообщение с
  `verification_id`, отдаёт отправителю — **backed**, `sms_carrier.py:58-87`
  (`template.for_app` → `INCAPABLE` при отсутствии, `compose`, `create_message`,
  `record_message_routing`, `modem.enqueue`).
- `app/db/migrate.py` — `messages.verification_id`, additive и NULL для существующих строк —
  **backed**, `migrate.py:495-499` — `_add_column_if_missing`, с комментарием об обратимости.
- `delivery_dispatch._the_verification_takes_this_outcome` на `dispatch_delivery` — единственная
  дверь, через которую проходят **все восемь** писателей статуса отправителя — **backed**:
  `delivery_dispatch.py:110`; восемь вызовов `spawn_delivery_dispatch` в `manager.py` —
  строки 803, 911, 937, 951, 1243, 1255, 1800, 1804. Ровно восемь.
- `app/modem/manager.py` — отправитель не перечитывает правило для размещённого лестницей —
  **backed**, `manager.py:688-690`.
- `tests/test_the_modem_rung_carries_a_code.py` и `test_a_verification_owns_its_message.py` —
  **backed**, оба существуют и зелены; второй несёт положительный контроль
  «обычное сообщение всё ещё извещает как сообщение».
- правило, перенаправленное **после** размещения, сторожится с 22.09.2026 со своим
  положительным контролем — **backed**,
  `tests/test_the_modem_rung_carries_a_code.py:295-364` — пара
  «код не брошен» / «обычный текст тем же правилом отказан».
- `bite-rule-repointed-after-placement.sh` краснит ещё четыре — **backed**: ровно четыре
  мутации в скрипте.
- `app/verification/probes.py` (`_sms_out_probe`, чтобы рунг можно было выбрать) —
  **backed**, `probes.py:129-171`; читает правило и **ловит** `UnreadableRule` (строка 157) —
  контраст, на котором видна находка 1.

### Сценарии требования 2

Все три имеют сторожа: «SMS с кодом падает» → `test_a_failed_code_fails_the_verification_under_its_own_id` ·
«сообщение верификации не извещает как сообщение» → `test_a_verifications_message_raises_no_message_status_push` ·
«правило уехало из-под уже размещённого кода» → `test_a_rule_re_pointed_after_placement_does_not_strand_the_code`
плюс его положительный контроль.

---

## Наблюдения (НЕ находки — ни один SHALL этим не нарушен)

1. **Отсутствующий платный рунг тратит аллованс номера.** `ladder.walk` зовёт
   `limits.claim` (`ladder.py:208`) **до** того, как `_attempt` выяснит, что носителя нет
   (`ladder.py:281-291`). На сегодняшней установке без ключа uCaller отклонённый Telegram-ом
   абонент получает вторую платную строку с исходом `absent` — вендора не спрашивали, а
   пятнадцатисекундный зазор и оба потолка уже потрачены. Формально спека сама требует
   считать «every recorded rung on a paid route whatever its outcome», поэтому это не
   противоречие норме, а её цена; но выглядит как та же семья дефектов, что и
   «бухгалтерия шлюза считается тратой», на один слой ниже. Стоит решения владельца, а не
   правки свипом.
2. **`flash_carrier` отдаёт первому вендорскому вызову `seconds_left`, а не остаток
   дедлайна** (`flash_carrier.py:114`), хотя дедлайн взят строкой 86 и между ними два
   `await` к базе. SHALL говорит про **второй** вызов, и второй (`_await_outcome`,
   строка 185) берёт остаток правильно — поэтому backed. Но асимметрия с `tg_carrier.py:101`
   существует, и если она намеренна, её стоит назвать в докстринге.
3. **Вне моих двух требований.** Соседнее требование «An open verification ends by itself,
   and its end is announced» (строка 1556) помечено `[unbacked · sweep precedent…]`, но
   `app/verification/dispatch.py:72` (`announce_verification_outcomes` — expire, announce
   once per verification, prune) существует и запущено из `app/modem/manager.py:1724`, а
   `tests/test_verification_outcome_reaches_the_app.py` его гоняет. Возможно, аннотация
   устарела в безопасную сторону. Передаю владельцу этого требования, сам не трогаю.
