# Tasks

## 1. Establish what is true before changing anything

- [x] 1.1 **Vendor reference for `AT+QCFG="ims"` before the decoder is written.** Done
      2026-09-20, recorded in `captures/` with both source documents named, dated and
      version-stamped, and the relevant sections extracted verbatim. The reference is the
      **LTE-A(Q) Series IMS Application Note V1.0** (2021-08-18), whose §1.1 lists EP06
      Series, plus the **EP06&EG06&EM06 AT Commands Manual V1.0** for the error codes.
      🔴 **It contradicts this change in two places and closes 1.2 in a third:** the first
      position is `<IMS_conf>` with **three** values, where `0` is not "off" but "defer to
      the carrier profile" and `2` is the explicit disable; the second is `<VoLTE_cap>`,
      which the vendor calls the capability of VoLTE in its table and the IMS registration
      status in its prose, and **never** calls the network's verdict. `proposal.md`,
      `design.md`, `specs/voice-route` and `specs/admin-sms-console` have been rewritten
      against it rather than left standing. Also settled: the maximum response time is
      **300 ms** (task 2.2), and `AT+CIREG` appears nowhere in the EP06 manual, which agrees
      with Quectel's letter and with the live `ERROR`. **What the firmware returns for a
      command it does not have** is answered by the live sample and not by the reference: a
      **bare `ERROR`** for `AT+CIREG?`. The manual promises only that `+CME ERROR: <err>` is
      *"similar to the ERROR result code"*, so task 4.2 must accept **both** forms of refusal
      and must not assume the bare one
- [x] 1.2 **Does `AT+QCFG="ims",1` survive a power cycle?** **Yes**, and the reference says
      so without spending a reboot on a gateway carrying live traffic: §2.3.1 Characteristics
      — *"the command takes effect after rebooting; the configuration will be saved
      automatically"*. The watchdog's hard reset therefore does not remove the voice route.
      🔴 **But the reference names a second way to lose it that nobody had considered, and it
      needs no reboot of ours at all:** §1.2.1 — an MBN activated or deactivated restores an
      NV item written by AT command to the profile's default; §1.2.3 — the MBN is selected
      automatically from the SIM's IMSI; §1.2.2 — *"not all operator MBN files enable IMS by
      default"*. **A SIM swap is a silent disarm.** This does not create the re-arming
      requirement the task was braced for — re-arming means rebooting the module, and
      `design.md` argues it out in its own right — but it is why the configuration is
      alerted on separately and why it is alerted even while the route still works.
      ⚠️ Whether the setting is *still* `1` on the live module today is a different question,
      and it is task 7.1
- [x] 1.3 **Does IMS being on move inbound SMS off the circuit-switched path?** **No harm
      observed.** The registry row `sms-gate-ec2f9e87/20260918-03` carried the probe; run
      read-only against the live database on 2026-09-20 it answers **7**, and the rows are
      real inbound messages stored after IMS was switched on at ≈11:42 UTC on 2026-09-18:
      `13:15:17` and `14:08:52` that day, then `11:43:49`, `12:11:43`, `12:27:38`, `14:01:49`
      and `14:07:25` on 2026-09-19. The first arrived about ninety minutes after the switch.
      Acceptance as written — a live inbound SMS, not a test and not an outbound send — is
      met seven times over, and the change's main risk is retired. ⚠️ **Two days is not the
      window:** the probe catches only the good outcome, harm is the *absence* of inbound
      messages, and absence is judged by the review date with the probe still silent. That
      judgement belongs to 1.6's window and to 7.2, not here. The reference makes the
      mechanism concrete rather than hypothetical — §1.3.2.2 of the application note
      documents SMS over IMS and the `+g.3gpp.smsip` capability in the IMS registration —
      which is why the window still has to be sat out.
      🔴 The registry row is **not** closed by this session: `ack` / `taken` / `done` are the
      owner's call alone. It is ripe and waiting for that word
