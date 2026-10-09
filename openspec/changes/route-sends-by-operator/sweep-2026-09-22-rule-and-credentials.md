# Свип «код против спеки» — правило и учётные данные, 22.09.2026

ИТОГ: backed 58 · contradicted 3 · unbacked 2 — правило и учётные данные исполнены как написано; настоящий дефект один (дверь верификации ждёт обновления ПРОТУХШЕЙ строки оператора, что требование запрещает дословно), остальные два «contradicted» — это аннотация требования 2, отставшая от кода.

---

## Находки

### 🔴 contradicted · требование 3 · дверь верификации задерживает ответ из-за ПРОТУХШЕГО оператора

**SHALL:** «Nothing SHALL be delayed, held or failed because the recipient's operator is
unknown, unresolved **or stale**» (spec.md:291-293), и отдельно: «**The bound SHALL be spent
only where the cache holds no operator at all.** A stale row still names one, and refreshing
it changes no routing decision this rule can make» (spec.md:325-329).

**Код:** `app/api/router.py:182` — `await record_operator(body.phone)`, безусловно, без
`wait_for`. `app/lookup/operator.py:35-40` — строка, которая есть, но протухла
(`is_stale`, `voxlink_cache_ttl_days`, по умолчанию 7 дней), **не возвращается сразу**:
функция идёт в `voxlink.lookup` и ждёт HTTP-ответа.

**Сценарий отказа:** номер, которому уже слали больше семи дней назад, — строка в
`number_operators` есть и называет оператора. `POST /verifications` на этот номер уходит в
`voxlink.lookup` и держит ответ приложению до `voxlink_timeout` (по умолчанию 5,0 с,
`app/settings_store.py:47`). Voxlink недоступен — человек у барьера ждёт полные пять секунд
**за обновление, которое не может изменить ни одного маршрутного решения**: `route_for`
читает то же имя оператора до и после. В отправителе это сделано правильно —
`app/modem/manager.py:606-608` возвращает закэшированное имя и бюджет не тратит; у двери
такой проверки нет вовсе.

Соседний сторож `tests/test_send_path_operator_lookup.py:198`
(`test_a_stale_row_is_used_as_it_stands_and_not_refreshed`) закрывает ровно этот случай —
но только в отправителе. Двери он не касается.

### 🔴 contradicted · требование 2 · аннотация утверждает, что `flash_call` не подключён, — код подключил его

**Аннотация (spec.md:249-252):** «⚠️ **Nothing in production reads the bearer yet**: the
settings page reads the rows, but the vendor is called by nobody until the adapter lands
(task 4.17), and `flash_call` has no probe registered and is therefore never offered.»

**Код говорит обратное по обоим пунктам:**
- `app/verification/probes.py:78` — `FLASH_CALL: _flash_call_probe(ucaller_bearer)`, проба
  зарегистрирована; её тело — `probes.py:226-251`;
- `app/api/router.py:94` — `ucaller_bearer=ucaller.configured_bearer() or ""` передаётся в
  `build_probes` на каждом запросе;
- `app/verification/placement.py:122-128` — `bearer = ucaller.configured_bearer()`, и при
  непустом бирере собирается `flash_carrier.carrier(...)`;
- адаптер вендора написан целиком: `app/verification/ucaller.py:369-489`
  (`init_call`, `get_info`, `get_balance`, `_call`).

**Чем это проявится:** читающий спеку считает рунг неподключённым и не станет искать его в
деньгах — при том, что на настроенном эстейте он предлагается, идёт в лестницу и платится.
Направление ошибки — аннотация отстала, код впереди; дефекта в коде нет.

### 🔴 contradicted · требование 2 · «Still unbacked: every rung-skipping clause below» — эти клаузы реализованы

**Аннотация (spec.md:254):** «Still unbacked: every rung-skipping clause below, which needs
the door».

**Код (дверь существует — `app/verification/placement.py:149-181`, `app/api/router.py:289-330`):**
- «A rung skipped for a missing credential SHALL raise an operator alert on the configuration
  the gateway ships with» — `app/verification/ladder.py:281-291`: отсутствующий carrier →
  `notify("routing", …)`; `app/settings_store.py:79` — `notify_routing_errors` по умолчанию
  `True`; `app/alerting.py:392` — канал `routing`;
