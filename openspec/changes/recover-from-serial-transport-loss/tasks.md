## 1. Test scaffolding

- [ ] 1.1 Add a serial fake that can raise on write/drain, return EOF on read, and be told the device is absent — the existing `_DelayedSerial` in `tests/test_at_recovery.py` never raises and the watchdog tests replace whole methods, so no current fixture can express a dead port
- [ ] 1.2 Note in the fixture which module to patch: `serial_asyncio` is imported separately by `app/modem/at_commands.py` and `app/modem/manager.py`, so reader-side and command-side tests patch different names
- [ ] 1.3 Extract background-task supervision out of `app/main.py`'s lifespan into a function that can be called from a test — there is no test file for `main.py` today

## 2. The failure class

- [ ] 2.1 Add a shared base and `ModemTransportError` as a sibling of `ATCommandError` in `app/modem/at_commands.py`, carrying the written-bytes flag with the same meaning
- [ ] 2.2 Classify `serial.SerialException` and `OSError` from `_send`, `_read_until` and `_drain` as transport failures — decide deliberately whether to catch `OSError` alone, since `SerialException` derives from it and `serial` is not currently imported
- [ ] 2.3 Classify an empty read on a previously open link as a transport failure, in both `_read_until` and `_drain`; `_read_until` today has no empty-chunk check and would spin to its deadline and report an AT timeout
- [ ] 2.4 Add a usable/unusable state to `ATSerial`, set on connect and cleared on any transport failure; every entry point fails fast when it is clear, and `close()` clears the reader and writer so their state after a failure is defined
- [ ] 2.5 Test: a raising transport produces `ModemTransportError`; a `+CMS ERROR` reply still produces `ATCommandError`
- [ ] 2.6 Test: `ModemTransportError` is not an instance of `ATCommandError`, and both are instances of the shared base
- [ ] 2.7 Test: a closed stream is classified as a lost link rather than as a command timeout, and does not spin
- [ ] 2.8 Test: a command issued after a lost link fails immediately rather than after its timeout

## 3. The written-bytes record

- [ ] 3.1 Change the flag assignment in `send_sms_pdu` from `isinstance(exc, ATCommandError)` to the shared base, so a transport failure after the write carries it
- [ ] 3.2 Make `_restore_cmgf_unlocked` catch the shared base, so a failure inside the `finally` cannot replace the exception already propagating
- [ ] 3.3 Test **at the `ATSerial` level**: a transport failure raised after the Ctrl-Z write carries the written-bytes flag — testing this only at the manager level passes trivially against a hand-built exception
- [ ] 3.4 Test: a transport failure raised inside the state restore leaves the original failure and its flag intact

## 4. The recovery ladder

- [ ] 4.1 Add a `TRANSPORT` cause and a `link_lost` observation to `ModemHealth.decide()`, keeping it free of I/O
- [ ] 4.2 Make the failure threshold per-cause in `ModemHealth.__init__` rather than one shared count, with transport acting on the first observation
- [ ] 4.3 Map `(cause, level)` to an action in the caller: for transport, the gentle level stops using the link and the blunt level exits — no radio cycle, no modem reset
- [ ] 4.4 Catch `ModemTransportError` in `_watchdog_step` and feed it to `decide()` instead of letting it escape
- [ ] 4.5 Make a poll that could not be completed count as a failed poll
- [ ] 4.6 Make `_recover()` treat a remedy it could not carry out as attempted so the ladder proceeds; same for `hard_reset()` meeting a dead port
- [ ] 4.7 Test the ladder as a history table: transport escalates on its own cause and threshold, and a change of cause restarts it as it already does for registration versus stall
- [ ] 4.8 Test: with a dead port the ladder reaches the service-exit level rather than looping — the regression that caused the incident
- [ ] 4.9 Make a lost link act even when `modem_watchdog_enabled` is false, since `watchdog_loop` skips the step entirely today; give it its own switch if one is wanted
- [ ] 4.10 Let the send path's observation of a lost link start the response rather than waiting for the next 60-second poll
- [ ] 4.11 Test: the watchdog disabled and the link lost still produces a response

## 5. The send path

- [ ] 5.1 Decide the hold **before** `begin_message_attempt` claims the message, so no attempt is counted and no schedule is cleared; if a hold is unavoidable after that point, restore both
- [ ] 5.2 Hold only when no byte has been written **and** no part has been accepted; otherwise fail, whatever the classification
- [ ] 5.3 Revisit the nine `except ATCommandError` sites — `manager.py` in `_send_one`, the inbound path, `scan_inbox` (two), `keepalive_loop`, `collect_diagnostics`; `at_commands.py` in `_restore_cmgf_unlocked`, `registration_state`, `hard_reset`. Three decide on the distinction, six widen to the shared base
- [ ] 5.4 Check `_failed()`, which calls `_drain()` while building an `ATCommandError`: a transport failure there changes the class the caller receives
- [ ] 5.5 Test: a link lost before transmission leaves the message `pending`, attempt count unchanged, with a schedule that brings it back, and emits no `failed` webhook
- [ ] 5.6 Test: a link lost after the PDU was written fails the message at once and schedules no retry
- [ ] 5.7 Test: a link lost between the parts of a multipart message fails it rather than holding it
- [ ] 5.8 Test: a message held for a lost link still reaches `failed` at the pending deadline and its app is notified once
- [ ] 5.9 Test: a registration query failing with an AT error against a usable link still attempts the message

## 6. Startup and restart limits

- [ ] 6.1 Make `connect()` at startup wait for the device on the same bounded terms as any other lost link, tolerating both a missing node and a permission error while udev applies its rules
- [ ] 6.2 Choose the bound together with `RestartSec` and `StartLimitBurst` in `deploy/sms-gate.service`, so an exit followed by a slow re-enumeration cannot stop the unit permanently
- [ ] 6.3 Test: a device absent at startup is waited for and the service starts when it appears
- [ ] 6.4 Test: a device that never appears exits within the bound rather than hanging startup

## 7. Loop supervision

- [ ] 7.1 Replace `asyncio.gather(*tasks, return_exceptions=True)` with per-task supervision that logs the traceback and alerts
- [ ] 7.2 Exclude cancellation during shutdown from being treated as a death — no alert, no exit, and do not read the exception off a cancelled task
- [ ] 7.3 Make essential loops exit the service when they die; `reader_loop` alerts and exits on a lost link rather than reconnecting
- [ ] 7.4 Drain pending notifications, within a bound, before any deliberate exit
- [ ] 7.5 Record a notification that cannot be queued or cannot be delivered, instead of dropping it silently
- [ ] 7.6 Test: a raising background loop produces a logged traceback and an alert
- [ ] 7.7 Test: an orderly shutdown produces no alert and no exit, and closes the modem and the database
- [ ] 7.8 Test: the alert explaining a fatal exit is delivered before the process ends

## 8. Verification and ship

- [ ] 8.1 Full test suite green
- [ ] 8.2 Live verification: re-enumerate the modem deliberately (`AT+CFUN=1,1`) and confirm the gateway escalates, exits, restarts unattended, comes back with `CNMI` intact, drains the inbox, and delivers inbound
- [ ] 8.3 Confirm the restart limits hold: the gateway must recover without the unit reaching its start limit
- [ ] 8.4 Ship and verify against prod
- [ ] 8.5 Archive so `openspec/specs/` carries `modem-link`, `service-runtime` and the `outbound-send` deltas