- [x] 1.4 **Measure whether the route's availability lags network registration, and by how
      long.** **No lag observed at or after the moment the gateway can look.** Run on
      2026-09-20 with `deploy/ims-lag-probe.py` on the live gateway, two attempts:
      🔴 **the first answered `LAG: 0.0` and had measured nothing** — it blocked about eleven
      seconds on its own command waits, so the whole reattach happened inside its pause, and
      it never sampled between `CFUN=4` and `CFUN=1`, so it could not even show the radio
      had cycled. The probe was rewritten to sample throughout and to print
      `radio never cycled - measures nothing` rather than a number it had not earned.
      The second run is the measurement: `left the network: True`, thirty seconds off the
      network over eight samples, **every one `+CEREG: 0,0` with `+QCFG: "ims",1,0`** —
      registration never read positive while the route read negative. Both returned positive
      at the same sample, 37.4 s, which was also the first moment after `AT+COPS=0` returned,
      and therefore the first moment the production path could look at all.
      ⚠️ **Bound, not a zero:** a lag shorter than about six seconds sits in an unobserved
      gap between `CFUN=1` and the first sample after it. It would be invisible to the
      gateway too, so the gate stands as written — on that named basis, recorded in
      `design.md`, not on "no lag exists".
      ✅ **Bonus the run settles:** the configuration digit held `1` unchanged across the
      whole radio cycle while availability swung 1 → 0 → 1, which is the split this change
      is built on, observed rather than assumed. And `+QCFG: "ims",1,1` before the run
      answers task 7.1 early: two days on, the setting and the route are both still there.
      The probe lives in the repository — `deploy/ims-lag-probe.py` — deliberately: the
      owner's `/tmp/ims_set.py` lives in no repository, and this proposal complains about
      exactly that. It reads only the **second** field for "route up"; the first has three
      states, and reading it as a boolean is the bug this change exists to avoid.
- [x] 1.5 **Correct the false premise in the neighbour.** Done —
      `openspec/changes/verify-by-inbound-code/proposal.md`, the paragraph on remedies. The
      sentence is withdrawn rather than deleted, with the 2026-09-18 measurement recorded and
      the split stated explicitly: inbound-call authorisation is reopened, the vendor flash
      call is not, and the owner's routing decision of 08.09.2026 is untouched.
      `openspec validate verify-by-inbound-code --strict` passes.
- [x] 1.6 **Write down the rollback before the switch is trusted.** Written into
      `docs/modem.md`, new section *Voice Route (IMS / VoLTE)*: how to read the setting, what
      each of the three configuration values means, how to turn it on, how to roll it back,
      and what would make a rollback the right call. The window is named — **2026-10-18**,
      watched by registry row `sms-gate-ec2f9e87/20260918-03` — together with the reason a
      probe cannot close it: harm is an absence, and absence is read off the review date.
      🔴 **The reference changed the rollback command's meaning, not its text.**
      `AT+QCFG="ims",0` is still right, but `0` is *"defer to the carrier profile"*, not
      *"off"*; the explicit disable is `2`. Rolling back with `2` would leave the module in a
      state it has never been in, pinned against any future profile that would have enabled
      VoLTE. The doc says so in as many words, because the wrong one looks more correct

## 2. IMS is read while the gateway serves

- [x] 2.1 A decoder for `AT+QCFG="ims"` in `app/modem/diag.py`, beside `decode_cireg` and
      `decode_servicedomain`, returning the two facts separately **and a named state for
      each**, as the neighbouring decoders do — the page renders decoded fields directly, so
      a decoder that returns only digits puts `ims_conf=1 volte_cap=0` in front of a person.
      🔴 **The configuration field has three values, not two** (`captures/`): `0` defers to
      the carrier profile, `1` is a compulsory enable, `2` a compulsory disable. A boolean
      here is a bug, and a decoder that maps `0` to "disabled" states the opposite of the
      truth. A fourth value the vendor does not list SHALL decode as unrecognised, not as one
      of the three
      ✅ `decode_qcfg_ims` in `app/modem/diag.py`. Three named configuration states from
      the vendor's own words, a named state for the VoLTE field, and a value outside the
      three decoding as `unrecognised`. The digits are kept beside the names, as the
      neighbouring decoders do, so the page renders words and the raw number stays
      readable.
