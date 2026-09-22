ИТОГ злого прохода (спека и аннотации): выжило 10 · убито 1 · сужено 1 — аннотации о самих себе отстали от кода в пяти местах и обещают два несуществующих укуса, а единственное настоящее противоречие «код против спеки» (исключение собственного хода из лимитов) спека УЖЕ оговаривает отдельным SHALL, которого чекер не нашёл.

Задача прохода была одна: **убить** каждую находку шести чекеров. Убить нечем — исход
нормальный и здесь самый частый. Доказательством убийства считался найденный вызыватель,
найденный файл, найденный сторож или прочитанный текст требования, говорящий иное; «по
смыслу так и есть» убийством не считалось.

Ничего не правилось: ни код, ни спека, ни тесты. Прогнан один сторож
(`tests/test_the_numbers_limits_are_taken_in_one_act.py` — 4 passed), `app/` не мутировался.

---

## ГРУППА 1 — «аннотация отстала от кода»

### B1 — ВЫЖИЛА · `specs/outbound-routing/spec.md:607`

Аннотация: «⚠️ **Implemented is not reachable**: the gate has no production caller, because
the door that walks the paid ladder belongs to `verify-by-inbound-contact` and does not exist
yet».

**Убить нечем.** Вызыватель есть, и он продакшн:

- `app/api/router.py:193-198` — `POST /verifications/{verification_id}/route`, обычная дверь
  с `Depends(get_app_id)`, без флага и без ветки «не сегодня»;
- `app/api/router.py:274` — `return await _walk_the_ladder(...)` при `places_here(route)`;
- `app/api/router.py:304` — `walk = await placement.place(...)`;
- `app/verification/placement.py:168` — `gates=gates.for_paid_ladder(app_id, phone, rungs)`;
- `app/verification/gates.py:188` — `return (blacklist_gate(phone), entitlement_gate(app_id), ceiling_gate())`.

Роутер смонтирован: `app/main.py:11` и `app/main.py:131` (`app.include_router(router)`).
Проверено и обратное — что вызыватель не «тестовый»: других дверей у `placement.place` нет,
а эта одна и живая.

Единственное сужение, которое проход нашёл и которое находку НЕ убивает: гейт входа
спрашивается только там, где в ходке есть платный рунг (`app/verification/gates.py:186`).
Это по-прежнему продакшн-путь, просто не всякий.

**Чем лечится: спекой** — снять `⚠️`. Цена ошибки та, которую назвал чекер: `may_spend`
отгружается нулём, и читатель, поверивший оговорке, не заведёт право ни одному приложению
перед выкатом.

### B2 — ВЫЖИЛА · `specs/outbound-routing/spec.md`, блок 728-815

Аннотация: «⚠️ **Counted is not produced:** the only caller today is `ladder.walk`, which has
no production caller of its own — the send-path refusal … is task 4.6».

**Убить нечем, и неверны обе половины.**

- У `ladder.walk` вызыватель есть: `app/verification/placement.py:162`, куда приходят из
  `app/api/router.py:304` (цепочка та же, что в B1).
- У `refusals.record` есть ВТОРОЙ вызыватель, и он на отправочном пути модема:
  `app/modem/manager.py:751` внутри `_refuse` (`:735`), которую зовут
  `app/modem/manager.py:700`, `:708` и `:732` — все три из
  `_refuse_what_the_rule_routes_elsewhere` (`:639`), а её зовёт `_send_one`
  (`app/modem/manager.py:759`), первой строкой, до кодирования текста.

То есть «семьдесят отказов в месяц», ради которых счёт и заведён, производятся уже сегодня.

**Чем лечится: спекой.**

### B3 — ВЫЖИЛА · `specs/outbound-routing/spec.md:249-252`

Аннотация: «⚠️ **Nothing in production reads the bearer yet** … and `flash_call` has no probe
registered and is therefore never offered».

**Убить нечем; код опережает аннотацию по обоим пунктам.**

- `app/verification/probes.py:78` — `FLASH_CALL: _flash_call_probe(ucaller_bearer)` в
  `build_probes`; тело пробы — `app/verification/probes.py:226`;
- `app/api/router.py:94` — `ucaller_bearer=ucaller.configured_bearer() or ""` передаётся
  в `build_probes` на каждый запрос (реестр строится по запросу, `router.py:83-101`);
- `app/verification/placement.py:122-128` — при непустом бирере собирается
  `flash_carrier.carrier(...)`;
- адаптер вендора написан целиком: `app/verification/ucaller.py:369-489`
  (`init_call`, `get_info`, `get_balance`, `_call`), бирер собирается в `ucaller.py:29-49`.

