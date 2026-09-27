---
id: SG-38
title: >-
  Семь давно падающих тестов: alert_send.sh, cds_attribution, контракт
  верификации
status: Done
assignee:
  - '@claude'
created_date: '2026-09-27 06:16'
updated_date: '2026-09-27 06:20'
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
- [x] #1 Для каждой из трёх групп в заметках названа причина с доказательством (вывод, строка кода), а не догадка
- [x] #2 Группа alert_send.sh: если причина — различие macOS/Linux, тест проходит на macOS И скрипт по-прежнему работает на коробке (Linux) — проверено, а не предположено
- [x] #3 Полный набор на ворктри: 0 failed
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. alert-send.sh: воспроизвести encode на BSD sed, заменить склейку на переносимую, сверить с GNU sed/mawk в контейнере. 2. cds_attribution: сверить жёсткий sent_at с окном 168 ч, сделать время относительным. 3. verification-api.md: найти коммит, выбросивший абзац про gateway_msisdn, вернуть согласованно с таблицей 25.09. 4. Полный набор.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Группа 1 (alert_send ×4). Причина: deploy/alert-send.sh encode() склеивал строки через sed ':a;N;$!ba'. BSD sed на однострочном входе выполняет N на последней строке и выходит БЕЗ печати (доказательство: printf 'one line' | sed ... | od -c — пусто на macOS; 'a\nb' — 'a\\nb'). GNU sed печатает. Итог на macOS — spool со штампом без текста, text= пустой. Фикс: склейка через awk (NR>1 printf '\\n'). Сверка: старый и новый encode на debian:12 и ubuntu:24.04 (GNU sed 4.9, mawk 1.3.4, /bin/sh=dash) дают идентичный вывод на 7 входах (одна строка, многострочный, обратный слэш, пустая строка внутри, хвостовые переводы, пустой); tests/test_alert_send_sh.py 10/10 в python:3.12-slim (Linux) и на macOS. На самой коробке не прогонялось.
Группа 2 (cds_attribution ×2). Причина: тесты (cc90af0, 03.09) ставили sent_at='2026-09-02 11:00:00' жёстко; окно delivery_report_max_age_hours=168 ч (app/settings_store.py:376), отсечка now-window (app/modem/attribution.py:124) — с 09.09 обе строки OUTSIDE_WINDOW, решение None, лог 'the only matches fell outside the delivery-report window'. Код верен, тест зависел от календаря. Фикс: sent_at = datetime('now','-600 seconds') одинаково обеим строкам (ничья сохранена). test_attribution_chain.py с такой же датой устойчив — там now=NOW зафиксирован.
Группа 3 (контракт ×1). Причина: e351e7f (25.09) переписал таблицу маршрутов и выбросил абзац про gateway_msisdn/ships blank. Факт по-прежнему верен (Spec gateway_msisdn default '' — app/settings_store.py:159), а дока без него оставляет отсутствие цифр необъяснённым — неверна дока. Фикс: абзац возвращён в формулировке под состояние 25.09 (на проде задан, читать из number).
Полный набор macOS: 1545 passed, 0 failed.

Дока не менялась: поведение системы не менялось: вывод alert-send.sh на Linux прежний, фикс cds — только тест, verification-api.md — внешний контракт, не capability-дока; ни одна capability-дока не описывает alert-send
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Ждёт тебя: выкат не делался. alert-send.sh на коробке — это копия /usr/local/sbin/sms-gate-alert, её ставит deploy/install-units.sh; правка доедет, только если выкат его перезапустит. НЕ проверено на самой коробке: сверка шла в контейнерах ubuntu:24.04/debian:12 (GNU sed 4.9, mawk, dash), вывод encode старого и нового идентичен — риск только в экзотическом awk на коробке.
Сделано: (1) alert-send.sh — склейка строк в encode() через awk вместо sed ':a;N;$!ba', который на BSD sed съедал однострочный алерт; поведение на Linux байт в байт прежнее. (2) test_cds_attribution — два теста зависели от календаря (жёсткий sent_at 02.09 выпал из окна 168 ч 09.09); время сделано относительным, код не менялся. (3) docs/verification-api.md — вернул абзац про gateway_msisdn (ships blank), выпавший в e351e7f, под состояние 25.09.
Проверено: полный набор на macOS 1545 passed / 0 failed; tests/test_alert_send_sh.py 10/10 в Linux-контейнере; /code-review low — замечаний нет.
Найдено: с одинаковой жёсткой датой test_attribution_chain.py устойчив (now зафиксирован) — других мин того же рода в наборе поиск по '2026-09-02 11:00:00' не нашёл.
<!-- SECTION:FINAL_SUMMARY:END -->
