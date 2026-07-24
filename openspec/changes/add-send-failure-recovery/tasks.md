## 1. The stall signal

- [ ] 1.1 Track distinct message ids that failed transiently since the last successful
      send, on `ModemManager`. A permanent failure and a pre-modem rejection touch it not
      at all; a success clears it.
- [ ] 1.2 `_watchdog_step` treats a stall as a failed health check, alongside a failed
      registration poll, with no change to escalation, cooldown or exit.
- [ ] 1.3 `watchdog_loop` clears the evidence when the watchdog is disabled.
- [ ] 1.4 Tests: three distinct messages stall; one message's four attempts do not; a
      success clears; permanent failures are neutral; disabled watchdog is inert; the
      escalation order and the hard-reset cooldown are unchanged.

## 2. The quiesce gate

- [ ] 2.1 An event on `ModemManager` meaning "sending allowed", closed by the watchdog
      around recovery and reopened after, including on the error path.
- [ ] 2.2 The sender waits on it **before** claiming a message, so a held message consumes
      no attempt; the wait is bounded by a timeout after which it proceeds.
- [ ] 2.3 Tests: a message due during recovery is not transmitted and its attempt count is
      unchanged; it goes out once recovery finishes; a gate that never opens does not hold
      the sender forever; the gate reopens even if recovery raises.

## 3. Verify and ship

- [ ] 3.1 Full suite green.
- [ ] 3.2 Mini conformance sweep of the `outbound-send` SHALLs about recovery and sending.
- [ ] 3.3 Docs: README behaviour note, `CHANGELOG.md`, version bump.
- [ ] 3.4 Deploy with the owner's confirmation, then confirm the loops start clean and a
      real send still works.

## 4. Deliberately out of scope

- Holding sends back while the modem is merely known-unregistered. Would have saved prod
  message 976, but acts on once-a-minute sampling and risks stranding traffic through a
  long outage; needs its own bound and its own change.
- Alerting the operator when a stall is declared. Worth having, but the alert vocabulary
  is a separate conversation — the log line is the floor.
