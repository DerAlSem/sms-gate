---
id: SG-36
title: 'tg_user: импорт контакта, когда ResolvePhone не находит человека с Телеграмом'
status: To Do
assignee: []
created_date: '2026-09-27 05:04'
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
- [ ] #1 Захват: для номера без Телеграма, номера со скрытым поиском и номера с открытым поиском записано, что отвечают ResolvePhone и ImportContacts (лежит в tests/ фикстурой)
- [ ] #2 Если ImportContacts находит того, кого ResolvePhone не нашёл: tg_user после пустого resolve импортирует контакт, шлёт, удаляет контакт; удаление выполняется и при ошибке отправки
- [ ] #3 Импорт считается в лимитах аккаунта и не выполняется, когда лимит исчерпан
- [ ] #4 Исходы для лестницы не меняются: пусто после импорта — miss; ошибка импорта — unavailable
<!-- AC:END -->