- [x] 2.2 A row in `_DIAG_QUERIES` (`app/modem/manager.py:129-157`) on the local budget: a
      register read the firmware answers out of its own memory. Confirmed by the reference —
      maximum response time **300 ms** (§2.3.1), so the local budget is the right one and no
      special case is owed
      ✅ Row `ims` in `_DIAG_QUERIES`, on `_DIAG_LOCAL`. The command string is named once
      (`_IMS_QUERY`) because the watchdog's tick asks for it too and two spellings of one
      command is how the sweep and the watcher would come to read different things.
- [x] 2.3 An unparseable response returns `{}` — the convention `decode_servicedomain` and
      `decode_cireg` already follow, and for the same reason: zero is a meaningful value
      here, so a failed read must not render as one
      ✅ `{}` on an unparseable response, tested against `ERROR`, an empty string, a
      truncated `+QCFG: "ims",1` and a `servicedomain` reply.
- [x] 2.4 Decide and record whether `ims_reg` (`AT+CIREG?`) and `svc_domain`
      (`AT+QCFG="servicedomain"`) stay in the sweep. They cannot answer on this build; the
      case for keeping them is that a firmware update could add them and section 4 makes
      their refusal legible, the case against is two round-trips per page load. **Follows
      1.1 and section 5, not preference**
      ✅ **Decided: both stay.** Section 5 removed the reason to cut them — they are no
      longer on the alert path at all, so the cost is two round-trips on a page an
      operator chose to open, and both are *refusals*, answered at once rather than waited
      out. Section 4 makes them legible instead of red. And keeping them is what the
      `modem-link` delta requires of itself: *"a previously refused command begins to
      answer → the value is reported, without any change to the gateway"*. Removing the
      rows would make that scenario unreachable by construction.
- [x] 2.5 Decide whether the sweep reads an identity of the hardware — IMEI or ICCID. Without
      one, "the configuration is no longer the one we set" cannot distinguish a replaced
      module from a reset NV, which is the distinction `design.md` uses to argue that
      condition's severity. 🔴 **The reference adds a third cause and makes ICCID the more
      useful of the two:** §1.2.1 says an MBN activation restores the setting to the profile's
      default and §1.2.3 says the profile is chosen from the SIM's IMSI, so a swapped SIM
      disarms the route — and a SIM identity in the sweep is what would make that visible.
      Either add the row or let the caveat stand, deliberately
      ✅ **Decided: no identity row; the caveat stands, deliberately.** The distinction
      `design.md` wants — a replaced module against a reset NV against a swapped SIM —
      needs a *remembered* identity, not a displayed one. Nothing stores what the ICCID
      was, so an ICCID on the page at the moment an alert arrives answers nothing: the
      reader would have to already know the old value. Remembering it is new state with
      its own lifecycle (who writes the baseline, what a deploy does to it), which is a
      change of its own rather than a row. ⚠️ And the gate binds here: there is no vendor
      reference for `AT+QCCID` in `captures/` and no live sample, so a parser for it
      cannot be written under this change's own rule. The alert names the condition and
      not its cause, which is the standard this project already holds alerts to.
- [x] 2.6 Tests: the decoder against both captured samples (`0,0` and `1,1`), against the
      three configuration values including **`2` and the healthy `0,1`, which no live sample
      covers and which come from the reference**, against an unlisted fourth value, against
      `ERROR`, and against a malformed response; the sweep reporting the two facts apart

      ✅ `tests/test_modem_diag.py` — both captured samples, all three configuration
      values including the healthy `0,1` that no live sample covers, an unlisted fourth
      value, `ERROR`, and three malformed shapes. `tests/test_modem_collect.py` — the
      sweep reporting the two facts apart.
## 3. The voice route is watched

- [x] 3.1 The observation runs **above** the `modem_watchdog_enabled` check in
      `watchdog_loop` (`app/modem/manager.py:1207`), which today `continue`s past the whole
      step. This means the registration answer has to come out of `_watchdog_step`, or the
      loop polls and passes it in. ⚠️ The switch governs remedies, not observation — the live
      `modem-link` spec refused this coupling once already, and archived task 4.9 of
      `recover-from-serial-transport-loss` records it being found and fixed once already
      ✅ `_observe_voice_route()` runs in `watchdog_loop` **above** the
      `modem_watchdog_enabled` check, and the registration answer it takes is handed to
      the step through `_take_poll()` rather than polled twice. Bitten: moving the call
      below the switch turns the test red.
