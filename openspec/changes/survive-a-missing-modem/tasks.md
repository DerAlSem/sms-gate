## 1. One way to bring the link up

- [x] 1.1 Write failing tests for `ensure_link()`: it opens both ports, applies the init sequence including `AT+CNMI`, reconciles the modem's stored messages, and reports failure if any part does not complete
- [x] 1.2 Add `ensure_link()` to `ModemManager`, folding together what `connect()` does at startup and what `_reopen_link` does after a loss, so there is one operation and one definition of done
- [x] 1.3 Make a partial result count as a failed attempt — a port that opens but is not initialised must not be treated as usable
- [x] 1.4 Rewrite `_reopen_link` to call `ensure_link()` instead of carrying its own open-and-init sequence
- [x] 1.5 Verify the URC port is brought up by the same operation, not by a second path of its own

## 2. The link comes up outside startup

- [x] 2.1 Write a failing test that the app serves HTTP when the device node does not exist
- [x] 2.2 Remove `await modem_manager.connect()` from `lifespan` in `app/main.py`, ahead of `yield`
- [x] 2.3 Start the recovery gate **closed**, so every loop waits rather than acting on a link that is not there yet
- [x] 2.4 Add a supervised background task that owns establishing the link and calls `ensure_link()`
- [x] 2.5 Verify each existing loop tolerates starting before the link exists — sender, reader, inbound, expire, retry, keepalive, parts-flush, watchdog

## 3. Reopening no longer ends

- [x] 3.1 Write failing tests: attempts continue past the old budget, the delay widens to a ceiling, and the gateway does not exit
- [x] 3.2 Put the unbounded cadence and its backoff ceiling in the linker rather than in `at_commands.py` — one `reconnect()` stays bounded, and the loop above it never stops calling it. Same outcome, and it leaves the reopen's own tested behaviour untouched
- [x] 3.3 Keep treating an absent node and an unpermitted node as "not back yet" rather than as errors
- [x] 3.4 Remove the terminal rung that exits the process, from both the ladder in `manager.py` and the startup path in `at_commands.connect()`
- [x] 3.5 Confirm a returning device is picked up on the next attempt even after the delay has widened to its ceiling

## 4. Absence is loud, not silent

- [x] 4.1 Write failing tests: the health snapshot reports the link unusable, and an alert fires once per episode rather than per attempt
- [x] 4.2 Report the unusable link in the health snapshot alongside the existing `link_last_good` and `link_reopens`
- [x] 4.3 Raise the alert on entering the absent state and arm it again only after the link returns
- [x] 4.4 Make sure nothing reports the gateway healthy while it has no link

## 5. The console says so on every page

- [x] 5.1 Write a failing test that any admin page renders with no modem and carries the notice
- [x] 5.2 Put the notice in the base template, fed by the same health snapshot the diagnostics page reads
- [x] 5.3 Make the diagnostics page render with values reported unavailable instead of failing when the modem cannot be read
- [x] 5.4 Verify the notice disappears when the link is in service
- [x] 5.5 Add the Russian and English strings for the notice

## 6. Messages wait instead of failing

- [x] 6.1 Write failing tests: a message due with no link stays `pending` with its attempt count unchanged, and is sent once the link comes up having spent no retry budget
- [x] 6.2 Hold a message when there is no link, checked in the same place as the existing unregistered hold and before an attempt is claimed
- [x] 6.3 Confirm the pending deadline still terminates a message held through a long outage
- [x] 6.4 Confirm `POST /sms/send` still accepts and queues while the modem is absent

## 7. Deploy and living spec

- [x] 7.1 Revisit `Restart=` and `StartLimitBurst=` in `deploy/`, whose reasoning assumed a startup path that deliberately exited, and update the comments that describe it
- [x] 7.2 Run the full test suite and confirm nothing depended on the gateway exiting for a lost link
- [ ] 7.3 Rehearse on prod hardware: unplug the modem, confirm the console stays up and shows the notice, replug, confirm sending and inbound resume with no restart
- [ ] 7.4 Confirm inbound that arrived while unplugged is delivered once, not twice, on reconciliation
- [ ] 7.5 Archive the change so the deltas land in `openspec/specs/`
