# Вердикт круга критики · system-architect · 22.09.2026

Круг по ИТОГОВОЙ редакции. Мишень — восемь требований, написанных после 11.09.2026,
четыре постройки 22.09 и исполняющий их код. Потолок назван владельцем до запуска:
2 воркера × $5 ≈ $10. Это сырой вердикт воркера; сведение и проверка по коду — в HANDOFF.md.

итог: три находки — одна на границе платной лестницы (N1, куплена состоянием
`apps.may_spend`), одна на норме о едином потолке (N2), одна на основаниях норм (N3).
Чисто по: переезду 4.58, нормализации 4.59, `RouteOffer.number` (3.4), `bite-limits.sh`,
перечислимости денежной границы, ссорам норм между собой.

---

## N1. Гейты платной лестницы стоят на КАЖДОЙ ходке, включая модемную — и запрещают бесплатную отправку

**где:** `app/verification/placement.py:165` (`gates=gates.for_paid_ladder(app_id, phone)`),
`app/verification/gates.py:149-166`, `placement.py:64`
(`PLACED_HERE = frozenset({TG_GATEWAY, FLASH_CALL, SMS_OUT})`)

**норма:** outbound-routing/spec.md:550 — «Whether an application may have its verifications
carried by a **paid** route SHALL be an entitlement», сценарий 590: «requests a verification
for an operator routed to a **paid ladder**». phone-verification/spec.md:524 — «assembled
into every **paid** walk by `gates.for_paid_ladder`». Сам `gates.py:149`: «Every gate a walk
down the **paid** ladder has to pass».

**дефект:** `placement.place` подаёт полный список гейтов безусловно, а `PLACED_HERE`
включает `sms_out`. Слово «paid» живёт в имени функции и в докстринге и нигде не
проверяется: ходка, состоящая ровно из одного бесплатного модемного рунга, проходит
`entitlement_gate`, `ceiling_gate` и `limits.per_number_gate`. Три из четырёх гейтов задают
вопрос про деньги там, где денег нет. Чёрный список — единственный, который обязан стоять
безусловно (он про человека, не про цену), и он тут единственный уместный.

**сценарий отказа:** свежий выкат. `migrate.py:515` добавляет `may_spend INTEGER NOT NULL
DEFAULT 0` — у всех четырёх существующих приложений `may_spend = 0` (это ровно то, чего
норма 560-567 и требует). Абонент МТС, штатное правило `rule.SHIPPED` даёт `*` →
`["sms_out"]`, штатный порядок предложений `call_in,sms_out,flash_call,tg_gateway,sms_in`.
`POST /verifications` проходит, `sms_out` предложен. `POST /verifications/{id}/route
{"route":"sms_out"}` → `placement.place` → `entitlement_gate` → `422 refused`,
`reason = "entitlement: sp_app does not hold the entitlement to spend on a paid route"`,
`fail_verification`. SMS не уходит, верификация мертва. То есть в день выката капабилити не
работает ни для кого на модемном маршруте, а причина отказа называет платный маршрут,
которого в ходке не было. Тот же механизм даёт второй отказ: после ста платных рунгов за час
`ceiling_gate` глушит БЕСПЛАТНЫЕ модемные верификации и будит оператора текстом «the spend
ceiling refused a paid verification» (`gates.py:138`); и третий: `per_number_gate` отвечает
`too_soon` бесплатному рунгу за восемь секунд после чужой платной попытки на тот же номер.

**лекарство:** точечно и с сохранением границы (не переносить вопрос в дверь).
`for_paid_ladder(app_id, phone, rungs)` — `blacklist_gate` всегда, три остальных только при
`any(r in routes.PAID_ROUTES for r in rungs)`. Вызывающий один: в `placement.place` поднять
`rungs = ladder_from(route, operator)` в локальную и передать её и в `walk`, и в сборку
гейтов. В норме — дописать в outbound-routing/spec.md:575 и в
phone-verification/spec.md:961-967, что безусловен на лестнице именно чёрный список, а три
денежных гейта спрашиваются, когда в оставшейся лестнице есть платный рунг.

**проверено воркером по коду:** `placement.place` и `carriers_for` целиком;
`gates.for_paid_ladder`; `limits.per_number_gate`; `queries.get_app` (`queries.py:1966`) и
`migrate.py:515`; `rule.SHIPPED`; `settings_store` строка `verification_route_order`;
`probes._sms_out_probe`. В наборе комбинация не встречается:
`tests/test_the_door_that_walks_the_ladder.py:82` включает `may_spend` на весь файл,
`tests/test_the_modem_rung_carries_a_code.py` до двери не доходит (зовёт
`carriers_for`/`walk` напрямую) — зелёный набор эту дыру не видит.