- [x] 3.2 The observation **cannot raise into the step**: a function with `_poll`'s explicit
      never-raises contract. A raising read placed before the decision stops the ladder
      advancing; placed after it, it swallows the returned rung and with it the settle and
      the `os._exit(1)` that must follow a hard reset
      ✅ Never raises, and both halves are guarded: the poll, and the AT command. A read
      that fails is recorded as unmeasured. Bitten with a sender that raises on every IMS
      command — the ladder still reaches HARD, `hard_reset` is still carried out, and
      `os._exit(1)` still runs.
- [x] 3.3 Edge-triggered alerting for the conditions, each raised once per episode, able to
      alert again after the state has been good in between, with a notification when the
      route returns — the shape `_notify_reopened` already uses for the link
      ✅ `VoiceRouteWatch` latches one alert per episode per condition and clears on the
      state being good in between; the route returning sends one notification. Bitten:
      removing the latch turns the "one alert per episode" test red.
- [x] 3.4 **A route already lost at startup raises the alert on the first reading that
      establishes it**, not only on a transition this process witnessed. Episode state dies
      with the process, and the process exits itself on the ladder's top rung and on every
      deploy. 🔴 **The two conditions start differently.** The *availability* reading waits
      for registration, so a deploy does not alert during the attach window. The
      *configuration* reading does not wait: it is local, readable while the module is still
      attaching, and a deploy that comes up on a drifted configuration should say so at once
      — that is exactly the 2026-09-18 state this change exists to stop being invisible
      ✅ All three latches start closed, so the first reading that establishes a condition
      raises it. The two conditions start differently as required, and it falls out of the
      gate rather than out of a special case: availability is simply not read as a verdict
      while unregistered, and the configuration is read and judged immediately.
- [x] 3.5 **Staleness.** Record when the voice route was last successfully measured, and
      alert when it has not been measurable for longer than the threshold. Both silencing
      mechanisms are real and verified: `registration_ok` returns `False` for a modem that
      does not answer at all (`app/modem/at_commands.py:662-666`), so the gate stays shut
      forever on an unanswerable modem; and an unparseable reading becomes "not measured",
      which section 4 then makes quiet on the page too
      ✅ `STALE_AFTER = 3600.0`, with the reasoning written where the constant is: the
      tick's ceiling is sixty seconds, so it is sixty consecutive failures to measure —
      past any recovery the ladder performs, and short enough that an unreadable route
      does not stay unread for a working day. An unregistered module counts as *not
      measured*, which is the silencing mechanism the alert exists to catch.
- [x] 3.6 **Name the delivery route.** `notify()` ignores an event type it does not know and
      returns silently (`app/alerting.py:403-418`), so `notify("voice_route", …)` would do
      nothing at all and a test asserting on the latch would still pass. Either add entries to
      `_EVENT_TOGGLE`/`_EVENT_TITLE` with a toggle named deliberately, or follow the `link`
      alert's route — and either way give the conditions **distinct templates**, since the
      ERROR-handler dedup is per template in a 300-second window and one condition would
      otherwise hide behind the other
      ✅ Three entries in `_EVENT_TOGGLE`/`_EVENT_TITLE` — `voice_route`,
      `voice_route_config`, `voice_route_stale` — following the `link` alert's route and
      sharing `notify_system_errors` rather than adding a setting no SHALL asks for.
      Distinct types, so `notify`'s per-type dedup cannot hide one condition behind
      another. Logged at `warning`, not `error`: an ERROR record is itself delivered by
      the Telegram handler, and the two together would wake the same person twice.
      🔴 The tests assert on **delivery** — `notify` is patched and its calls counted —
      not on the latch.
