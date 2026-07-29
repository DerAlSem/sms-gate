## 0. Test harness

- [x] 0.1 Allow the script's config block to be overridden from the environment (`DEVICE`, `IFACE`, `STATE_DIR`, `MAIN_IFACE`), keeping `/etc/default/wwan-backup` authoritative over both — without this nothing about the script is testable off the server
- [x] 0.2 Add `tests/test_wwan_backup.sh` following the `test_notify_telegram.sh` convention: stub `qmicli`, `ip`, `resolvectl`, `logger` and `ping` on `PATH`, driven by env, each recording its invocations so a test can assert what was asked of it
- [x] 0.3 Make the stub `qmicli` able to answer, refuse, and time out independently per subcommand, since the whole change turns on telling those three apart

## 1. Session establishment

- [x] 1.1 `cmd_up` starts the session from the modem's default profile instead of passing `apn=$APN,ip-type=4`
- [x] 1.2 Keep `APN` as an override: when it is set explicitly in `/etc/default/wwan-backup`, use it; otherwise use the profile
- [x] 1.3 Fix `session_connected()` so an established session is reported as present and the idempotent path is taken
- [ ] 1.4 Verify on the live server: with no session present, a cold start succeeds on the first attempt

## 2. Client handling

- [x] 2.1 Acquire the QMI client once, record it in `$STATE_DIR`, and reuse it across attempts rather than acquiring one per attempt
- [x] 2.2 Make `cmd_down` tear down using the recorded client and clear it, so a stale id is never reused across a re-enumeration
- [x] 2.3 Verify: repeated failed attempts do not advance the client id

## 3. Duty separation

- [x] 3.1 Make the session path in `cmd_watchdog` return rather than `exit`, so a QMI failure does not abort the run — `cmd_up`'s own `exit 1` calls are what currently defeat the `||` guard
- [x] 3.2 Verify: with session establishment failing, `fails`/`oks` still advance and failover still triggers when the primary is down

## 4. Bounded retrying

- [x] 4.1 Count consecutive failures in `$STATE_DIR`, stop retrying on the normal schedule at the bound, and reset on success
- [x] 4.2 Alert the operator on reaching the bound, and make the stopped state visible in `cmd_status`
- [x] 4.3 Choose the bound against the 30-second timer cadence (design open question)

## 5. Renewing access to the device

- [x] 5.1 Distinguish a request that timed out from one that was refused — only the former counts toward staleness
- [x] 5.2 After several consecutive timeouts, renew access including restarting `qmi-proxy`, then re-acquire the client
- [x] 5.3 Bound renewal by the same allowance as any other retry, so it cannot loop
- [x] 5.4 Verify: a `no-service` refusal does not restart the proxy

## 6. Interface presence

- [x] 6.1 Confirm `/sys/class/net/$IFACE` exists before bringing the interface down, setting `raw_ip`, or applying addressing, as `$DEVICE` already is
- [x] 6.2 Report a missing interface rather than proceeding, so addressing is never applied into nothing

## 7. Ship

- [ ] 7.1 Deploy from merged `main` through the normal path
- [ ] 7.2 Live verification of 1.4, 2.3, 3.2 and 5.4 against the production modem
- [ ] 7.3 Re-enable `wwan-watchdog.timer`, stopped since 2026-07-29, and confirm one clean cycle
- [ ] 7.4 Archive the change so `openspec/specs/backup-uplink` becomes the living spec
