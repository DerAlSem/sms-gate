---
id: SG-37
title: Посчитать исходы tg_user у gmp_app после недели на бою
status: Backlog
assignee: []
created_date: '2026-09-27 05:58'
due_date: '2026-10-04'
labels:
  - routing
  - tg_user
dependencies: []
ordinal: 34000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Не сейчас: исходов пока три (26–27.09: 1 accepted, 2 miss — оба номера скрыты от поиска по номеру или без Телеграма). Нужна неделя живого трафика. 04.10 посчитать по rung_ledger (route='tg_user', brand='gmplus') доли accepted / miss / unavailable / indeterminate и вывести, окупает ли ступень себя: если miss подавляющий — ступень лишь тратит квоту аккаунта и секунды человека перед SMS. Номера в задачу не выписывать, только доли. Контекст: SG-32, SG-36 (импорт контакта miss не лечит).
<!-- SECTION:DESCRIPTION:END -->
