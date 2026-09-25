---
id: SG-29
title: >-
  uCaller initCall отказывает code 1 — звонок (flash_call) не размещается на
  проде
status: In Progress
assignee:
  - '@worktree-tg-gateway-rung'
created_date: '2026-09-25 13:46'
updated_date: '2026-09-25 14:41'
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
- [x] #1 Названа и доказана пробой на 79000000001 причина code 1
- [ ] #2 initCall через адаптер размещает звонок на тестовом номере
- [x] #3 Тест фиксирует форму тела initCall, которую вендор принимает
- [ ] #4 Выкачено по ship-sms-gate; владелец повторил 5.1 на +79851600019 — confirmed
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
25.09 сессия Dx: тело initCall из адаптера = {phone: str (wire_number), code: str, unique: UUIDv4 из idempotency_key(rung_id)}; client НЕ уходит — client_label нигде не передаётся (flash_carrier.py:76 default ''). Значит подозреваемых три: phone строкой (главный), code строкой, unique. Справочник §3: phone NUMBER, code number|string. Разделяющая проба спроектирована: 5 вызовов на 79000000001 c паузой 17с — A тело адаптера как есть; B phone int; C phone int+code int; D phone str без unique; E GET-контроль формой 1.3. Скрипт на stdlib, ключ из settings (ucaller_key, ucaller_service_id) без печати. Запись скрипта, читающего боевой ключ, заблокирована классификатором авто-режима [Production Reads] — нужно слово владельца. Замок снят не был.

25.09 17:0x MSK проба sg29_probe.py на derserver, тестовый 79000000001: A (адаптер как есть, phone str) → code 1; B (phone int, code str, unique) → status true ucaller_id=57288106; C (phone int, code int) → true 57288114; D (phone str, без unique) → code 1; E (GET-контроль) → true 57288122. Вывод: причина code 1 — phone строкой в JSON; code строкой и unique ни при чём.

Фикс: ucaller.wire_number возвращает int → phone уходит JSON-числом; code остаётся строкой (ведущие нули). Тесты: test_the_number_goes_to_the_vendor_as_a_json_number (был красным до фикса), test_the_code_stays_a_string_so_leading_zeros_survive. Полный набор: 1373 passed, 7 failed — те же 7 падают на чистом HEAD df8c88e (alert_send_sh ×4, cds_attribution ×2, verification_contract_doc ×1), к SG-29 не относятся. AC2 НЕ проверен через сам адаптер: проба B доказала форму тела, но код адаптера на хосте ещё старый — проверится выкатом.
<!-- SECTION:NOTES:END -->
