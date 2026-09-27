---
id: SG-36
title: 'tg_user: импорт контакта, когда ResolvePhone не находит человека с Телеграмом'
status: Done
assignee:
  - '@S·tg-импорт-контакта'
created_date: '2026-09-27 05:04'
updated_date: '2026-09-27 05:42'
labels: []
dependencies: []
ordinal: 33000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
27.09 первая живая верификация gmp_app дала tg_user miss (ResolvePhone пуст), а владелец говорит: у человека Телеграм БЫЛ, и после добавления в контакты сообщение отправить можно. Это расходится с захватом 3.1 (app/routing/tg_user.py, докстринг «Resolution adds no contact»: ImportContacts для скрытого номера тоже пуст). Нужен новый захват и, если импорт помогает, запасной шаг: ImportContacts → отправка → DeleteContacts. Риск: массовый импорт — путь к бану аккаунта @gmplus_support; импорт обязан идти под лимиты messenger_limits. tg_user.py перенесён байт в байт с ветки feature/reach-people-in-messengers (SG-24) — правку согласовать с ней (одинаковые файлы = нет конфликтов при мерже).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Захват: для номера без Телеграма, номера со скрытым поиском и номера с открытым поиском записано, что отвечают ResolvePhone и ImportContacts (лежит в tests/ фикстурой)
- [ ] #2 Если ImportContacts находит того, кого ResolvePhone не нашёл: tg_user после пустого resolve импортирует контакт, шлёт, удаляет контакт; удаление выполняется и при ошибке отправки
- [ ] #3 Импорт считается в лимитах аккаунта и не выполняется, когда лимит исчерпан
- [ ] #4 Исходы для лестницы не меняются: пусто после импорта — miss; ошибка импорта — unavailable
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
27.09 S·tg-импорт-контакта: захват 3.1 (feature/reach-people-in-messengers, captures/kurigram-2.2.26.json, 22.09) УЖЕ содержит все три случая AC#1: открытый +798…19 — resolve и import находят; без аккаунта +790…03 — PHONE_NOT_OCCUPIED / users=0; скрытый +792…88 — PHONE_NOT_OCCUPIED / import users=0. Импорт для скрытого номера не помог. Гипотеза расхождения с владельцем: у человека поиск по номеру «Мои контакты» — ImportContacts находит, только если НАШ номер у него в контактах; владелец писал со своего личного аккаунта, который у человека в контактах, а @gmplus_support — нет. Решающая проба: ImportContacts номера из rung_ledger (miss 26.09 20:26:51) с сессии gmplus_support, затем DeleteContacts. Ждёт слова владельца.

27.09 проба (с разрешения владельца), сессия gmplus_support с Мака, копия файла сессии, удалена после: номер мисса 26.09 (+798…64) — ResolvePhone PHONE_NOT_OCCUPIED, ImportContacts users=0 imported=0 (popular_invites=1); контактов на аккаунте 0 до и 0 после. Владелец: в контактах gmplus_support никого нет; номер …9888 стоит на «только контакты». Итог: импорт находит ровно тех, кого находит resolve → шаг import→send→delete не строится, AC #2–#4 не применимы (их условие «если ImportContacts находит» ложно). Код tg_user.py не тронут — он остаётся байт в байт с веткой SG-24. Фикстура tests/fixtures/tg_contact_import.json + tests/test_tg_contact_import_capture.py (3 passed). Полный прогон: 1478 passed, 7 failed — те же 7 падают на чистом HEAD (test_alert_send_sh ×4, test_cds_attribution ×2, test_verification_contract_doc ×1), не от этой задачи. /code-review не гонялся: боевого кода в диффе нет.

Сверка с боем 27.09: rung_ledger — 27.09 04:10:29 UTC +792…9888 tg_user miss (утренний вход владельца, код ушёл SMS), 26.09 20:26:51 +798…7464 miss (другой человек, на нём проба SG-36). …9888 — тот же скрытый номер, что в захвате 3.1 (+792…88).
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Ждёт тебя: ничего по SG-36. Сделано: захват — ImportContacts с @gmplus_support не находит никого, кого не нашёл ResolvePhone (открытый/без аккаунта/два скрытых, включая живой мисс gmp_app 26.09); причина — приватность «только контакты» отвечает лишь тому, кто в контактах у человека. Шаг импорта не нужен, лестница не меняется. Фикстура и тест в tests/, в доке verification-tg-user — требование «A miss is final — no contact is imported». Найдено: 7 предсуществующих падений тестов на HEAD.
<!-- SECTION:FINAL_SUMMARY:END -->