- «and the ladder SHALL then advance past it as it would past a decline» —
  `app/verification/ladder.py:77`, `ABSENT` входит в `_ADVANCING`;
- «A ladder every one of whose rungs was skipped SHALL fail the verification with a reason
  naming the missing credentials, and SHALL NOT fall back to `sms_out`» —
  `app/verification/ladder.py:265-267` + `_why_nothing_carried` (308-313): причина
  перечисляет рунги и их исходы, `fail_verification` вызывается, и никакого перехода на
  `sms_out` в коде нет — модем идёт только там, где его назвало правило.

Снова: код впереди аннотации.

### ⚪ unbacked · требование 2 · «семь мутаций» за средовую половину не существуют нигде

**Аннотация (spec.md:235):** «**The environment half is backed** by
`tests/test_credentials_do_not_live_in_the_environment.py` and **seven mutations**…»

Тест существует и зелёный (6 тестовых функций, прогнаны). **Мутаций нет:** в каталоге заявки
нет укуса, который гонял бы этот файл — `bite-credentials.sh` гоняет
`tests/test_vendor_credentials.py`, `bite-ucaller.sh` гоняет
`test_ucaller_credentials.py`+`test_vendor_credentials.py`, остальные не касаются его вовсе.
Репозиторный греп по `credentials_do_not_live` не находит ни одной ссылки вне самого файла —
ни в `tasks.md`, ни в `HANDOFF.md`.

Это ровно тот дефект, который эта же заявка уже поймала на другой спеке
(`specs/phone-verification/spec.md:623`: «had ever been committed, so the seven mutations it
claims were never run by anything»).

### ⚪ unbacked · требование 3 · «routed without a known operator» не считается на платных рунгах

**SHALL (spec.md:295-298):** «the item … SHALL be recorded as having been routed without a
known operator, so that the case is countable rather than invisible».

**Что есть:** пара `messages.routed_route` / `messages.routed_operator`
(`app/db/migrate.py:478-479`, `app/db/queries.py:1850-1866`), пишется из
`app/modem/manager.py:721` и `:749` и из `app/verification/sms_carrier.py:85`.

**Чего нет:** верификация, которую понесли `tg_gateway` или `flash_call`, строки в `messages`
не создаёт вовсе (`tg_carrier.py`/`flash_carrier.py` — ни одного упоминания `messages`), а
`verification_rungs` (`app/db/migrate.py:338-348`) и `verifications`
(`app/db/migrate.py:311-329`) колонки оператора не держат. Значит на платных рунгах случай
«поехало без известного оператора» не записывается ничем и остаётся невидимым — именно то,
что требование называет причиной клаузы.

---

## Требование 1 (строки 76–180): «The route is chosen by a configured rule keyed on the recipient's operator»

**Исход: backed.** Опровергающий проход ничего не сломал.

