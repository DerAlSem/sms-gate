---
id: SG-34
title: Шаблон кода верификации на пару приложение+ступень; в SMS код прописью
status: In Progress
assignee:
  - '@S·tg-верификация'
created_date: '2026-09-26 15:48'
updated_date: '2026-09-27 04:08'
labels: []
dependencies: []
ordinal: 32000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Решение владельца 26.09 (сессия S·tg-верификация): одного шаблона на приложение мало — в Телеграме и в SMS нужен разный текст, а в SMS код идёт прописью заглавными («ОДИН ДВА ТРИ ЧЕТЫРЕ»), не цифрами. Сейчас verification_templates — список {app_id, template}, читают его sms_out (sms_carrier) и tg_user (tg_user_carrier); tg_gateway и flash_call нашего текста не несут. Форма (согласована): необязательное поле route в записи; запись без route — запасная для всех ступеней приложения; новая подстановка {code_words}. Рядом: SG-30 (проба sms_out по шаблону — должна читать шаблон ступени).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Запись verification_templates может нести route; для ступени берётся запись (app_id, route), иначе запись приложения без route, иначе шаблона нет
- [x] #2 Подстановка {code_words} даёт код прописью заглавными через пробел: 1204 → «ОДИН ДВА НОЛЬ ЧЕТЫРЕ»; в шаблоне ровно одна подстановка — {code} или {code_words}
- [x] #3 При сохранении отказ: две записи на одну пару (app_id, route), неизвестный route, ноль или две подстановки
- [x] #4 sms_out и tg_user шлют текст своего шаблона; проба sms_out и отказ no_template читают шаблон ступени sms_out
- [x] #5 Нынешние записи без route работают как раньше; набор тестов зелёный в прежнем объёме
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Сделано: template.py — ключ (app_id, route), запасная запись без route, {code_words} (spell: ОДИН ДВА НОЛЬ ЧЕТЫРЕ), отказ при сохранении: дубль пары, route вне WORDED_ROUTES (sms_out, tg_user), 0 или 2 подстановки. Попутно: «{ code }» с пробелами раньше проходило сохранение, но не подставлялось — теперь отказ. Читатели: sms_carrier → for_app(app, SMS_OUT), tg_user_carrier и проба tg_user → TG_USER, отказ no_template в router — по шаблону каждой предложенной ступени. AC4 уточнён: пробы sms_out по шаблону нет (это SG-30), проверяется отказ no_template. Подсказка настройки в админке обновлена. Набор: 1475 зелёных (+14), те же 7 известных падений. Дока: doc-8, требование Each worded rung.

27.09: GM+ ходит в дверь; первое SMS ушло общим шаблоном цифрами (68 знаков) — записи sms_out с {code_words} в verification_templates на проде ещё нет. Закрытие ждёт её и первого SMS прописью.
<!-- SECTION:NOTES:END -->
