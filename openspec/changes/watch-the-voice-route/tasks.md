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
