---
id: SG-30
title: >-
  Дверь верификации предлагает sms_out приложению без шаблона — маршрут, который
  гарантированно упадёт
status: To Do
assignee: []
created_date: '2026-09-25 13:55'
labels:
  - bug
  - verification
dependencies: []
ordinal: 31000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
25.09.2026, проба 5.2: POST /verifications для app test без шаблона вернул в routes sms_out; выбор кончился 'sms_out incapable' (верификация 4, verification_rungs.id=3). Проверка 4.47 (app/api/router.py, create_verification) отказывает, только если без шаблона не несёт НИ ОДИН рунг; по отдельности sms_out из предложения не вычеркнут. Приложение показывает человеку маршрут, который не может сработать.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Приложению без шаблона sms_out не предлагается ни при создании, ни в списке оставшихся после отказа (GET /verifications/{id})
- [ ] #2 Приложению с шаблоном sms_out предлагается как прежде
<!-- AC:END -->
