---
id: SG-8
title: 'Дозакрыть: watch-the-voice-route'
status: To Do
assignee: []
created_date: '2026-09-25 11:59'
labels:
  - migrated
dependencies: []
references:
  - openspec/changes/watch-the-voice-route
ordinal: 8000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
## Why

The owner stated the purpose on 2026-09-18: *"имс нам нужен для получения звонков на модем
и авторизации пользователей, за ним надо следить"*. IMS is what makes the module reachable
for an incoming voice call, an incoming voice call is a way to authorise a person, and
nothing in this gateway watches it.

**The voice route exists, and that is new.** On 2026-09-18 the live `EP06-E`
(`EP06ELAR03A08M4G`) had IMS switched off — `+QCFG: "ims",0,0`. After `AT+QCFG="ims",1`
and `AT+CFUN=1,1` it read `+QCFG: "ims",1,1` — the second digit is the network's answer,
and Билайн admits this module — and an incoming call to the SIM landed: fifteen `RING` /
`+CLIP` pairs in the gateway's journal, carrying the caller's number. The same call to the
same modem had previously left not one line anywhere.

That falsifies one sentence elsewhere, and it is worth stating exactly which.
`verify-by-inbound-code`'s proposal says *"The modem in service cannot supply the second —
verified 07.09.2026, a call to its SIM is silence and disconnect"*. The measurement was
honest and the conclusion drawn from it was not: a call to this SIM is silence **with IMS
off**, and rings **with IMS on**. What that reopens is narrow — a subscriber calling our SIM
and being identified by `+CLIP`, the same direction-reversal that change already builds on
for SMS. It does **not** reopen the vendor flash call: that scheme puts the code in the last
four digits of the *calling* number and needs a pool of numbers to dial from, which one SIM
cannot supply at any IMS setting. The routing decision of 2026-09-08 stands on grounds this
change does not touch.

**And the setting is invisible.** Three separate reasons:

- **Reading it costs an outage.** The command port is held by `sms-gate`, so asking the
  modem anything means stopping the service. The owner's `/tmp/ims_set.py` does exactly
  that. This gateway carries live customer traffic — a message was sent and delivered at
  15:07 on the day of the measurement — so the act of measuring is the outage it would be
  measuring for.
- **Nothing asks.** `_DIAG_QUERIES` (`app/modem/manager.py:129-157`) has no IMS row at all.
  What it does have is two rows that cannot answer on this firmware: `AT+CIREG?` and
  `AT+QCFG="servicedomain"` are both refused. Quectel confirmed in writing on 2026-09-18
  that the commands are absent from this build and that IMS state is read with
  `AT+QCFG="ims"`. `ERROR` there is an empty reading, not a negative one — a three-day
  verdict of "this module has no voice path" was built on reading it as negative.
- **A page that is always partly red trains its reader to ignore red.** Those two rows
  render in the error style on every visit to `/admin/modem`, as does `AT+CLIP?`, which
  never answers — measured: given eight seconds it spent all eight and still did not reply,
  which is why it is back on the two-second budget (`app/modem/manager.py:139-147`). Three
  of fourteen rows are permanently red on a healthy modem.

**The evidence an alert carries is gathered at the worst possible moment.**
`_alert_observations` (`app/modem/manager.py:1162`) runs the entire fourteen-command sweep
to print the four readings `summarise_for_alert` hardcodes (`app/modem/diag.py:158-188`). It
runs on the alert path, holding the command port while the modem is by definition already
misbehaving, and three of those fourteen commands cannot answer. Adding an IMS row to that
sweep would make an incident longer, which is why the split belongs in this change rather
than after it.

## What Changes

- **IMS is read as part of the ordinary read-only sweep**, through the command port's
  existing locking, with the gateway running. Two facts, kept apart: whether IMS is enabled
  on the module, and whether the network has admitted it.
- **IMS is watched rather than displayed.** Losing the network's admission means the
  authorisation-by-call route is gone, and an operator learns it from an alert instead of
  from opening a page. Edge-triggered, as the link alert already is, with a notification
  when it returns.
- **Only the network's half is gated on registration.** Measured on 2026-09-18: after
  `AT+CFUN=1,1` the module was outside the network for about three minutes, and the second
  digit reads zero throughout — so an ungated watcher would announce a lost voice route
  after every modem reset. The module's own setting is not gated: that digit does not depend
  on the radio, and the state that clears it happens while the module is rebooting.