- [x] 3.7 The alert text names which condition it is, and therefore who acts. 🔴 **Two
      conditions, and the second does not name a culprit.** *The configuration is no longer
      the one this gateway set* — someone writes `AT+QCFG="ims",1` and accepts a reboot, and
      the text says which of the two off-states it is, since `0` (profile decides) and `2`
      (explicitly disabled) got there by different routes. *The route is not available* — the
      gateway has no reading that says why, so the text reports the observation and stops.
      ⚠️ It must not say the carrier refused us: `outbound-send` already forbids naming a
      cause the gateway did not observe, and the first draft of this change broke that rule
      ✅ Each text names its condition. The configuration alert says which of the two
      off-states it is and what writing it back costs. The availability alert reports the
      observation and stops; tested for the absence of "carrier", "operator", "refused"
      and "rejected".
      🔴 Found while biting: the meaning of the configuration value `0` was written down
      **twice** — in the decoder's map and again in the alert's prose — so a mutation of
      the map left the alert green. Two places that can come to disagree about one digit,
      with the page saying one thing and the alert another. The second source is gone; the
      alert now takes the state's name from the decoder.
- [x] 3.8 Tests, and each one bitten: mutate the gate away → the "module off the network"
      test goes red; mutate edge-triggered to level-triggered → the "one alert per episode"
      test goes red; make the fake sender raise on the IMS command → the "ladder still
      advances and still exits on HARD" test goes red; **map the configuration value `0` to
      "disabled" → the "`0,1` is a working route and raises no availability alert" test goes
      red**. A test that asserts on the latch rather than on delivery does not count for 3.6
      — assert the notifier was reached

      ✅ Five mutations run, each red on its own test and green again after restoring:
      the registration gate removed; the latch made level-triggered; the observation's
      exception guard narrowed; configuration `0` mapped to "disabled"; the observation
      moved below the watchdog switch.
## 4. A refusal stops looking like a fault

- [x] 4.1 Carry the outcome — value, refusal, silence, failure — and the modem's **raw
      response** out of the place that still has them. Today `_command_unlocked` raises
      `ATCommandError` carrying only `describe_at_error`'s normalised string
      (`app/modem/parser.py:112-117`), the raw text is discarded, and `collect_diagnostics`
      never sets `raw` on the failure path — so the requirement that a row shows what the
      modem answered cannot be met by editing the template alone
      ✅ `ModemFailure` carries `response` beside the normalised message, set at both
      raise sites — the `ERROR` path and the timeout path. `collect_diagnostics` reads it
      and sets `raw` on the failure path too.
- [x] 4.2 Classify from what the modem answered, not from a list of commands believed absent.
      ⚠️ **Not by sniffing the substring `ERROR`:** `+CME ERROR: 13` on `AT+CPIN?` is a failed
      SIM — the fault of the 2026-09-06 outage — and must stay a fault. **Settled by 1.1:** a
      refusal is a bare `ERROR`, or `+CME ERROR: 3` / `4` (operation not allowed / not
      supported), or `+CMS ERROR: 302` / `303` (the same two). A fault is anything else the
      modem says about its own state — `+CME ERROR: 10`, `13`, `14`, `15` are SIM not
      inserted, SIM failure, SIM busy, SIM wrong. ⚠️ **Both forms of refusal must be
      accepted:** the live sample shows a bare `ERROR` for `AT+CIREG?`, but the EP06 manual
      promises only that `+CME ERROR` is *"similar to the ERROR result code"*, so a build that
      answers a missing command with a code is not ruled out
      ✅ `classify_at_outcome` in `app/modem/parser.py`, decided from the response alone
      and never from a list of commands. Refusal is a bare `ERROR`, `+CME 3`/`4`,
      `+CMS 302`/`303` — both forms accepted, as 1.1 requires. A verbose firmware saying
      the same in words is classified by the same rule, and an error about the modem's own
      state stays a fault whichever form it arrives in.
- [x] 4.3 `app/admin/templates/modem.html`: a refusal and a silence get their own rendering,
      neither in the fault style, both showing the modem's response; a genuine fault keeps
      the fault style
      ✅ 🔴 **Found on the way: `.err` was not defined in the stylesheet at all.** The
      modem template had been asking for the class since it was written, so the "fault
      style" this requirement distinguishes a refusal *from* did not exist — a fault
      rendered as ordinary body text and looked exactly like everything else. The
      requirement would have been satisfiable by changing nothing. The style is defined
      now, and refusal and silence are rendered quietly beside it.
