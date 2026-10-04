---
id: SG-40
title: >-
  Имя wwan0 не закреплено: релиз-апгрейд до 26.04 переименовал модем, Билайн
  лежал
status: To Do
assignee: []
created_date: '2026-10-04 18:22'
updated_date: '2026-10-04 18:35'
labels:
  - wwan
dependencies: []
ordinal: 40000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
04.10.2026 (найдено из turbo01, TB-49): после do-release-upgrade derserver до Ubuntu 26.04 systemd назвал модем Quectel EM06 wwp0s20f0u4i4 вместо wwan0. wwan-backup: «wwan0 not present — netdev has not reappeared?», юнит упал; второй запуск ушёл в ветку «another wwan-backup run holds the lock» и стал active без сессии; wwan-watchdog inactive dead. Агент харнесса derserver-beeline и замер абонентского плеча turbo01 (HARNESS_CONSUMER_LEGS …/wwan0) мерили мёртвую линию. Вручную починено: /etc/systemd/network/10-wwan0.link ([Match] Driver=qmi_wwan, [Link] Name=wwan0) + ip link set … name wwan0 + restart wwan-backup → wwan0 UP 100.127.197.90/30. Файл поставлен руками и в deploy/ не входит — следующая переустановка повторит аварию. Отдельно разобрать: при упавшем watchdog уступка блокировки оставляет wwan-backup зелёным (active) без сессии — по замыслу строки 472–481 сессию держит watchdog, а в этот раз он не держал ничего.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Закрепление имени wwan0 (.link по драйверу qmi_wwan) ставится штатным deploy/install-units.sh и описано в deploy/wwan-backup/README.md
- [x] #2 Отсутствие wwan0 видно как отказ в status/алерте с подсказкой про имя интерфейса, а не только строкой в журнале
- [x] #3 Решено и записано, может ли wwan-backup стоять active, уступив блокировку, когда watchdog сессию не держит
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
AC3 решено: wwan-backup может стоять active, уступив блокировку, только пока интерфейс есть; без него юнит падает. Тесты tests/test_wwan_backup.sh (docker debian, 36 проверок): новые красные на старом скрипте, зелёные на новом. Руками на ВДС НЕ делалось: install-units.sh в /usr/local/sbin обновляется вручную (root), .link там уже стоит.

AC1 не отмечен: install-units.sh на хосте не прогонялся (пути /opt/sms-gate, root). Проверка — при выкате: после установки cmp /etc/systemd/network/10-wwan0.link с репо. Копия install-units.sh в /usr/local/sbin обновляется вручную.

Выкат 04.10.2026 21:34 MSK, 952cbd2 (fast-forward с 736cd08), бэкап sms.db.pre-sg40-* сверен 2819=2819, очередь была пуста, NRestarts=0, /admin/stats 401, ошибок в журнале 0. Скрипт /usr/local/sbin/wwan-backup обновлён post-receive. Проверено на коробке: IFACE=wwan-nope wwan-backup status печатает >>> … qmi_wwan created: wwan0 <<<. НЕ доделано: хост-копия /usr/local/sbin/sms-gate-install-units от 01.08 старая (root) — .link через неё не ставится, пока владелец не обновит её с sudo.
<!-- SECTION:NOTES:END -->