Дополнительное доказательство от самой заявки: `bite-flash-call.sh:116` несёт мутацию
«15. проба flash_call не зарегистрирована» — укус, который имеет смысл только над
зарегистрированной пробой.

**Чем лечится: спекой.**

### B4 — ВЫЖИЛА · `specs/outbound-routing/spec.md:254`

Аннотация: «Still unbacked: every rung-skipping clause below, which needs the door».

Словарь тега здесь не на моей стороне и проверен отдельно: `openspec/specs/outbound-send/spec.md:15`
определяет `unbacked` как «an accepted gap **with no code behind it yet**» — то есть
утверждение именно о коде, а не о сторожах. Код есть:

- «A rung skipped for a missing credential SHALL raise an operator alert on the configuration
  the gateway ships with» — `app/verification/ladder.py:281-291` (`carrier is None` →
  `notify("routing", …, dedup_extra=f"absent:{route}")`), канал включён по умолчанию:
  `app/settings_store.py:79` (`notify_routing_errors`, `True`), карта канала —
  `app/alerting.py:392`;
- «and the ladder SHALL then advance past it as it would past a decline» —
  `app/verification/ladder.py:77`: `ABSENT` входит в `_ADVANCING`;
- «A ladder every one of whose rungs was skipped SHALL fail the verification … and SHALL NOT
  fall back to `sms_out`» — `app/verification/ladder.py:265-267` (`_why_nothing_carried` +
  `fail_verification`) и `:308-313`; перехода на `sms_out` в коде нет — модем идёт только
  там, где его назвало правило (`placement.PLACED_HERE`, `placement.py:64`, и только по
  рунгам из `ladder_from`).

Дверь, которой клаузам «не хватало», существует: `app/verification/placement.py:149-181` +
`app/api/router.py:289-330`.

⚠️ **Одна половина фразы в требовании при этом исполнена не буквально, и это НЕ спасает
аннотацию, но должно быть записано:** требование просит «fail … with a reason **naming the
missing credentials**», а `_why_nothing_carried` (`ladder.py:308-313`) называет рунги и их
исходы («no rung carried this verification: tg_gateway absent, flash_call absent»), а не
учётные данные. Для оператора это разрешимо, для буквы — нет.

**Чем лечится: спекой** (снять `unbacked`), и отдельно — решением владельца, считать ли
перечисление рунгов исполнением «naming the missing credentials».

### B5 — ВЫЖИЛА · `specs/phone-verification/spec.md:1330-1331`

Аннотация: «🔴 **The second rung is `flash_call` and nothing carries it** (task 4.17, blocked
on 1.1), so today a declined subscriber ends in the loud-skip path rather than in a call».

**Убить нечем.**

- Носитель строится: `app/verification/placement.py:122-128`;
- носитель написан: `app/verification/flash_carrier.py` (330 строк), адаптер —
  `app/verification/ucaller.py:369-489`;
- проба зарегистрирована: `app/verification/probes.py:78`;
- задачи закрыты обе: `tasks.md:8` — `- [x] 1.1`, `tasks.md:555` — `- [x] 4.17`;
- докстринг самого `carriers_for` говорит аннотации прямо обратное:
  `app/verification/placement.py:88-92` — «`flash_call` was absent here until 22.09.2026 …
  and is now present on exactly the same terms as the Telegram rung».

**Чем лечится: спекой.** Пока не снято, читатель считает, что отказ Telegram кончается
громким пропуском, — тогда как на настроенном эстейте он кончается **платным звонком**.

---

## ГРУППА 2 — «аннотация ссылается на укус, которого нет»

### B6 — ВЫЖИЛА · `specs/outbound-routing/spec.md:235`

Аннотация: «**The environment half is backed** by
`tests/test_credentials_do_not_live_in_the_environment.py` and **seven mutations**…»

**Убить нечем — укуса нет нигде.**

- Тест существует и зелёный: шесть функций (`tests/test_credentials_do_not_live_in_the_environment.py:91,115,137,195,219,257`),
  причём `:219` — собственный положительный контроль переписи;
- ни один укус заявки его не гоняет: перечислены все `TESTS=` двадцати семи `bite-*.sh`
  (`bite-credentials.sh:15` — `tests/test_vendor_credentials.py`; `bite-ucaller.sh:9` —
  `test_ucaller_credentials.py` + `test_vendor_credentials.py`; остальные не касаются);