| Утверждение | Исход | Доказательство | Что проверено |
|---|---|---|---|
| Выбор маршрута — конфигурация, читаемая на момент отправки | backed | `app/verification/rule.py:208-211` | `route_for` импортирует store внутри вызова и читает `store.get(KEY)` на каждый вызов, а не при импорте |
| Добавление/смена/удаление записи не требует правки кода и выката | backed | `app/settings_store.py:624-653`, `rule.py:196-228`; `tests/test_routing_rule.py:94` | `set_many` обновляет кэш в той же транзакции; следующий `route_for` видит новое без рестарта |
| Значение записи — упорядоченный список, пробуемый в порядке записи | backed | `rule.py:102-104`; `app/verification/placement.py:132-146` | `ladder_from` берёт срез `named[index(route):]`, порядок из данных |
| Ни одно имя оператора не стоит в ветви на пути отправки | backed | грep по `app/`: попадания только в комментариях/докстрингах, плюс `rule.py:66` (`SHIPPED`) и `settings_store.py:313` (текст `description`) | ни одной `if`-ветви на имени оператора нет |
| Порядок лестницы не зашит | backed | `rule.py:224` (`list(rule[key])`), `placement.py:137-139` | порядок возвращается как записан; укус №2 в `bite-rule.sh` бьёт именно сюда |
| Правило не ключуется на `app_id` | backed | `rule.py:93-98` | `_entry` бросает `ValueError` на присутствие ключа `app_id` |
| Правило — собственная типизированная настройка, валидируемая при сохранении | backed | `settings_store.py:311` (тип `oproutes`), `:448-451` → `rule.validate`, `:509-511` → `rule.normalize` | тип разведён с `routes` (диспетч-маршруты), своя валидация |
| Непустой упорядоченный список из известных маршрутов | backed | `rule.py:102-110`, `_ALLOWED = ALL_ROUTES \| {REFUSE}` (`:59`) | пустой список и неизвестное имя отвергаются с указанием записи |
| Записи стрипаются на записи И на чтении | backed | `rule.py:99`, `:105`, `:146-170`; `settings_store.py:628` (`normalize_raw` до валидации) | `set_many` нормализует прежде, чем писать |
| Маршрут, названный дважды, отвергается при сохранении | backed | `rule.py:111-113` | `len(set(routes)) != len(routes)` |
| Не переносится на существующую dispatch-route настройку | backed | `settings_store.py:311` против настроек типа `routes` с `route_key` | разные ключи и разные типы |
| Нечитаемое правило поднимает алерт и НЕ читается как пустое | backed | `rule.py:74-75`, `:180-185`, `:210-219` | `UnreadableRule` + `notify("routing", …)` внутри `route_for`, один раз на чтение |
| Маршрут по умолчанию — запись того же правила | backed | `rule.py:50` (`DEFAULT = "*"`), `:225-227` | в коде нет вшитого «иначе модем» |
| `?` отделён от `*` намеренно | backed | `rule.py:51`, `:222-227` | пустой ключ идёт ТОЛЬКО в `?` и не проваливается в `*` |
| `refuse` стоит в записи один | backed | `rule.py:114-116` | ладдер за отказом отвергается при сохранении |
| Правило, которому нечего ответить, отказывает, а не угадывает | backed | `rule.py:220-228` | `[REFUSE]` и на пустом правиле, и когда нет ни записи, ни `*`/`?` |
| Два написания одного оператора отвергаются при сохранении | backed | `rule.py:134-143` (свёртка `fold`, NFKC+casefold, `:78-85`) | свёртка в Python, не `upper()`/`LIKE` |
| Аннотация: `app/verification/rule.py` | backed | файл существует, 233 строки | — |
| Аннотация: `tests/test_routing_rule.py` | backed | 15 тестов, прогнаны, зелёные | сценарии спеки покрыты поимённо (`:106` дефолт, `:117` `?`, `:145` неизвестный маршрут, `:222` нечитаемое, `:246` нет дефолта) |
| Аннотация: `bite-rule.sh`, восемь красных, названные поимённо | backed | файл существует и исполним; все **восемь** якорей найдены ровно по одному разу в `rule.py` | проверено статически — якоря уникальны, мутации имеют цель; сам скрипт не гонялся (в ворктри работают параллельные читатели) |

**Опровергающий проход.** Искал: проверку, стоящую после обесценивающей (`_entry` проверяет
неизвестный маршрут ДО дубля и ДО «`refuse` один» — порядок верный); сравнение значения с
собой (нет); сторожа, который не запускается (все 15 прогнались); ветвь без входа
(`rule.py:225` — обе стороны `UNKNOWN if not key else DEFAULT` достижимы).

⚠️ Одна асимметрия, не нарушающая ни одного SHALL: `parse` (`rule.py:186-193`) два написания
одного оператора **не** отвергает — молча побеждает последнее. Требование говорит «refused at
**save time**», и `validate` это делает; но правило, записанное в `settings` в обход двери
(прямой SQL, миграция), пройдёт без слова.

---

## Требование 2 (строки 181–262): «A route's credentials live in `settings`, marked secret, and never in the environment»

**Исход: backed по коду; аннотация отстала в двух местах и один её пункт беспочвенен.**

