---
id: SG-32
title: Ступень tg_user в лестнице верификации — коды ГМ+ с аккаунта @gmplus_support
status: In Progress
assignee:
  - '@S·tg-верификация'
created_date: '2026-09-25 17:05'
updated_date: '2026-09-26 05:28'
labels: []
dependencies:
  - SG-24
ordinal: 31000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Срез из ветки feature/reach-people-in-messengers (SG-24) на master по решению владельца 25.09 (после снятия flash_call, SG-31). Ветка feature/tg-user-verification от deploy-remote/master, ворктри .claude/worktrees/tg-user-verification. План и решения — SG-24 (--plan и заметки 25.09). SG-11 не блокирует: владелец принял риск аккаунта.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Код верификации приложения, в правиле которого стоит tg_user, уходит сообщением с аккаунта @gmplus_support, если номер есть в Телеграме
- [x] #2 Номер без Телеграма: ступень отвечает declined, лестница переходит к следующей ступени правила
- [x] #3 Сообщение могло дойти, но ответа нет (unanswered): лестница спускается к следующей ступени
- [x] #4 Без ключей TG_* или без файла сессии ступень не вписана: квота аккаунта не тратится, в журнале route is configured but not wired
- [x] #5 Отказ Телеграма нам (сессия, бан, флуд) — refused с громким алертом, называющим аккаунт
- [x] #6 Лимиты аккаунта (в час и на получателя) действуют и переживают рестарт процесса
- [x] #7 Первое сообщение человеку от этого аккаунта представляется (правило 5.3 ветки SG-24)
- [x] #8 Код не уходит, если верификация закончилась до отправки
- [x] #9 Путь /sms и остальные ступени верификации ведут себя как до правки: набор тестов master зелёный в прежнем объёме
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
25.09 — план среза (сессия S·tg-верификация)

Находки разведки, которых не было в хендоффе:
- Правило маршрутов верификации (`operator_routes`) — по ОПЕРАТОРУ, не по приложению; порядок предложения `verification_route_order` — глобальный. «Только ГМ+» держится картой брендов `messenger_brands` (apps → brand → tg_user account + intro), как на ветке мессенджеров (задача 2.5).
- Ступень, которую потребитель не выбрал, лестница не ходит: `ladder_from(route)` начинается с выбранной. Значит tg_user надо ПРЕДЛАГАТЬ: проба, инструкция, `PLACED_HERE`.

Шаги:
1. Перенос тем же путём и содержимым: app/routing/{__init__,classes,config,brands,introduction,rate,route,routes,tg_errors,tg_user}.py, deploy/tg-sign-in.py, kurigram в requirements, TG_* в app/config.py и .env.example. Лестница /sms (ladder, dispatch, health, login_codes) НЕ едет.
2. БД: таблицы rung_ledger, messenger_rate_claims, messenger_disclosures, messenger_suppressions и их запросы (record_rung, record_disclosure, accounts_that_have_written_to, claim_rate_allowance, settle_rate_claim, is_withheld_from_messengers) — как на ветке.
3. Настройки: messenger_brands, messenger_limits (+ валидаторы, check_every_account_is_rate_bound в set_many).
4. app/verification/tg_user_carrier.py: один TelegramUserRoute на процесс; аккаунт — из карты брендов по app_id; нет аккаунта/шаблона/представления → INCAPABLE (до раскрытия номера); подавленный номер → INCAPABLE; claim лимитов → отказ = REFUSED; код читается из стора прямо перед offer, нет кода → FAILED; accepted→CARRIED, miss→DECLINED, unavailable→REFUSED (громко, с аккаунтом), indeterminate→UNANSWERED. Журнал rung_ledger/disclosures пишется как на ветке; id в журналах — отрицательный id верификации (пространство id сообщений не пересекается).
5. placement: carriers[TG_USER] только при ключах + файле сессии аккаунта этого приложения; иначе warning `route is configured but not wired`. PLACED_HERE += TG_USER.
6. routes: _CARRIES[TG_USER], _NEEDS_OUR_WORDS += TG_USER, инструкция; probes: проба tg_user по app_id (без обращения к Телеграму).
7. ladder: WITHHELD модема — только после отказа ПЛАТНОГО вендора (решение владельца 25.09: «модем несёт»).
8. Тесты переносимые + новые на носитель/сшивку; полный набор master.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
25.09 решение владельца (вопрос в сессии): отказ tg_user (refused) НЕ придерживает sms_out — модем несёт. Правило 20.09 (WITHHELD) остаётся для платных вендоров tg_gateway/flash_call.

26.09 ревью (/code-review medium) — три находки: (1) medium — отмена снаружи внутри первого connect()/get_me() в app/routing/tg_user.py обходит очистку (except Exception не видит CancelledError), клиент держит файл сессии → database is locked до рестарта. Исправлено в носителе: offer под shield, лестница перестаёт ждать, но не отменяет. В самом tg_user.py НЕ правлено (перенос байт в байт) — ТА ЖЕ ДЫРА живёт на ветке мессенджеров, её лестница тоже зовёт wait_for; чинить там (SG-24). (2) low — _budget() читает store.route_deadlines_parsed, настройки на master нет, бюджет всегда 8−1.5 с; при shield безвредно, настройка приедет с веткой мессенджеров. (3) low — алерт на отказ собственного лимита винил Телеграм; разведено. Набор: 1459 зелёных, 7 известных падений базы. AC #1 проверен только фейковым клиентом — живьём после выката.
<!-- SECTION:NOTES:END -->