- `bite-code.py:27` гоняет `tests/test_the_code_and_who_may_spend_it.py` — тоже не он;
- по истории: `git grep credentials_do_not_live $(git rev-list --all)` даёт попадания
  **только** в `specs/outbound-routing/spec.md` и в свип-отчёт
  `sweep-2026-09-22-rule-and-credentials.md` — ни одного скрипта ни в одном коммите,
  достижимом из любого рефа (414 коммитов).

Это тот же дефект, который заявка уже поймала на `specs/phone-verification/spec.md:623`
(«no such file had ever been committed, so the seven mutations it claims were never run by
anything»), и там же записала урок: **ссылка на укус — утверждение о коде и проверяется
так же.**

**Чем лечится: либо кодом** (написать укус и прогнать), **либо спекой** (убрать число).
Владельцу стоит заметить, что урок записан в этой же дельте и всё равно повторился.

### B7 — СУЖЕНА · адрес в задании неверен; находка настоящая, но по другому адресу

Мне было заявлено: «`specs/phone-verification/spec.md:764-893`: аннотация обещает пять
мутаций, скрипта нет».

**По названному адресу находка УБИТА.** В блоке 764-893 (требование «What verifications cost
is visible before the bill is») обещания «пяти мутаций» нет вовсе, а те, что есть, сходятся:

- «`bite-nobody-is-watching.sh` turns **seven** red» — семь и есть: шесть через `mut`
  (`bite-nobody-is-watching.sh:51,73,83,90,97,103`) плюс мутация №2, идущая мимо `mut`
  двумя правками (`:54-69`, перенос вызова за `yield`);
- «mutation 9 of `bite-flash-call.sh`» — на месте: `bite-flash-call.sh:87`
  («9. наблюдаем баланс до списания»).

**Находка при этом настоящая, и её адрес — `specs/phone-verification/spec.md:752`**, то есть
требование «The application learns a verification's outcome without polling the modem»
(736-763): «…asserts the verification's number appears in exactly one field; **five mutations
bite**, including one that moves the message contract underneath it». Скрипта с этими пятью
в заявке нет: единственный укус, гоняющий `tests/test_verification_outcome_reaches_the_app.py`, —
`bite-late-call-outcome.sh:7`, и его одиннадцать мутаций (`:42-96`) — про поздний исход
звонка, не про форму рассылки. Чекер `cost-and-dispatch` это и написал
(`sweep-2026-09-22-cost-and-dispatch.md:244`), применив три мутации вручную; воспроизвести
именно **пять** нечем.

**Чем лечится: тем же, чем B6** — укусом или снятым числом.

---

## ГРУППА 3 — расхождение текста и кода

### B8 — УБИТА · `app/db/queries.py:1088` (`AND r.verification_id <> ?`)

Два чекера разошлись: чекер лестницы считает исключение необходимым, чекер вендорских
исходов — противоречащим букве требования `specs/phone-verification/spec.md:555-638` и
предлагает чинить спекой.

**Находка убита прочитанным текстом требования: исключение УЖЕ написано в спеке, отдельным
SHALL, в той же дельте.**

`specs/phone-verification/spec.md:1276` — требование «Selecting a rung the gateway places
walks the ladder inside that selection»:

> **A walk's own rungs SHALL NOT count against that walk.** A ladder claims its second paid
> rung while the first one's row is zero seconds old, so a count that read its own walk would
> refuse the ladder the right to advance at all … Every *other* request still counts them,
> which is what this requirement asks for: what the vendor counts is an authorisation placed,
> and one verification places more than one.

Это дословно то, что делает `queries.py:1088`, вместе с тем же обоснованием. Проверка
`sweep-2026-09-22-vendor-outcomes.md:79` — «текст требования не содержит этого исключения
нигде, проверено грепом по `specs/`» — не выдержала: грепом по `specs/` оно находится, просто
в соседнем требовании того же файла. Два требования при этом не противоречат друг другу:
555-638 задаёт **единицу счёта** (рунги, а не верификации), 1276 задаёт **область** (чужие
ходки, а не своя), и второе прямо объясняет, почему первое этим не нарушено.

**Рассуждение: кто неправ.** Неправ ни код, ни спека — неправа находка.

- Код прав и по существу: без исключения второй платный рунг одной лестницы не заклеймился
  бы НИКОГДА (строке первого ноль секунд от роду при минимальном зазоре в пятнадцать), а
  `app/verification/ladder.py:208-213` при отказе `limits.claim` возвращает
  `Walk(refused_by=…)` — то есть бросает ВСЮ лестницу, а не пропускает рунг. Лестница
  `[tg_gateway, flash_call]` умирала бы на втором рунге с `too_soon`, выглядя как гейт,
  делающий свою работу.