- **A route already lost at startup is an episode.** Episode state dies with the process,
  and the process ends itself on the ladder's top rung and on every deploy. Without this the
  gateway says nothing about exactly the condition it was built to find.
- **Watching survives the watchdog's switch**, which governs remedies rather than
  observation — the coupling this capability's neighbour already refused once for the link.
- **`ERROR`, silence, a fault and a negative answer stop rendering alike.** Four outcomes,
  decided where the modem's response is still in hand. The page reports what the modem did,
  not why it did it: a SIM that has failed also refuses its command, and that row stays red.
- **The alert path reads only what the alert reports**, from one declaration, so the page's
  sweep can grow without lengthening an incident.

## Non-goals

- **Nothing consumes `RING` or `+CLIP`.** They reach `logger.info("Unhandled URC: %r")`
  (`app/modem/manager.py:762`) and stop there. Turning an incoming call into a verification
  is a change of its own, under the new capability this one opens.
- **The gateway does not switch IMS on, and does not re-arm it.** The setting takes effect
  only after `AT+CFUN=1,1`, and an init sequence that reboots the module would turn every
  reconnect into an outage, on a gateway whose `modem-link` spec is built around
  reconnecting without one. This change watches; a human acts.
- **No opinion on the `call` / `flash_call` naming** contested between
  `route-sends-by-operator` and `verify-by-inbound-code` task 1.4, and none on the routing
  decision of 2026-09-08.
- **`AT+CLIP?` is not made to answer.** Whether the network provisions caller ID is now
  known positively from traffic — the observed `+CLIP` URCs carried the caller's number —
  so the query that never answers is no longer the only way to learn it.

## Capabilities

### New Capabilities

- `voice-route`: whether this gateway's own SIM can be reached by an incoming voice call,
  and whether anyone would find out if it stopped being reachable. It is not the serial
  link and it is not sending; it is the capability that would later own consuming
  `RING`/`+CLIP` if the owner goes there.

### Modified Capabilities

- `modem-link`: the read-only sweep's failure taxonomy gains the distinction between a
  refusal, a silence, a fault and a value — one level finer than the link-versus-AT
  separation that capability already defines.
- `outbound-send`: "An alert names only what the gateway observed" gains what gathering the
  evidence may cost, and its statement that the console's snapshot and the alert's are the
  same collection stops being true.
- `admin-sms-console`: how a reading the gateway does not have is rendered.

## Impact

- `app/modem/manager.py` — an IMS row in `_DIAG_QUERIES`; `_alert_observations` stops
  running the full sweep; the watchdog's tick gains an observation that cannot raise into
  it, above the `modem_watchdog_enabled` check.
- `app/modem/at_commands.py`, `app/modem/parser.py` — a reading's outcome and the modem's
  raw response are carried out of the place that still has them. Today `ATCommandError`
  keeps only a normalised string and the raw response is discarded, so no later code can
  tell a refusal from a fault.
- `app/modem/diag.py` — a decoder for `AT+QCFG="ims"`; `_ALERT_READINGS` becomes the one
  declaration of what the alert asks for and prints, instead of being unreferenced while the
  four keys sit hardcoded in `summarise_for_alert`.
- `app/alerting.py` — the voice-route conditions need a route that is not a silent no-op:
  `notify()` ignores an event type it does not know.
- `app/admin/templates/modem.html`, `app/admin/translations/{ru,en}` — a refusal, a silence
  and a fault stop sharing one style, and the new operator-visible strings are translated.
- `docs/modem.md` — how to act on the alert, since writing the setting still costs a stop
  and the script that does it lives in nobody's repository.
- `openspec/changes/verify-by-inbound-code/proposal.md` — its measured premise about a call
  to this SIM is false as written and is corrected in this change, without touching the
  routing decision built on top of it.

## Depends on

Nothing. The reading is available today on the firmware in service; what is missing is that
the gateway asks for it.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
# Tasks

## 1. Establish what is true before changing anything