| Утверждение | Исход | Доказательство | Что проверено |
|---|---|---|---|
| Учётные данные читаются из `settings`, каждое — своя настройка, помеченная секретом | backed (с оговоркой ниже) | `app/settings_store.py:167` (`tg_gateway_token`, `is_secret=True`), `:218` (`ucaller_key`, `True`) | оба вендора объявлены; см. ⚠️ про `ucaller_service_id` |
| Консоль говорит «заведено», значения не рисует | backed | `app/admin/router.py:532-533` (`"value": "" if spec.is_secret else current`, `"configured": bool(current)`), шаблон `settings.html` без `value=` у `type="password"` | `tests/test_vendor_credentials.py:70,93,106` — значение не доходит даже до строки вида |
| Смена не требует рестарта | backed | `app/api/router.py:93-94`, `app/verification/placement.py:105,122` | и токен, и бирер читаются из store на каждый запрос |
| Вендорское учётное не читается из окружения на отправке | backed | `app/config.py` (ни одного вендорского поля), `tests/test_credentials_do_not_live_in_the_environment.py:195-216` (перепись по AST), `:257-285` (вторая поверхность — `BaseSettings(env_file=".env")`, белый список из одного `admin_password`) | обе поверхности утверждены; перепись имеет собственный укус (`:219`) |
| Два вендора — две раздельные настройки | backed | `settings_store.py:167`, `:218`, `:225` | — |
| Рунг без учётного не пробуется и не зовётся неаутентифицированным «чтобы узнать» | backed | `placement.py:105-121` (нет токена → нет carrier), `:122-128` (нет бирера → нет carrier); `probes.py:250-251` (`if not bearer: Proof(holds=False)`) | к вендору не уходит ничего |
| Бирер собирается самим шлюзом из двух настроек | backed | `app/verification/ucaller.py:40-44`, `:47-49` | `f"{left}.{right}"` из двух стрипнутых половин |
| Любая отсутствующая половина = учётного нет вовсе | backed | `ucaller.py:42-43` (`if not left or not right: return None`) | дизъюнкция, а не конъюнкция — укус №3 в `bite-ucaller.sh` бьёт сюда |
| Пропущенный за отсутствие учётного рунг поднимает алерт на стоковой конфигурации, лестница идёт дальше | backed (**аннотация говорит «unbacked»**) | `ladder.py:281-291`, `:77` (`ABSENT` в `_ADVANCING`), `settings_store.py:79` (`notify_routing_errors=True`) | см. находку выше |
| Лестница, где пропущены все рунги, валит верификацию с причиной, называющей их, и не падает на `sms_out` | backed (**аннотация говорит «unbacked»**) | `ladder.py:265-267`, `:308-313` | причина перечисляет `route outcome` по каждому рунгу |
| Аннотация: `captures/ucaller-reference-2026-09-22.md` | backed | файл в `captures/` | ссылка на источник пары существует |
| Аннотация: `tg_gateway_token` объявлен `is_secret` в `settings_store.py` | backed | `:167` | — |
| Аннотация: `_settings_view_rows` рисует `configured`/`not set` без значения и без `value=` | backed | `admin/router.py:522-535` | — |
| Аннотация: `tests/test_vendor_credentials.py` в обеих локалях | backed | `:29-33` (`_SAYS_CONFIGURED`/`_SAYS_NOT_SET` для `ru` и `en`), `:80`, `:96` | страница читается дважды |
| Аннотация: `bite-credentials.sh`, четыре красных по трём слоям | backed | файл существует; **четыре** якоря найдены по одному: объявление (`settings_store.py`), вид (`admin/router.py` ×2), страница (`settings.html`) | — |
| Аннотация: сторож перечисляет учётные по ФОРМЕ ключа | backed | `tests/test_vendor_credentials.py:27,50-51` | `_CREDENTIAL_SUFFIXES = ("_token","_key","_secret","_password")` |
| Аннотация: средняя половина — `tests/test_credentials_do_not_live_in_the_environment.py` | backed | файл, 6 функций, зелёные | прецедент утверждён на заголовке `Authorization`, не на атрибуте store (`:110`, `:154`) |
| Аннотация: «**seven mutations**» за средовую половину | **unbacked** | укуса нет ни в заявке, ни где-либо в репозитории | см. находку выше |
| Аннотация: `admin_password` — белый список из одного | backed | `tests/…:253-254,280-285` | и обратное утверждение (поле исчезло → сторож неверен) тоже стоит |
| Аннотация: `ucaller_key` (секрет) и `ucaller_service_id` объявлены | backed | `settings_store.py:218`, `:225` | — |
| Аннотация: `tests/test_ucaller_credentials.py` и `bite-ucaller.sh`, восемь мутаций поимённо | backed | 6 тестов зелёные; **восемь** якорей найдены по одному (пять в `ucaller.py`, три в `settings_store.py`) | названия мутаций совпадают с перечнем в аннотации |
| Аннотация: ⚠️ «Nothing in production reads the bearer yet», «`flash_call` has no probe registered» | **contradicted** | `probes.py:78`, `api/router.py:94`, `placement.py:122-128` | см. находку выше |

