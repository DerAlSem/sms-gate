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