- [ ] 1.1 **Vendor reference for `AT+QCFG="ims"` before the decoder is written.** The live
      samples give the shape — `+QCFG: "ims",0,0` and `+QCFG: "ims",1,1`, both captured on
      2026-09-18 — but a sample shows the values seen, not the values possible. Record from
      the Quectel reference for `EP06ELAR03A08M4G`: what each position is named, what values
      each can take, and whether the second has states beyond 0 and 1. Record in the same
      pass **what this firmware returns for a command it does not support** — a bare `ERROR`
      or `+CME ERROR: <n>` — since the whole four-way classification in section 4 turns on
      telling that apart from an error about the modem's own state. ⚠️ External contract
      gate: the reference or a captured sample lands **before** the parser and before any
      claim about what the modem does or does not report
- [ ] 1.2 **Does `AT+QCFG="ims",1` survive a power cycle?** It was written once and took
      effect after `AT+CFUN=1,1`. If the setting is not held in non-volatile memory, a hard
      reset — the watchdog's own last rung — silently removes the voice route, and the change
      owes a requirement about re-arming that it does not have. ⚠️ Costs a modem reboot on a
      gateway carrying live traffic: the owner's to run
- [ ] 1.3 **Does IMS being on move inbound SMS off the circuit-switched path?** The one way
      this change could damage what the gateway exists for. Acceptance is a live inbound SMS
      arriving and being stored with IMS on — not a test, not an outbound send, not a
      delivery report
