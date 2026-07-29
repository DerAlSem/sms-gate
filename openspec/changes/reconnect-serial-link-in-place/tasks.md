## 1. Reopening the port

- [x] 1.1 Add `_init_unlocked()` alongside the existing `_*_unlocked` helpers, so the init sequence can run while the caller already holds the serial lock
- [x] 1.2 Add `reconnect()`: hold the lock across close, open and `_init_unlocked()` as one indivisible act; a failing init makes the attempt fail
- [x] 1.3 Bound each attempt in time as well as bounding their number — `wait_closed()` on a vanished device and `open()` on a node udev has not finished can both block
- [x] 1.4 Treat an absent node and a permission error alike as "not back yet"
- [x] 1.5 Fix the budget against `_RECOVERY_TIMEOUT` (300 s), not `_SEND_GATE_TIMEOUT`; target roughly 30 s worst case
- [x] 1.6 Guarantee that every exit path, including cancellation, leaves the link either fully usable or explicitly unusable
- [x] 1.7 Test: reopen re-runs the full init sequence including the URC subscription
- [x] 1.8 Test: a reopen holding the lock does not deadlock on init — the regression this task group exists to prevent
- [x] 1.9 Test: a missing node, then a permission error, then success across successive attempts
- [x] 1.10 Test: a cancelled reopen leaves the link marked unusable and the next send fails immediately rather than timing out

## 2. The remedy becomes reopen-then-restart

- [x] 2.1 Make the transport cause's gentle level reopen the link, keeping the blunt level as the service exit
- [x] 2.2 Run the reopen behind the recovery gate, and resume sending whether it succeeded or failed
- [x] 2.3 Test: sending stays suspended for the duration of a reopen and resumes even when the reopen raises
- [x] 2.4 Test: exhausted attempts still reach the service exit

## 3. Reconciliation with the modem's memory

- [x] 3.1 Scan the modem's stored messages after a link is restored in place, as startup does
- [x] 3.2 Do not rely on indexes queued before the outage in place of the scan
- [x] 3.3 Add a deduplication key so a re-read message is not delivered to the application twice, with its migration and back-compat
- [x] 3.4 Test: inbound arriving during an outage is delivered after a reopen, without a restart
- [x] 3.5 Test: a message persisted but not deleted before the link died is not delivered twice by the next scan

## 4. The unsolicited-result port

- [x] 4.1 Recover the read port through the shared mechanism rather than an independent loop, waiting on the recovery gate before any attempt
- [x] 4.2 Settle whether the read port needs its own init sequence given it has no writer (design open question)
- [x] 4.3 Test: a re-enumeration taking both ports produces one coordinated recovery, not two
- [x] 4.4 Test: the read port does not reopen during the settling period after a deliberate hard reset

## 5. Visibility

- [x] 5.1 Add link state, last-known-good time and reopen count to the health snapshot
- [x] 5.2 Show them on the diagnostics page
- [x] 5.3 Test: the snapshot reports a lost link

## 6. Verification and ship

- [x] 6.1 Full test suite green
- [ ] 6.2 Live verification: re-enumerate the modem (`AT+CFUN=1,1`) and confirm the gateway recovers **without restarting**, with `CNMI` intact
- [ ] 6.3 Live verification of the case this change is most likely to break: send an SMS to the gateway while the link is down, and confirm it is delivered after the reopen without a restart
- [ ] 6.4 Ship and verify against prod
- [ ] 6.5 Archive so the `modem-link` additions land in `openspec/specs/`