- Спека и сама этого требует в другом месте: `specs/outbound-routing/spec.md:724` — сценарий
  «The ceiling counts the ladder, not the rung»: «verifications advance from the first rung to
  the second often enough that the **two rungs together** reach the configured ceiling». Потолок
  этот — платный (`gates.ceiling_gate` над `routes.PAID_ROUTES`), значит спека сама
  предполагает лестницу, продвигающуюся с платного рунга на платный.
- Сторож на месте и зелёный: `tests/test_the_numbers_limits_are_taken_in_one_act.py:149`
  (`test_a_ladder_advances_from_one_paid_rung_to_the_next`) и обратная половина на `:87`;
  прогон — 4 passed.

**Отдельный вопрос, решающий цену: засчитает ли вендор эти две авторизации как две?**

**Нет.** Платных маршрутов два, и это два РАЗНЫХ вендора: `PAID_ROUTES = {flash_call,
tg_gateway}` (`app/verification/routes.py:72`) — uCaller и Telegram Gateway. Лимит, ради
которого всё это написано, — uCaller'ский и по номеру У НЕГО: четыре авторизации в минуту,
не ближе пятнадцати секунд, тридцать в сутки, штраф — десять часов блокировки номера
(`specs/phone-verification/spec.md:557-560`). Одна ходка лестницы ставит **не более одной
авторизации у каждого вендора**, и это не случайность, а сторож: правило запрещает называть
маршрут дважды — `app/verification/rule.py:111-113`, «a route is named twice; a rung is
attempted at most once», `ValueError` на разборе. Значит uCaller видит одну авторизацию,
Telegram — одну, и десятичасовой блокировки эта конструкция произвести не может. Повтор
верификации открывает НОВУЮ верификацию (`specs/phone-verification/spec.md:639+`), а её
рунги считаются полностью.

Остаточная строгость, которую исключение действительно ослабляет, — собственное, более
строгое чтение «лимиты применяются к лестнице целиком» (`spec.md:575-581`), написанное про
Telegram, чьи лимиты не опубликованы. Но оно ослаблено **по решению, записанному в спеке**
(1276), а не по недосмотру кода.

### B9 — ВЫЖИЛА · `specs/outbound-routing/spec.md:289-349`

«…SHALL be recorded as having been routed without a known operator, so that the case is
countable rather than invisible» — на платных рунгах не исполнено.

**Убить нечем.**

- Пара пишется одной функцией: `app/db/queries.py:1866`
  (`UPDATE messages SET routed_route = ?, routed_operator = ? WHERE id = ?`), колонки
  заведены `app/db/migrate.py:478-479`;
- вызывателей ровно три, и все — модемные: `app/modem/manager.py:721`, `:749`,
  `app/verification/sms_carrier.py:85`;
- `tg_carrier.py` и `flash_carrier.py` строк в `messages` не создают вовсе;
- `verification_rungs` (`app/db/migrate.py:338-348`) и `verifications`
  (`app/db/migrate.py:311-329`) колонки оператора не держат — схема прочитана целиком;
- по всему `app/verification/` оператор попадает в БД ровно в одном месте —
  `ladder.py:152`, `refusals.record(...)`, и только когда ПРАВИЛО ОТКАЗАЛО, то есть в
  счёте отказов, а не в записи о том, чем повезли.

То есть верификация, которую понесли `tg_gateway` или `flash_call`, случай «поехало без
известного оператора» нигде не оставляет. Модемная верификация оставляет
(`sms_carrier.py:85`), и находка этого не отрицает.

**Чем лечится: кодом** (колонка оператора на `verification_rungs` или строка в `messages` для
платных рунгов) — либо решением владельца сузить требование до модемного пути, но это
именно решение: обоснование клаузы («the numbers most likely to lack an operator row are the
ones never messaged before, and a first-time recipient is exactly who a confirmation code is
usually for», `spec.md:301-303`) написано ровно про верификации.

### B10 — ВЫЖИЛА · `specs/phone-verification/spec.md:882-884`, сценарий «A fee that bought nothing»

«…и the count is readable beside the attributed spend».

**Убить нечем.** По всему `app/` агрегат ровно один и он не про деньги:
`app/db/queries.py:429` — `SUM(CASE WHEN status = 'delivered' THEN 1 ELSE 0 END)` в счётчике
сообщений. Ни `SUM(cost)`, ни любой другой свод по `verification_rungs.cost` в коде нет.
Данные для него записаны (`verification_rungs.cost`, `app/db/migrate.py:343`;
`outcome='unanswered'` как класс «возможно оплачено», `app/verification/ladder.py:65` — `UNANSWERED = "unanswered"  # possibly charged`), но
класса «плата, не привязанная ни к какой верификации» никто не считает, и «beside the
attributed spend» читать негде.

