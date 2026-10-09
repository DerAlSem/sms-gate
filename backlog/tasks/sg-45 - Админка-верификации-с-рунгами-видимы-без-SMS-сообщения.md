---
id: SG-45
title: 'Админка: верификации с рунгами видимы без SMS-сообщения'
status: Done
assignee:
  - '@sg45-admin-verifications'
created_date: '2026-10-09 11:14'
updated_date: '2026-10-09 11:52'
labels: []
dependencies: []
ordinal: 45000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Владелец 09.10: uCaller-авторизация 57415246 (flash_call, верификация 127, рунг 132: carried, 0.8 ₽) не видна в истории админки, потому что страница /admin/messages списком держит СМС-сообщения (2883/2884 — delivered-СМС), а верификации с рунгами подгружаются только раскрытием под СМС-кой того же номера (app/admin/router.py:138-151, verifications_for_phone от open_phone сообщения). flash_call сообщений не создаёт — значит, сшивка невидима ни при каком клике. Локация правки: новый маршрут/секция в app/admin/router.py + шаблон; данные есть — queries.verification_rungs и верификации уже выбраны.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 На странице истории админки видна верификация flash_call без единого SMS-сообщения: список или секция верификаций с маршрутом, исходом, vendor_ref (авторизацией uCaller), стоимостью и временем
- [x] #2 Раскрытие верификации показывает её рунги: маршрут, исход, reason, vendor_ref, cost
- [x] #3 Существующая страница сообщений и раскрытие верификаций под сообщением не сломаны (полный набор зелёный)
- [x] #4 Верификации ЛЮБЫХ маршрутов видимы одинаково — flash_call, tg_user, sms_out, call_in/sms_in — независимо от того, создаёт ли маршрут сообщения: сшивка с рунгами, vendor_ref и стоимостью видна в админке всегда
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. queries.py: list_verifications_page + count_verifications_page — колонки перечислены (без code), фильтры период+телефон, newest first с тай-брейком по id. 2. router.py: GET /admin/verifications (period, phone, page), рунги одной выборкой rungs_for_verifications. 3. Шаблоны: таблицу верификаций из messages.html вынести в include, новая verifications.html с колонкой Phone; вкладка нава после SMS. 4. i18n: новые строки в ru/en .po. 5. Тесты: flash_call без единого сообщения видна, все маршруты одинаково, код не доходит до страницы и до строки, пустой список рендерится. 6. Полный набор + скриншот рендера; задача, дока capability и код — одним коммитом.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Владелец 09.10: «надо сделать», расширил на все маршруты — «если шлём в телеграм или как-то ещё — тоже надо, чтобы было видно».

Реализовано в ворктри sg45-admin-verifications (ветка worktree-sg45-admin-verifications): queries list/count_verifications_page (колонки перечислены, code не выбирается; период+телефон, тай-брейк по id), GET /admin/verifications, общая таблица _verifications_table.html (messages.html подключает её же без колонки Phone), вкладка нава «Верификации» после СМС, msgid Verifications в ru/en .po. Тесты: tests/test_admin_verifications_page.py — 6 штук. Полный набор 1557 passed (база 1551). Рендер проверен скриншотами (десктоп+мобайл, обе страницы): рунги видны всегда без клика — «раскрытие» AC#2 реализовано как надмножество (строки рунгов инлайн); маршруты call_in/sms_in появятся с сестринской веткой verify-by-inbound-contact — запрос и шаблон не фильтруют по списку маршрутов, видимость по построению.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Ждёт тебя: выкат на прод (сам не катал — ship-sms-gate по слову); вето на два решения формы — рунги всегда инлайн без клика (надмножество AC#2 «раскрытие») и вкладка «Верификации» сразу после СМС; решение по домеровому дефекту: ru-каталог «%(count)s records» без форм множественного («1 записей» на пяти страницах, SG-45 не вводил). Сделано: страница /admin/verifications — список всех верификаций с номером, статусом, маршрутом, рунгами (исход, reason, vendor_ref, стоимость, возврат), фильтры период+телефон, пейджер; таблица общая с messages (include, там без колонки телефона); колонки без code из одного кортежа; вкладка нава; i18n ru/en + pot по доке. Проверено: тесты tests/test_admin_verifications_page.py (flash_call без единого сообщения, все маршруты, код не на экране и не в строке, фильтры/период), полный набор 1557 passed (база 1551), рендер скриншотами десктоп+мобайл обеих страниц, colspan-баг из ревью пойман парсером отданного HTML (покрытие 11=11). Найдено ревью: 5 замечаний, все закрыты (colspan, .status-confirmed, pot, _pager.html, единый кортеж колонок).
<!-- SECTION:FINAL_SUMMARY:END -->