⚠️ **Зависит от прочтения, не убиваю:** «each SHALL be its own setting marked secret» при
буквальном чтении покрывает обе половины пары uCaller, а `ucaller_service_id` объявлен
`is_secret=False` (`settings_store.py:225`) — его значение рисуется на странице настроек
обычным полем, и сторож `_credential_keys()` его не видит (суффикс `_service_id` не в наборе).
Сама спека, однако, называет секретной только половину-ключ («a per-service **secret** key
and a service id») и в аннотации прямо описывает перечисление по форме имени, куда
`_service_id` не попадает. То есть это сознательное прочтение, а не промах, — засчитываю
backed и отмечаю здесь.

---

## Требование 3 (строки 289–349): «An unknown operator does not block, delay or fail the attempt»

**Аннотации `[backed · …]` у требования нет — стоит `[normative · evidence: …]`, то есть
основание не оговорено как проверенное. Проверял как заявленное полностью.**

**Исход: backed с одним contradicted и одним unbacked.**

| Утверждение | Исход | Доказательство | Что проверено |
|---|---|---|---|
| Поиск оператора остаётся обогащением; `record_operator` не валит отправку | backed | `app/lookup/operator.py:23-45` | все ветви возвращают `None`-исход, ни одного `raise` |
| Ничто не задерживается/держится/валится из-за **неизвестного** оператора | backed | `manager.py:610-622` (бюджет `operator_lookup_bound`, истёк → `None`) | таймаут абсорбирован, сообщение идёт дальше |
| …из-за **протухшего** оператора | **contradicted** | `api/router.py:182` + `operator.py:35-40` | см. находку №1 |
| Неизвестный оператор берёт запись `?`, не `*` | backed | `rule.py:222-227`; `manager.py:692-695`; `api/router.py:303-307` | пустой ключ идёт только в `UNKNOWN` |
| Эта запись — часть данных правила и может быть выставлена в отказ | backed | `rule.py:57`, `:114-116`; `tests/test_routing_rule.py:131` | — |
| Случай записывается как «поехало без известного оператора» | **unbacked** на платных рунгах | `migrate.py:478-479`, `queries.py:1850-1866`, `manager.py:721,749`, `sms_carrier.py:85` — только `messages`; `verification_rungs`/`verifications` оператора не держат | см. находку №5 |
| Верификация разрешает оператора синхронно в ограниченное время перед ответом | backed | `api/router.py:182`; граница — `voxlink_timeout` (`settings_store.py:47`, 5,0 с) внутри `httpx.AsyncClient(timeout=…)` (`voxlink.py:49`) | граница есть, но это таймаут HTTP-клиента, а не маршрутный бюджет |
| …и не отвечает молча маршрутом по умолчанию, когда не смогла | backed | `api/router.py:306` → `rule.route_for(None)` → `?` | `*` в этом случае недостижим |
| Ответ приложения (`/sms/send`) НЕ ждёт поиска | backed | `api/router.py:32-45` (`_spawn_lookup`, `create_task`), сторож `tests/test_send_path_operator_lookup.py:409` | — |
| Путь отправки МОЖЕТ разрешать под собственным коротким бюджетом; истечение = случай «неизвестен» | backed | `manager.py:583-623`; `settings_store.py:308` | `asyncio.wait_for(record_operator(...), timeout=bound)` |
| Бюджет тратится только там, где кэш не держит оператора вовсе | backed **в отправителе** | `manager.py:606-608` + `_cached_operator` (`:625-637`, NULL и пустая строка считаются отсутствием) | у двери — нет, см. находку №1 |
| Ничто не валится при истечении бюджета или исключении поиска | backed | `manager.py:613-622` | обе ветви возвращают `None`, не бросают |
| Аннотация: `app/lookup/operator.py:23-45` | backed | строки совпадают с `record_operator` | — |
| Аннотация: `app/api/router.py:36` (`record_operator` spawned, not awaited) | backed | `:36` — тело `_spawn_lookup.run` | — |
| Аннотация: `app/modem/manager.py` (`_operator_for`, bounded by `operator_lookup_bound`) | backed | `:583`, `:610` | — |
| Аннотация: `app/db/migrate.py` (`messages.routed_route`, `messages.routed_operator`) | backed | `:478-479` | колонки существуют; покрытия платных рунгов не дают |
| Аннотация: `tests/test_send_path_operator_lookup.py` | backed | 11 тестов, зелёные | покрывают пустой кэш, протухшую строку (в отправителе), NULL, пустую строку, зависший поиск, бросающий поиск, час недоступности |

