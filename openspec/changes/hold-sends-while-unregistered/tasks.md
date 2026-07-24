## 1. The check

- [ ] 1.1 A registration probe that distinguishes "not registered" from "could not tell",
      unlike `registration_ok()`, which folds both into False for the watchdog's benefit.
- [ ] 1.2 Consult it in the send path before claiming the message, so a held message
      consumes no attempt.
- [ ] 1.3 Reschedule a held message with a short delay and log the hold.
- [ ] 1.4 Tests: a definitive negative holds and does not count an attempt; registration
      restored sends normally; a failing check attempts rather than holds; a multipart is
      not partially transmitted during an outage; the pending deadline still terminates a
      message held through a long outage.

## 2. Verify and ship

- [ ] 2.1 Full suite green.
- [ ] 2.2 Conformance sweep of the `outbound-send` SHALLs about attempts and deadlines.
- [ ] 2.3 Docs: README, `CHANGELOG.md`, version bump.
- [ ] 2.4 Deploy with the owner's confirmation, then a real send.

## 3. Out of scope

- Holding for signal quality, operator or SMSC address; each needs its own evidence that
  it predicts failure.
- Any new setting: the pending deadline and the backoff already bound this.