- [ ] 1.4 **Measure whether IMS admission lags network registration, and by how long.**
      After a soft recovery (`CFUN=4→1`, the watchdog's own first rung), sample
      `AT+QCFG="ims"` and `AT+CEREG?` together every few seconds and record whether the
      second digit trails registration. The gate in the second requirement, and the rejection
      of debounce in `design.md`, both assume this window does not exist; the 2026-09-18
      measurement cannot separate "off network, reads zero" from "on network, not yet
      admitted". **If it lags, the gate widens to "registered and settled" or debounce comes
      back** — and `design.md` is rewritten rather than left standing
- [ ] 1.5 **Correct the false premise in the neighbour.** `verify-by-inbound-code`'s proposal
      says a call to this SIM is silence and disconnect, verified 07.09.2026. Record the
      2026-09-18 measurement there and what it does and does not refute: inbound-call
      authorisation is reopened, the vendor flash call is not — one SIM cannot supply the
      pool of calling numbers that scheme encodes the code in. **The owner's routing decision
      of 08.09.2026 is not touched**
- [ ] 1.6 **Write down the rollback before the switch is trusted.** IMS has been on since
      2026-09-18 with no recorded way back: `AT+QCFG="ims",0` + `AT+CFUN=1,1` appears nowhere
      in this repository. If 1.3 finds harm, the remedy must already be written down — with
      the observation window over which 1.3 is judged, since one inbound SMS proves less than
      a week of them

## 2. IMS is read while the gateway serves

- [ ] 2.1 A decoder for `AT+QCFG="ims"` in `app/modem/diag.py`, beside `decode_cireg` and
      `decode_servicedomain`, returning the two facts separately **and a named state for
      each**, as the neighbouring decoders do — the page renders decoded fields directly, so
      a decoder that returns only digits puts `enabled=1 admitted=0` in front of a person
- [ ] 2.2 A row in `_DIAG_QUERIES` (`app/modem/manager.py:129-157`) on the local budget: a
      register read the firmware answers out of its own memory
- [ ] 2.3 An unparseable response returns `{}` — the convention `decode_servicedomain` and
      `decode_cireg` already follow, and for the same reason: zero is a meaningful value
      here, so a failed read must not render as one
- [ ] 2.4 Decide and record whether `ims_reg` (`AT+CIREG?`) and `svc_domain`
      (`AT+QCFG="servicedomain"`) stay in the sweep. They cannot answer on this build; the
      case for keeping them is that a firmware update could add them and section 4 makes
      their refusal legible, the case against is two round-trips per page load. **Follows
      1.1 and section 5, not preference**
- [ ] 2.5 Decide whether the sweep reads an identity of the hardware — IMEI or ICCID. Without
      one, "IMS disabled on the module" cannot distinguish a replaced module from a reset NV,
      which is the distinction `design.md` uses to argue that condition's severity. Either
      add the row or let the caveat stand, deliberately
- [ ] 2.6 Tests: the decoder against both captured samples, against `ERROR`, and against a
      malformed response; the sweep reporting the two facts apart

## 3. The voice route is watched

- [ ] 3.1 The observation runs **above** the `modem_watchdog_enabled` check in
      `watchdog_loop` (`app/modem/manager.py:1207`), which today `continue`s past the whole
      step. This means the registration answer has to come out of `_watchdog_step`, or the
      loop polls and passes it in. ⚠️ The switch governs remedies, not observation — the live
      `modem-link` spec refused this coupling once already, and archived task 4.9 of
      `recover-from-serial-transport-loss` records it being found and fixed once already
- [ ] 3.2 The observation **cannot raise into the step**: a function with `_poll`'s explicit
      never-raises contract. A raising read placed before the decision stops the ladder
      advancing; placed after it, it swallows the returned rung and with it the settle and
      the `os._exit(1)` that must follow a hard reset
- [ ] 3.3 Edge-triggered alerting for the conditions, each raised once per episode, able to
      alert again after the state has been good in between, with a notification when the
      route returns — the shape `_notify_reopened` already uses for the link
- [ ] 3.4 **A route already lost at startup raises the alert on the first reading that
      establishes it**, not only on a transition this process witnessed. Episode state dies
      with the process, and the process exits itself on the ladder's top rung and on every
      deploy. Take the first reading only once the module is registered, so a deploy does not
      alert during the attach window
- [ ] 3.5 **Staleness.** Record when the voice route was last successfully measured, and
      alert when it has not been measurable for longer than the threshold. Both silencing
      mechanisms are real and verified: `registration_ok` returns `False` for a modem that
      does not answer at all (`app/modem/at_commands.py:662-666`), so the gate stays shut
      forever on an unanswerable modem; and an unparseable reading becomes "not measured",
      which section 4 then makes quiet on the page too
- [ ] 3.6 **Name the delivery route.** `notify()` ignores an event type it does not know and
      returns silently (`app/alerting.py:403-418`), so `notify("voice_route", …)` would do
      nothing at all and a test asserting on the latch would still pass. Either add entries to
      `_EVENT_TOGGLE`/`_EVENT_TITLE` with a toggle named deliberately, or follow the `link`
      alert's route — and either way give the conditions **distinct templates**, since the
      ERROR-handler dedup is per template in a 300-second window and one condition would
      otherwise hide behind the other
- [ ] 3.7 The alert text names which condition it is, and therefore who acts: a local setting
      and a reboot, or the carrier
- [ ] 3.8 Tests, and each one bitten: mutate the gate away → the "module off the network"
      test goes red; mutate edge-triggered to level-triggered → the "one alert per episode"
      test goes red; make the fake sender raise on the IMS command → the "ladder still
      advances and still exits on HARD" test goes red. A test that asserts on the latch
      rather than on delivery does not count for 3.6 — assert the notifier was reached

## 4. A refusal stops looking like a fault

- [ ] 4.1 Carry the outcome — value, refusal, silence, failure — and the modem's **raw
      response** out of the place that still has them. Today `_command_unlocked` raises
      `ATCommandError` carrying only `describe_at_error`'s normalised string
      (`app/modem/parser.py:112-117`), the raw text is discarded, and `collect_diagnostics`
      never sets `raw` on the failure path — so the requirement that a row shows what the
      modem answered cannot be met by editing the template alone
- [ ] 4.2 Classify from what the modem answered, not from a list of commands believed absent.
      ⚠️ **Not by sniffing the substring `ERROR`:** `+CME ERROR: 13` on `AT+CPIN?` is a failed
      SIM — the fault of the 2026-09-06 outage — and must stay a fault. A refusal is a bare
      `ERROR` or a code meaning "not supported"/"not allowed" (settled by 1.1)
- [ ] 4.3 `app/admin/templates/modem.html`: a refusal and a silence get their own rendering,
      neither in the fault style, both showing the modem's response; a genuine fault keeps
      the fault style
- [ ] 4.4 New operator-visible strings added to `app/admin/translations/ru` and `.../en`,
      as archived task 11.1 of the SMS-tab change already requires of this template
- [ ] 4.5 Look at the rendered page before calling this done — the visual contour, not the
      test. The whole requirement is about what a reader's eye does with the page
- [ ] 4.6 The positive control is concrete: a row answered `+CME ERROR: 13` is still shown as
      a fault. Without it, an implementation that renders everything as "not measured" passes

## 5. The alert path stops paying for the page

- [ ] 5.1 `_alert_observations` (`app/modem/manager.py:1162`) asks only for the readings the
      alert prints. ⚠️ **The declaration it should ask from does not exist yet:**
      `_ALERT_READINGS` (`app/modem/diag.py:155`) is referenced nowhere, and
      `summarise_for_alert` hardcodes the four keys in its body. Make it one declaration
      serving both the asking and the printing
- [ ] 5.2 Tests that pin it in both directions: adding a row to the page's sweep does not add
      a command to the alert path; adding a key to what the alert prints without adding it to
      what it asks for goes red. Bite both
- [ ] 5.3 Confirm the alert still says "observations unavailable" when the modem answers
      nothing — the behaviour `_alert_observations` exists for, which must survive the split

## 6. From alert to remedy

- [ ] 6.1 `docs/modem.md` gains what to do on each condition, beside its existing "Serial
      Port Locking" and "Useful Debug Commands" sections. Writing the setting still costs a
      service stop, and the script that does it lives in `/tmp` on one host and in no
      repository. An alert arriving in six months to somebody who did not run the 2026-09-18
      measurement needs a next step it can reach

## 7. Acceptance on the live gateway

- [ ] 7.1 Deploy, then read `/admin/modem` and record the live IMS state. **The first reading
      of it that has ever cost nothing**, and it answers a question open since 2026-09-18:
      whether the module is still admitted, or whether the `1,1` measured that day has since
      fallen away unseen
- [ ] 7.2 A live inbound SMS after the deploy (1.3), over the window 1.6 names, and the page
      showing no red row on a healthy modem
- [ ] 7.3 Owner: place one incoming call to the SIM and confirm `RING` / `+CLIP` still reach
      the journal. Nothing consumes them — that is a non-goal — but the alert claims to watch
      a route, and only a call proves the route

## Хендофф

ветка: master
имя: Q·голосовой-маршрут

# Хендофф — заявка написана и откритикована, ждёт владельца

Состояние на 18.09.2026, ~13:00 UTC. Кода не написано ни строки: полоса C
дошла до конца авторинга и остановилась там, где положено — перед `/opsx:apply`.

⚠️ **Буква сессии здесь `Q`, а не `M`.** Родительский хендофф назывался
`M·ИМС-под-наблюдением`, но карта букв в `derflow/_capture.md` отдаёт `M`
проекту mprz.ru, а `sms-gate` — это `Q`. Старое имя было опиской.

## Что приземлилось

Коммит `1d8f07b`, локальный. **В `deploy-remote` не пушено и пушить нельзя без
слова владельца — пуш рестартит боевой сервис.** На `deploy-remote/master`
по-прежнему `40ddbfb`.

Заявка `openspec/changes/watch-the-voice-route`: 8 требований, 29 сценариев,
четыре capability. Отметка круга критики стоит (`.critique`).

## Три поправки к родительскому хендоффу — проверены, не повторять старые версии

1. **IMS уже `1,1`, и звонок дошёл.** Родитель писал «второй разряд мог стать
   единицей, и сейчас этого не знает никто». Знает: память проекта
   `ep06-does-inbound-calls-once-ims-is-on` фиксирует `+QCFG: "ims",1,1` и
   пятнадцать пар `RING`/`+CLIP` с номером звонящего.
2. 🔴 **Рунг `call` в `route-sends-by-operator` — НЕ наш модем.** Родитель
   называл IMS предусловием этого рунга. Это вендорский flash call uCaller:
   *«Our modem does not participate at all»*. Код там — последние четыре цифры
   ЗВОНЯЩЕГО номера, то есть нужен пул номеров, которого одна симка не даёт ни
   при каком IMS. Настоящий сосед — `verify-by-inbound-code`, и ложна там ровно
   одна фраза: «a call to its SIM is silence and disconnect». Решение владельца
   от 08.09 о платном рунге этой поправкой НЕ затрагивается.
3. **Таймаут `AT+CLIP?` уже разобран.** Родитель считал «короткое окно» догадкой
   к проверке; замер лежит в комментарии `app/modem/manager.py:139-147` — дали
   восемь секунд, потратил все восемь, не ответил.

## Что круг критики переложил и поймал

Круг был один, парой (`system-architect` + `gap-finder`), закрыт по счёту.
**Второго круга не будет** — дальше только механика.

Переложено:
- IMS не принадлежит `modem-link`: та capability про последовательный линк, и её
  первое требование стоит на различении «линк против радио». Заведена новая
  capability **`voice-route`**;
- цена сбора улик для алерта принадлежит `outbound-send` и оформлена как
  **MODIFIED**: существующее требование утверждает, что снимок консоли и есть
  то, что несёт алерт, — после этой заявки фраза становится ложной.

Поймано в нормах (каждое проверено кодом):
- отказ ≠ «прошивка не знает команды». `+CME ERROR: 13` на `AT+CPIN?` — севшая
  симка, дефект аварии 06.09; строка обязана остаться красной. Первая редакция
  требования красила бы её как «не измерено»;
- наблюдение внутри тика вотчдога может оборвать лестницу восстановления и
  проглотить `os._exit(1)` после hard reset;
- `modem_watchdog_enabled` пропускает весь шаг (`manager.py:1207`), то есть
  слежка стала бы отключаемой тумблером, заведённым для другого.

Поймано в моих собственных утверждениях о коде:
- `_ALERT_READINGS` (`diag.py:155`) **не используется нигде** — фильтр не «уже
  есть», его предстоит создать;
- вотчдог **не держит** последовательную блокировку через тик: `command()`
  берёт её на каждую команду.

## Чего НЕ делать

- **не пушить в `deploy-remote` без слова владельца** — рестарт боевого сервиса;
- **не останавливать `sms-gate` ради чтения** и не слать AT в порт при живом
  сервисе — порт держит шлюз;
- **не читать `ERROR` как «модуль не умеет»**;
- **не открывать второй круг критики** — слой закрыт по счёту;
- `sudo` через ssh не звать: TTY нет. Меняющее состояние — блоком коротких
  строк владельцу, ≤60 знаков, без `&&`. Read-only замеры снимаются сами:
  `ssh -p 30022 home.deralsem.ru`.

## Порядок шагов дальше

1. **Владелец читает заявку и принимает или отклоняет.** До этого `/opsx:apply`
   не начинать — это proposal, а не план.
2. Задачи 1.2, 1.3, 1.6 и 7.3 — владельца: они требуют ребута модуля, живой
   входящей SMS и живого входящего звонка на боевом шлюзе.
3. Задачу 1.1 (вендорский референс на `AT+QCFG="ims"`) можно закрывать сессией,
   если есть доступ к документации Quectel. **Внешне-контрактный гейт: референс
   ДО парсера.**
4. Задача 1.5 (поправить ложную посылку в `verify-by-inbound-code`) —
   дешёвая и не ждёт никого, кроме принятия заявки.

## Живой риск, заведённый отдельно

`waiting.py` строка **`sms-gate-ec2f9e87/20260918-03`**: IMS включён в проде с
18.09, и что входящая SMS всё ещё доходит, не проверял никто. Проба и оба её
исхода сняты на боевой базе. 🔴 Проба ловит только ХОРОШИЙ исход — вред это
отсутствие входящих, и его ловит только наступивший срок при молчащей пробе.
Отката в репозитории нет вовсе (задача 1.6).

## Единственная копия — на ноутбуке

`master` трекает `github/main`, ветки `github/master` не существует. На
18.09.2026 четыре коммита заявок (`0e2b272`, `1d8f07b`, `3b4ae67`, `ab91abd`)
не лежат ни на GitHub, ни на боевом хосте — только на этой машине. Резерв
делается `git push github master:main`, он ничего не рестартит. Владельцу
предложено 18.09, ответа не было — не отказ, а незакрытый вопрос.

⚠️ В `deploy-remote` эти коммиты пушить НЕ надо: кода в них нет вовсе (15
файлов, все `openspec/` плюс строка реестра), а пуш туда рестартит боевой
сервис. Пуш становится нужен, когда появится код.

## Соседи

- `openspec/changes/verify-by-inbound-code` — ложная посылка, задача 1.5;
- `openspec/changes/carry-telegram-on-any-uplink` — **висит долг: выданный
  владельцу `sudo`-блок для задач 1.2–1.4 не отработан**, хендофф
  `.claude/handoff/backup-uplink-wireguard.md`;
- `.claude/handoff/modem-ims-watch.md` — родитель этого хендоффа, вытеснен им.
<!-- SECTION:NOTES:END -->
