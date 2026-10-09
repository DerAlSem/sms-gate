
<!-- BACKLOG.MD GUIDELINES START -->
<!-- backlog.md-instructions-version: 1.52.0 -->
<CRITICAL_INSTRUCTION>

## Backlog.md Workflow

This project uses Backlog.md for task and project management.

**At the beginning of each conversation in this project, run `backlog instructions overview` before answering or taking action. Re-read it only if you have not read it yet in the current conversation.**

Use the overview to decide whether to search, read, create, or update Backlog tasks.

Before task lifecycle actions, read the matching detailed guide:
- `backlog instructions task-creation` before creating or splitting tasks
- `backlog instructions task-execution` before planning, changing status or assignee, adding a plan or implementation notes, or implementing task work
- `backlog instructions task-finalization` before checking acceptance criteria, writing final summaries, or moving tasks to terminal statuses

Use `backlog <command> --help` before running unfamiliar commands. Help shows options, fields, and examples.

Do not edit Backlog task, draft, document, decision, or milestone markdown files directly. Use the `backlog` CLI so metadata, relationships, and history stay consistent.

</CRITICAL_INSTRUCTION>
<!-- BACKLOG.MD GUIDELINES END -->

## sms-gate

Задачи этого репо ведутся через docflow; openspec выведен из обращения
25.09.2026. Как устроено — `backlog/docs/capabilities/`; строки отложки
`.claude/waiting` переехали задачами в колонку Backlog.

В `openspec/changes/` остались каталоги ТОЛЬКО живых заявок (SG-1…8): там
рабочие улики, на которые ссылаются задачи и ветки ворктри, а тесты читают
`route-sends-by-operator/captures/`. Каталог уходит вместе с закрытием своей
задачи; фикстуры — в `tests/` до удаления их каталога.

Стек, гочи и выкат — `AGENTS.md` (FastAPI + SQLite + AT-модем, systemd на
одном хосте); выкат только через скилл `ship-sms-gate`.

**Репозиторий работается параллельно:** живые ворктри в `.claude/worktrees/`
(мессенджеры, телеграм-рунг, обратный код, голосовой маршрут) — ворктри до
первой правки.

**Автономно нельзя:** push в `deploy-remote` — это выкат на боевой хост с
живым трафиком; любые действия на ВДС — только по слову владельца.
