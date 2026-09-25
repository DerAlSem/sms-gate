---
id: SG-29
title: >-
  uCaller initCall отказывает code 1 — звонок (flash_call) не размещается на
  проде
status: To Do
assignee: []
created_date: '2026-09-25 13:46'
labels:
  - bug
  - ucaller
dependencies: []
ordinal: 30000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
25.09.2026 16:43 MSK, платная проба 5.1 владельца (верификация 3, app test, +79851600019, route flash_call): initCall ответил HTTP 200 {error: 'Invalid request. Check the query syntax and the list of parameters used', code 1}. Списания нет (verification_rungs.id=2, cost пуст, outcome refused). Авторизация прошла (иначе code 401).

Гипотеза (НЕ проверена): справочник (openspec/changes/route-sends-by-operator/captures/ucaller-reference-2026-09-22.md §3) задаёт phone как NUMBER; адаптер (app/verification/ucaller.py:381 init_call → _call :463) шлёт POST JSON с phone СТРОКОЙ (wire_number). Живые сэмплы 1.3 снимались GET'ом (все параметры строки), так что POST+JSON initCall вживую не исполнялся ни разу до 25.09. Другие подозреваемые в том же теле: unique (UUID из idempotency_key), client (client_label), code строкой.

Разделяющая проба бесплатна: тестовый номер uCaller 79000000001 «всегда успех» — POST JSON с phone числом против строки, остальное поле за полем. Ключ — в settings боевой базы; значения не выписывать; внешний вызов с боевым ключом — с согласия владельца.

Блокирует: пробы 5.1 и 5.7 заявки route-sends-by-operator, и весь рунг flash_call для МегаФона (Telegram не дошёл → звонок не будет размещён, верификация падает с 'flash_call refused').
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Названа и доказана пробой на 79000000001 причина code 1
- [ ] #2 initCall через адаптер размещает звонок на тестовом номере
- [ ] #3 Тест фиксирует форму тела initCall, которую вендор принимает
- [ ] #4 Выкачено по ship-sms-gate; владелец повторил 5.1 на +79851600019 — confirmed
<!-- AC:END -->