Ближайшее, что есть, — стоимость ОДНОЙ строки рунга в панели номера
(`app/admin/templates/messages.html:173,185`). Это не счёт.

**Чем лечится: кодом** (запрос + место в админке) или спекой (снять сценарий до отдельной
задачи).

### B11 — ВЫЖИЛА · там же, «A month's spend is answerable» и «The spend is answerable per application»

**Убить нечем, и по тому же доказательству:** данные записаны
(`verification_rungs.cost`, `verifications.app_id` — `app/db/migrate.py:311-348`), запроса
нет ни в `app/db/queries.py` (единственный `SUM(` — `:429`), ни в админке
(`app/admin/router.py` и `app/admin/templates/` — слово «spend» встречается только как
`may_spend`, право приложения, `admin/router.py:501`, `apps.html:25`).

То есть на вопрос «что стоил call-маршрут в прошлом месяце» и «какое приложение это
потратило» сегодня отвечает только чтение базы руками — ровно то, что сценарии называют
исполнением, а требование `outbound-routing` в соседнем месте прямо запрещает
(«visible to an operator without reading the database»).

**Чем лечится: кодом.**

### B12 — ВЫЖИЛА · `specs/phone-verification/spec.md:11-121` против `:1215+`

Первый SHALL требования 11-121: «The gateway SHALL choose the method from the routing rule,
SHALL return that choice **in the same response** together with the verification's id», и два
сценария: «the response carries the verification id and names the call method, **and the call
is placed**» (`:106-108`), «the response names the Telegram method rather than the call, and
no call is placed» (`:110-112`).

**Убить нечем.** Код двухшаговый:

- `app/api/router.py:129-188` — `POST /verifications` возвращает
  `VerificationCreateResponse` со **списком** `routes: list[RouteOffer]`
  (`app/api/router.py:183-188`), и собственный докстринг двери говорит: «Accept a number,
  prove the routes that can carry it, and **place nothing**» (`app/api/router.py:134`);
- метод называется и рунг кладётся только в `POST /verifications/{id}/route`
  (`app/api/router.py:191-330`).

**Рассуждение: есть ли между требованиями настоящее противоречие. Да, настоящее, и неправа
спека — а именно вступительный абзац требования 11-121 и два его сценария.**

- Требование `:1215` («Selecting a rung the gateway places walks the ladder inside that
  selection») существует ТОЛЬКО при отдельной двери выбора: «A route SHALL NOT be **offered,
  selected, recorded**, and then left unplaced», «the ladder SHALL be walked **before the
  selection is answered**». При одношаговой двери выбирать нечего и это требование мертво
  целиком — вместе со своими двадцатью мутациями и шестнадцатью тестами.
- Контракт несёт четыре двери и прямо называет форму: `docs/verification-api.md:17-21` —
  `POST /verifications → id + the routes that can carry it right now`,
  `POST /verifications/{id}/route → you pick one`; и дальше жирным: «**You do not choose a
  mechanism — you choose from what we offer**» (`:24-30`).
- Остальные половины самого требования 11-121 писались уже под двухшаговую дверь и с кодом
  согласны: «the method named in the response is the rung that actually accepted the
  verification» (`:32-36`) — это ответ ВЫБОРА, а не создания; номер как данные
  (`RouteOffer.number`) живёт в элементе списка предложений.
- Собственный перечень владения в том же абзаце устарел вместе с ними: он называет три
  двери (`POST /verifications`, `POST /verifications/{id}/check`, `GET /verifications/{id}`,
  `:26-29`), а способность держит четыре.

Проверено и то, что противоречие внутреннее для одной дельты: `openspec/specs/` не содержит
capability `phone-verification` вовсе, оба требования — `## ADDED` одной заявки.

**Чем лечится: спекой.** Код следует более позднему и более подробному требованию, и менять
его значило бы убить `:1215` целиком.

---

## Что прогонялось

```
/Users/deralsem/dev/sms-gate/venv/bin/python -m pytest \
  tests/test_the_numbers_limits_are_taken_in_one_act.py -q
→ 4 passed
```

`app/` не мутировался (по дереву ходят другие читатели). История проверена
`git grep <pattern> $(git rev-list --all)` по 414 коммитам.