---

## N2. «Один потолок на лестницу» держится до первого рунга с двумя вызовами вендора — и норма это разрешает

**где:** `app/verification/tg_carrier.py:92` и `:129` — оба `timeout=max(0.1, seconds_left)`

**норма:** phone-verification/spec.md:1098 — «The one bound SHALL be handed to each rung as
what is left of it, and each carrier SHALL apply it to its own vendor calls.»; выше, :1023 —
«the bound SHALL cover the ladder as a whole rather than each rung separately — otherwise two
rungs of a slow day take twice the time the application was promised».

**дефект:** формулировка «apply it to its own vendor calls» удовлетворяется реализацией,
которая выдаёт каждому вызову ВСЮ оставшуюся величину. `tg_carrier` держит длительность, а
не дедлайн: `seconds_left` посчитан один раз при входе в рунг, и `sendVerificationMessage`
получает его повторно, не зная, сколько уже съел `checkSendAbility`. Соседний
`flash_carrier` — тот же вопрос, решённый правильно: `flash_carrier.py:87`
`deadline = time.monotonic() + max(0.0, seconds_left)`, и дальше
`timeout=max(0.1, deadline - time.monotonic())` (`:185`). Два носителя под одной нормой
расходятся, потому что норма не различает длительность и дедлайн. Это ровно вопрос «какая
неверная реализация это удовлетворяет» — ответ лежит в дереве.

**сценарий отказа:** `verification_ladder_bound = 10` (штатно), правило МегаФон
`[tg_gateway, flash_call]`, уплинк переведён на резерв — по замеру самой заявки
(`probes.py:209`) `gatewayapi.telegram.org` на этом пути отваливается по таймауту в
пятнадцать секунд. Проверка отвечает подтверждением на девятой секунде (fee уже начислен,
`set_rung_outcome` записал `request_id`), после чего отправке выдаётся ещё девять секунд.
Дверь отвечает примерно на восемнадцатой при обещанных десяти; `ladder.walk` на следующем
витке видит `seconds_left <= 0` и обрывает лестницу — то есть `flash_call` не пробуется
вовсе, хотя по норме :1026 рунг, не ответивший в потолок, «SHALL be abandoned in favour of
the next». Человек стоит у барьера всё это время, клиент приложения свой таймаут уже отдал.

**лекарство:** в `tg_carrier.carry` завести `deadline = time.monotonic() + max(0.0,
seconds_left)` первой строкой и передавать `max(0.1, deadline - time.monotonic())` в оба
вызова — один в один как в `flash_carrier`. В норме заменить «each carrier SHALL apply it to
its own vendor calls» на «каждый носитель держит дедлайн, а не длительность: второй и
последующий вызов вендора внутри рунга получают то, что осталось от общего потолка», и
дописать сценарий про рунг с двумя вызовами (существующий «The bound reaches the vendor»
проверяет только, что потолок доехал, и на этой реализации зелёный).

**проверено воркером по коду:** `tg_carrier.carrier` целиком; `flash_carrier.carry` и
`_await_outcome`; `ladder.walk` (`deadline`/`seconds_left`, обрыв цикла на
`seconds_left <= 0`, отсутствие `wait_for`); `tg_gateway.check_send_ability`/
`send_verification_message` — обе никогда не бросают и честно принимают `timeout`, так что
удвоение приходит не из адаптера.

---

## N3. Одиннадцать укусов названы основанием и в дереве отсутствуют; три из восьми целевых требований держатся на них

**где:** outbound-routing/spec.md:229 (`bite-credentials.sh`), :504 (`bite-ladder.sh`,
`bite-carrier.sh`); phone-verification/spec.md:1247 (`bite-template.sh`). Тем же списком:
`bite-lookup.sh` (:59), `bite-rule.sh` (:144), `bite-modem.sh`/`bite-withhold.sh` (:678),
`bite-refusals.sh` (:714), `bite-code.py` (:117, 191, 867, 912), `bite-verif-view.sh` (:841).

**норма:** phone-verification/spec.md:554 — «a reference to a bite is a claim about the code
like any other, and is verified the same way». Она же, :1247: «guarded by
`tests/test_verification_template.py` and by nine mutations in `bite-template.sh`»;
outbound :503: «seventeen mutations in `bite-ladder.sh` and `bite-carrier.sh` each turn a
guard red».

