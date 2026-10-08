---
id: SG-42
title: >-
  flash_call: сверка с code-отчётом uCaller фейлит доставные звонки — отчёт
  недостоверен
status: To Do
assignee: []
created_date: '2026-10-08 15:50'
updated_date: '2026-10-08 15:50'
labels:
  - bug
  - ucaller
dependencies: []
ordinal: 42000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Причина доказана 08.10 (полная история улик — SG-29 Implementation Notes): поле code у uCaller (initCall-эхо, getInfo, ЛК) системно НЕ есть набранные цифры. На боевой базе все 6 рунг flash_call с причиной "the vendor allocated different digits" (верификации 35, 65, 66, 68, 87, 118; 01–08.10) имеют верификацию, подтверждённую НАШИМ кодом через 9–23 с после размещения (attempts=0); все 8 рунг без расхождения — истекли без подтверждения; исключений из 15 нет. Код не имел другого канала: create отвечает без кода, админка без кода (queries.verifications_for_phone), логи без кода, боевую базу никто не читал (слово владельца). Проба openspec/changes/route-sends-by-operator/captures/sg29_zero_probe.py: ведущие нули вендор не калечит (тест-номер 0427 → строка 0427 и в эхе, и в getInfo) — дело не в парсере; отчёт возвращает другие полные цифры (v35=9279, v118=5096 при подтверждении нашим кодом). Текущая ветка _digits_changed/_mismatch в app/verification/flash_carrier.py: 6 раз зафейлила доставные оплаченные звонки (0.8 ₽ каждый), разбудила оператора ложным Routing refused и позволила позднему sweep перезаписать рунг уже подтверждённой верификации (118: confirmed 16:43:06, рунг failed 16:43:12).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Рунг flash_call при расхождении отчётного code с запрошенным НЕ завершается failed и не двигает лестницу покупать код повторно: исход неизвестен с пометкой, верификация остаётся подтверждаемой человеком в пределах TTL
- [ ] #2 Поздний добор исхода (resolve_outstanding/_settle) не перезаписывает рунг верификации, уже подтверждённой нашим кодом: подтверждение сильнее отчёта вендора
- [ ] #3 Случай расхождения больше не будит оператора алертом Routing refused (тихая запись журнала или информационный уровень)
- [ ] #4 Спека phone-verification живой заявки SG-6 и доки capability отражают: поле code вендора не есть набранные цифры, сверка по нему не меняет исход рунга
- [ ] #5 Выкачено через ship-sms-gate; ближайший живой flash_call с расхождением не рождает ни failed-рунга, ни алерта (проверка владельца)
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Ворктри до первой правки (репо параллельное, .claude/worktrees/). 2. app/verification/flash_carrier.py — _mismatch: вместо Attempt(FAILED) вернуть UNRESOLVED-семантику (лестница не advance, человек подтверждает в TTL); обе точки: placed.code после initCall (~:141) и info.code после poll (~:157). 3. _settle (~:283-330): верификация confirmed → рунг carried с пометкой противоречия; расхождение без подтверждения → не failed, fail_verification за расхождение не звать. 4. Алерт из _mismatch (notify routing, текст "spending money it cannot complete") убрать или перевести в logger; будящий канал не трогать для остальных событий. 5. Тесты: tests/test_flash_call_carrier.py — переписать mismatch-кейсы (test_a_code_the_vendor_changed_fails..., test_a_code_that_changed_only_by_the_time_of_getinfo...) под новую семантику; новый кейс: sweep не перезаписывает рунг подтверждённой верификации; проверить test_the_call_outcome_that_arrives_late.py. 6. Спека: openspec/changes/route-sends-by-operator/specs/phone-verification/spec.md (~:320-326) — premise "код сверки = отчёт вендора" заменить: отчёт не авторитетен, расхождение не меняет исход; причина-улика в тексте (6/6). 7. Закрытие по docflow: критерии влить в доку capability (flash_call в backlog/docs/capabilities не описан — описать сшивку, которую трогали), bl-done.sh, коммит задача+дока+код вместе. 8. Выкат только скиллом ship-sms-gate (пуш deploy-remote = рестарт живого сервиса — слово владельца). Остановиться и вернуть вопрос: если тесты вскроют, что UNRESOLVED-семантика ломает соседние SHALL лестницы.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Замок SG-29 снят сессией Dx 08.10; сага продолжается здесь. Улики: SG-29 notes (полная хронология), captures/sg29_zero_probe.py, ЛК uCaller (сервис sms-gate 747277): v35=9279, v118=5096, v42=9965 (совпал). Побочное вне скоупа: 02-06.10 было 9 оплаченных flash_call вне правила (явный /route, верификации 44-94, все наши); операция 2.0 ₽ (рунг 55); SG-39 (просрочен с 05.10) — факты ложатся в претензию вендору.
<!-- SECTION:NOTES:END -->
