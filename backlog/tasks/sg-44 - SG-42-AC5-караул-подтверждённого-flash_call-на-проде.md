---
id: SG-44
title: 'SG-42 AC#5: караул подтверждённого flash_call на проде'
status: Backlog
assignee: []
created_date: '2026-10-08 16:43'
due_date: '2026-10-22'
labels: []
dependencies: []
ordinal: 44000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Не сейчас: событие внеплановое — первый после выката 08.10 19:39 MSK подтверждённый flash_call. Проба в описании караулит журнал боевого хоста; созревшая строка — «settled as carried by a confirmation of ours» (именно она доказывает AC#5: подтверждённая верификация, добор записал rung carried). При созревании: сверить рунг в базе (sqlite3 -readonly /opt/sms-gate/data/sms.db: select outcome, reason from verification_rungs where route='flash_call' order by id desc limit 3 — ожидается carried с confirmation в reason), убедиться в отсутствии алерта Routing refused, отметить AC#5 в SG-42 и закрыть её через bl-done.sh, эту задачу закрыть вместе с ней. Контрольный негатив: строка «dialled digits other than the ones requested» в журнале после выката — либо живое расхождение эха (тогда SG-43 и разбор), либо регресс — разбирать сразу, не ждать срока. Команды на коробке — короткими строками, см. глобальный CLAUDE.md.

```when
match: settled as carried by a confirmation
---
ssh -o BatchMode=yes -p 30022 home.deralsem.ru 'journalctl -u sms-gate --since "-7 days" --no-pager | grep -m1 "settled as carried by a confirmation"'
```
<!-- SECTION:DESCRIPTION:END -->