**Опровергающий проход.** Проверял «сторож, который не запускается»: все 11 прогнались.
Проверял «ветвь без входа»: `manager.py:619-622` (`except Exception`) достижима —
`tests/…:362` её и гоняет. Проверял, не читается ли строка с NULL-оператором как присутствие:
`_cached_operator` (`manager.py:626-637`) стрипает и возвращает `None` — правильно; у двери
(`api/router.py:306`) стрипа нет, но `fold("  ")` = `""` и результат тот же `?`.

---

## Требование 4 (строки 350–404): «A route carries only what it is capable of carrying»

**Аннотации `[backed · …]` у требования нет — стоит `[normative · evidence: …]`.
Проверял как заявленное полностью.**

**Исход: backed. Опровергающий проход дал две заметки и ни одного нарушения SHALL.**

| Утверждение | Исход | Доказательство | Что проверено |
|---|---|---|---|
| Каждый маршрут объявляет, что он способен нести | backed | `app/verification/routes.py:92-101` (`_CARRIES`) | карта объявлена рядом с именами, не в отправителе |
| `sms_out` несёт произвольный текст | backed | `routes.py:98` | `{ARBITRARY_TEXT, VERIFICATION_CODE}` |
| `flash_call` несёт код и ничего кроме | backed | `routes.py:99` | — |
| `tg_gateway` несёт код и ничего кроме | backed | `routes.py:100` | — |
| Вещь, которую назначенный маршрут нести не может, не передаётся ему, не перемаршрутизируется и не пробуется | backed | `app/modem/manager.py:755-760` — проверка первой строкой `_send_one`, до `encode_submit` (`:762`) и до модемного гейта (`:774`); `:719` — берётся только `assigned_routes[0]` | `tests/test_send_path_refuses_an_uncarryable_route.py:151` (ни одного PDU), `:388` (модем за платным рунгом вещь не подбирает) |
| Отказ называет маршрут и то, что он не может нести | backed | `manager.py:729-732` | «the route the rule names for X is Y, which cannot carry arbitrary text» |
| Отказ не тратит попытку, считается и слышен на стоке | backed | `manager.py:735-753` (`record_message_routing` → `refusals.record` → `_finally_fail(attempt=0)`); `app/verification/refusals.py:49-74`; `settings_store.py:79` | `tests/…:179` (слышен), `:200` (посчитан), `:151` (attempt=0) |
| Назначенный маршрут — первый, названный записью, и только он | backed | `manager.py:715-719` | комментарий и код совпадают; за `[tg_gateway, sms_out]` модем не подхватывает — `tests/…:388` |
| Маршрут, который шлюз не объявил способным, не несёт ничего | backed | `routes.py:138-145` (`carries` для неизвестного — `False`), `placement.py:67-73` (`places_here` — `False`), `ladder.py:281-291` (`ABSENT` + алерт) | `tests/…:478`, `:517` |
| Аннотация: `app/verification/routes.py:74-111` (`_CARRIES`, `carries`) | backed по символам, **диапазон строк не совпадает** | `_CARRIES` — `:95-101` (в диапазоне), `carries` — `:138-145` (ВНЕ диапазона) | оба символа существуют и делают названное; цитата уехала |
| Аннотация: `app/modem/manager.py:558-653` (`_refuse_what_the_rule_routes_elsewhere` и `_refuse`, зовутся в голове `_send_one` до `encode_submit` и до модемного гейта) | backed по символам и по порядку, **диапазон строк не совпадает** | фактически `:639-733` и `:735-753`, `_send_one` — `:755`, вызов — `:759` | порядок «до кодирования и до гейта» подтверждён |
| Аннотация: `app/verification/refusals.py:49` (считается и алертится на `routing`, который едет включённым) | backed | `refusals.py:49` — `record`; `:70-74` — `notify("routing", …)`; `settings_store.py:79` — `True` | — |
| Аннотация: `tests/test_send_path_refuses_an_uncarryable_route.py` | backed | 14 тестов, зелёные | — |
| Аннотация: модем ДЕЙСТВИТЕЛЬНО несёт код — `app/verification/sms_carrier.py` и `probes.py` (`_sms_out_probe`) | backed | `sms_carrier.py:68-95` (составляет текст, создаёт сообщение, пишет маршрутизацию, ставит в очередь); `probes.py:129-172` | `_sms_out_probe` спрашивает правило и отказывает, если оно не шлёт этот номер на модем |