- [x] 4.4 New operator-visible strings added to `app/admin/translations/ru` and `.../en`,
      as archived task 11.1 of the SMS-tab change already requires of this template
      ✅ Two new strings in `app/admin/translations/ru` and `.../en`. Tested in both
      languages, including that neither language claims the firmware lacks the command.
- [x] 4.5 Look at the rendered page before calling this done — the visual contour, not the
      test. The whole requirement is about what a reader's eye does with the page
      ✅ Looked at. The page was rendered through the real router with the live module's
      actual sweep — `AT+CIREG?` and `AT+QCFG="servicedomain"` refused, `AT+CLIP?` silent,
      everything else answering — served locally and opened in a browser, in both
      languages and with and without a failed SIM. The contour is the one the requirement
      is about: on healthy hardware the three permanently-unsuccessful rows are quiet, and
      on the page with a failed SIM the single red row is the fault, with nothing else
      competing for the eye. ⚠️ Headless Chrome does not start in this sandbox; the
      screenshot was taken through the browser extension against a local http server.
- [x] 4.6 The positive control is concrete: a row answered `+CME ERROR: 13` is still shown as
      a fault. Without it, an implementation that renders everything as "not measured" passes

      ✅ `test_a_failed_sim_is_still_a_fault`, bitten: rendering every unsuccessful row as
      "nothing was measured" turns it red.
## 5. The alert path stops paying for the page

- [x] 5.1 `_alert_observations` (`app/modem/manager.py:1162`) asks only for the readings the
      alert prints. ⚠️ **The declaration it should ask from does not exist yet:**
      `_ALERT_READINGS` (`app/modem/diag.py:155`) is referenced nowhere, and
      `summarise_for_alert` hardcodes the four keys in its body. Make it one declaration
      serving both the asking and the printing
      ✅ `_ALERT_READINGS` is now the declaration it was assumed to be — label, key and
      renderer per reading — and `ALERT_KEYS` is derived from it. `summarise_for_alert`
      prints from it and `collect_diagnostics(only=…)` asks from it. Four commands on the
      alert path instead of fourteen; the output format is unchanged.
- [x] 5.2 Tests that pin it in both directions: adding a row to the page's sweep does not add
      a command to the alert path; adding a key to what the alert prints without adding it to
      what it asks for goes red. Bite both
      ✅ Both directions, both bitten: restoring the full sweep on the alert path turns
      the "asks only for what it prints" test red, and making the asked keys a subset of
      the printed ones turns the "one declaration" test red.
- [x] 5.3 Confirm the alert still says "observations unavailable" when the modem answers
      nothing — the behaviour `_alert_observations` exists for, which must survive the split

      ✅ The liveness pre-check and the "observations unavailable" fallback are untouched
      by the narrowing, and there is a test on the narrowed path that says so.
## 6. From alert to remedy

- [x] 6.1 `docs/modem.md` gains what to do on each condition, beside its existing "Serial
      Port Locking" and "Useful Debug Commands" sections. Writing the setting still costs a
      service stop, and the script that does it lives in `/tmp` on one host and in no
      repository. An alert arriving in six months to somebody who did not run the 2026-09-18
      measurement needs a next step it can reach

      ✅ `docs/modem.md`, new *When an alert arrives* subsection: a row per condition
      saying what the gateway saw and what to do, written for somebody who was not here
      for the 2026-09-18 measurement. It names the SIM-swap question first on the
      configuration alert, because that is the cause that will move the setting again
      after it is written back.
## 7. Acceptance on the live gateway

- [ ] 7.1 Deploy, then read `/admin/modem` and record the live IMS state. **The first reading
      of it that has ever cost nothing**, and it answers a question open since 2026-09-18:
      whether the voice route is still available and the configuration still the one that was
      written, or whether the `1,1` measured that day has since fallen away unseen
- [ ] 7.2 A live inbound SMS after the deploy (1.3), over the window 1.6 names, and the page
      showing no red row on a healthy modem
- [ ] 7.3 Owner: place one incoming call to the SIM and confirm `RING` / `+CLIP` still reach
      the journal. Nothing consumes them — that is a non-goal — but the alert claims to watch
      a route, and only a call proves the route
