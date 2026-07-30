## 1. The sweep learns the difference

- [ ] 1.1 Split the expiry sweep in two: messages with no part ever confirmed, and messages with at least one confirmed and none failed
- [ ] 1.2 Complete the second group as `delivered`, recording that the status was concluded rather than reported — an operator chasing "the customer says they never got it" needs to know how solid the `delivered` is
- [ ] 1.3 Leave the first group expiring exactly as before; silence about everything is not evidence of anything
- [ ] 1.4 Leave a message with a failed part alone — that path is not a timeout question and already has an answer

## 2. Tests, before the code

- [ ] 2.1 Test: one part of two confirmed, none failed, timeout reached → `delivered`, and the record says it was inferred
- [ ] 2.2 Test: no part confirmed, timeout reached → `expired`, unchanged
- [ ] 2.3 Test: a part reported failed → the timeout does not turn it into a delivery
- [ ] 2.4 Test: every part confirmed → `delivered` as before, and *not* marked inferred — the distinction is worthless if the ordinary path also carries it
- [ ] 2.5 Test: a single-part message with no report → `expired`, so the change cannot quietly rescue the case it was never about

## 3. The webhook says the conclusion

- [ ] 3.1 Notify `delivered` for a message completed by inference, and do not notify `expired` for it
- [ ] 3.2 Test: exactly one notification, and it is `delivered`
- [ ] 3.3 Test: the late-report correction path still sends `expired` then `delivered`, because that one is a genuine correction after the fact rather than a decision the gateway could have made in time

## 4. Evidence it worked

- [ ] 4.1 Report how many historical messages would have been completed rather than expired, from the existing data
- [ ] 4.2 Live: send a two-part message to a number on the operator that reports once, and confirm it ends `delivered` with one webhook
- [ ] 4.3 Live: confirm a single-part message to an unreachable number still expires

## 5. Ship

- [ ] 5.1 Full test suite green
- [ ] 5.2 Changelog entry saying plainly that messages were reported failed while arriving
- [ ] 5.3 Ship and verify against prod
- [ ] 5.4 Archive so the modified requirements land in `openspec/specs/`