**Опровергающий проход — две заметки, ни одна не ломает SHALL.**

1. **Ветвь без входа.** `manager.py:726-728` — `if routes.carries(assigned, routes.ARBITRARY_TEXT)`
   недостижима: единственный маршрут с `ARBITRARY_TEXT` в `_CARRIES` — `sms_out`, а он вернулся
   раньше на `:720`. Докстринг теста `tests/…:490` обещает различать
   «`tg_gateway` cannot carry arbitrary text» и «`tg_user` is not the modem», но тело теста
   вторую формулировку не проверяет — оно сравнивает «cannot carry» с «no way out». Ветвь
   становится живой в тот день, когда `_CARRIES` объявит текст ещё за одним маршрутом; сегодня
   это задел, а не дефект.
2. **Решение принимается не через `carries`.** Фактический гейт на `:720` — это
   `assigned == routes.SMS_OUT`, то есть «этот ли отправитель назван», а не «способен ли
   маршрут». Сегодня эквивалентно (`sms_out` — единственный носитель текста), и для модемного
   отправителя это верная формулировка; но карта `_CARRIES` участвует только в тексте причины и
   в дверном вопросе `api/router.py:155`.
3. **Смежная напряжённость, не моё требование:** `INCAPABLE` («this rung cannot carry *this*
   item») входит в `_ADVANCING` (`ladder.py:77`), и `sms_carrier` возвращает его при отсутствии
   шаблона (`sms_carrier.py:63-66`) — то есть вещь, которую рунг «не может нести», ПЕРЕХОДИТ на
   следующий рунг. По `_CARRIES` это не про способность маршрута (текст `sms_out` несёт), а про
   конфигурационный пробел приложения, и дверь уже отказывает, когда слов нет ни у одного
   оставшегося рунга (`api/router.py:155-177`). Оставляю как наблюдение для чекера требования о
   лестнице (строки 405+).

---

## Чего я НЕ делал

Укусы (`bite-rule.sh`, `bite-credentials.sh`, `bite-ucaller.sh`) **не гонялись**: они временно
мутируют файлы в `app/`, а по этому ворктри параллельно ходят другие читатели свипа. Вместо
прогона проверено статически, что каждый заявленный якорь существует и встречается ровно один
раз в названном файле — то есть что мутация имеет цель. Прогнаны только тесты:
`test_routing_rule.py`, `test_send_path_operator_lookup.py`,
`test_send_path_refuses_an_uncarryable_route.py`, `test_vendor_credentials.py`,
`test_ucaller_credentials.py`, `test_credentials_do_not_live_in_the_environment.py` —
**63 passed**.
