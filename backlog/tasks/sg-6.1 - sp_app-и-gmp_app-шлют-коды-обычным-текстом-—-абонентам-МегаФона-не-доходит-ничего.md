---
id: SG-6.1
title: >-
  sp_app и gmp_app шлют коды обычным текстом — абонентам МегаФона не доходит
  ничего
status: To Do
assignee: []
created_date: '2026-09-25 12:37'
updated_date: '2026-09-25 13:36'
labels:
  - routing
  - megafon
dependencies: []
parent_task_id: SG-6
ordinal: 28000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Замер 25.09.2026 по боевой базе: с 22.09 14:25 UTC правило мегафон → [tg_gateway, flash_call] отказало 53 сообщениям (sp_app 38, gmp_app 15; по суткам 8/6/25/14 — впятеро выше августовской оценки ~3,7/сут). У всех verification_id пуст: приложения шлют код через /send как обычный текст длиной 11–18 знаков, а лестница Telegram → звонок работает только для верификации, открытой через дверь. Итог: абонент МегаФона в этих приложениях не получает ни кода, ни звонка. Решение владельца 25.09: коды МегаФону — через Telegram, не пришёл — звонок; значит приложения обязаны перейти на дверь верификации. Для sp_app это пункт 3.2a заявки route-sends-by-operator (контракт разработчику); для gmp_app пункта не было — его код вне этого репо.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Контракт двери верификации с живыми примерами передан разработчику sp_app (3.2a)
- [ ] #2 gmp_app открывает код через дверь верификации, а не /send
- [ ] #3 После перехода новых строк route_refusals с route=tg_gateway от sp_app и gmp_app за сутки — 0
- [ ] #4 Верификации абонентов МегаФона от этих приложений видны в verifications и доходят по tg_gateway или flash_call
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
25.09.2026: контракт = docs/verification-api.md (уже был, 3.3/3.4 учтены). Раздел «What a deployment can carry today» сверен с продом и переписан: gateway_msisdn, ключ uCaller, callback Telegram заданы; шаблонов нет. Добавлен раздел про МегаФон. Опубликован страницей для передачи разработчику sp_app.

25.09.2026: для разработчика — короткая русская версия docs/verification-api.ru.md (72c4d91), вычитана ru-check. Владелец передаёт сам; AC#1 отмечать после передачи.
<!-- SECTION:NOTES:END -->