**дефект:** урок, записанный 22.09 про `bite-limits.sh`, применён к одному имени и не
применён к остальным. `**/bite-*` по всему рабочему дереву даёт ровно одиннадцать файлов —
все заведены 21-22.09; одиннадцать других имён, на которые спека ссылается как на основание,
не существует ни по одному пути, и ни один шаблон `.gitignore` их не покрывает. Три из
восьми требований мишени — «credentials live in settings» (#1), «A paid ladder tries its
rungs in order» (#2) и «The text of an SMS-carried verification… there is no default» (#8) —
предъявляют в качестве доказательства файл, которого сегодня никто запустить не может.

**сценарий отказа:** не данные, а следующий круг ревью — и это тот же отказ, который заявка
уже один раз оплатила. Читающий видит «nine mutations in `bite-template.sh`» и принимает,
что `template.compose` защищён от подмены `replace` на `str.format`; перепроверить нечем,
потому что мутации существуют только как проза в спеке. Ровно так `bite-limits.sh` простоял
названным и непрогнанным до 22.09.

**лекарство:** не переписывать укусы. Либо снять из спеки имена, которых нет, оставив
`tests/…` как единственное основание (и там, где укус был реально прогнан, сказать
«прогонялся 1x.09, скрипт не сохранён» — это честная слабая форма), либо закоммитить
сохранившиеся файлы. Плюс сторож заявки: каждое имя `bite-*` из спеки обязано разрешаться в
файл — иначе валидация зелёная, а основание пустое.

**проверено воркером по коду:** `Glob **/bite-*` (11 файлов); `Grep bite-[a-z-]+\.(sh|py)`
по обоим файлам спеки (22 ссылки на 22 имени); `.gitignore` целиком; подсчёт мутаций в
присутствующих скриптах — заявленные числа сходятся.

⚠️ **Граница проверки воркера, названная им самим:** ему даны только Read/Grep/Glob,
коммитов он не смотрел — утверждает «отсутствует в рабочем дереве и не подпадает под
`.gitignore`», а НЕ «не существовало никогда». Историю обязана проверить сессия.

---

## Чисто — воркер прошёл и не нашёл

- **4.58, переезд чёрного списка.** Полный, а не вторая копия: `is_phone_blocked` в
  верификационном пути стоит ровно дважды — `router.py:140` (дверь, требуется нормой
  :1004-1006) и `gates.blacklist_gate` (граница лестницы, норма :954-967). Третьего
  экземпляра в пути верификации нет; `manager.py:948`, `telegram_poll.py:66`,
  `admin/router.py:231,268` — чужие двери со своими нормами.
- **4.59, нормализация до чтения оператора.** Держится ТИПОМ, а не порядком строк:
  `VerificationCreateRequest.validate_phone` (`schemas.py:61`) нормализует до тела
  обработчика, `record_operator` и `get_number_operator(row["phone"])` читают уже
  нормализованное. Ненормализованному номеру в лестницу не попасть.
- **3.4, `RouteOffer.number`.** Поле и фраза ключуются одним множеством
  `_NEEDS_GATEWAY_NUMBER` (`routes.py:176`), разойтись не могут; `number: str | None = None`
  — аддитивность держится схемой, а не дверью. Замечание, находкой не являющееся: докстринг
  `_number_for` (`routes.py:351`) ссылается на `_can_instruct`, такого имени в модуле нет —
  реальный сторож называется `_is_offerable`.
- **Перечислимость денежной границы.** Механическая и полная: деньги тратят
  `ucaller.init_call` и `tg_gateway.check_send_ability`/`send_verification_message`, у каждой
  ровно один вызывающий — тело носителя; носители собираются только в `carriers_for` и
  зовутся только из `ladder.walk`; у `ladder.walk` в `app/` один боевой вызывающий —
  `placement.place`. `ucaller.get_info` бесплатен. Пробы вендоров не трогают. Дыры «дверь,
  забывшая гейт» здесь нет — есть обратная ошибка, N1.
- **Ссоры норм между собой.** По восьми целевым требованиям пары, где поздняя норма молча
  отменяет раннюю, не нашёл. Сужение 4.47 объявлено явно, со ссылкой на отменяемое чтение
  (spec.md:1235-1242) — это то, как отмена должна выглядеть.
