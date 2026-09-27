---
id: SG-38
title: >-
  Семь давно падающих тестов: alert_send.sh, cds_attribution, контракт
  верификации
status: To Do
assignee: []
created_date: '2026-09-27 06:16'
labels:
  - tests
dependencies: []
ordinal: 38000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
На HEAD (caa1a91, 27.09) полный набор: 1538 passed, 7 failed; те же 7 падали до SG-34/SG-36 — не регресс последних задач, но набор перестал быть сигналом («зелёный в прежнем объёме»). Три группы, у каждой своя причина: (1) tests/test_alert_send_sh.py ×4 — текст алерта пустой (text= пустой в curl-args), spool хранит только штамп без текста сообщения; подозрение: bash/утилиты macOS против Linux на коробке (BSD vs GNU) или сломанный скрипт; (2) tests/test_cds_attribution.py ×2 — ожидается выбор 'recency', приходит None; (3) tests/test_verification_contract_doc.py ×1 — в docs/contracts (контракт верификации) нет упоминания `gateway_msisdn` и фразы, что номер шлюза — настройка, поставляемая пустой. Для каждой группы решить: чинится код, тест или дока — и не подгонять тест под поломку.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Для каждой из трёх групп в заметках названа причина с доказательством (вывод, строка кода), а не догадка
- [ ] #2 Группа alert_send.sh: если причина — различие macOS/Linux, тест проходит на macOS И скрипт по-прежнему работает на коробке (Linux) — проверено, а не предположено
- [ ] #3 Полный набор на ворктри: 0 failed
<!-- AC:END -->
