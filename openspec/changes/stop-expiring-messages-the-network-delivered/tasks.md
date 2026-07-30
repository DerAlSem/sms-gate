## 1. The sweep learns the difference

- [x] 1.1 Split the expiry sweep in two: messages with no part ever confirmed, and messages with at least one confirmed and none failed
- [x] 1.2 Complete the second group as `delivered`, recording that the status was concluded rather than reported — an operator chasing "the customer says they never got it" needs to know how solid the `delivered` is
      <!-- A `delivery_inferred` column, and the ordering does the rest: completing runs
           before the expiry sweep and takes those messages out of `sent`, so the sweep never
           sees them and needed no change at all. -->
- [x] 1.3 Leave the first group expiring exactly as before; silence about everything is not evidence of anything
- [x] 1.4 Leave a message with a failed part alone — that path is not a timeout question and already has an answer

## 2. Tests, before the code

- [x] 2.1 Test: one part of two confirmed, none failed, timeout reached → `delivered`, and the record says it was inferred
- [x] 2.2 Test: no part confirmed, timeout reached → `expired`, unchanged
- [x] 2.3 Test: a part reported failed → the timeout does not turn it into a delivery
- [x] 2.4 Test: every part confirmed → `delivered` as before, and *not* marked inferred — the distinction is worthless if the ordinary path also carries it
- [x] 2.5 Test: a single-part message with no report → `expired`, so the change cannot quietly rescue the case it was never about

## 3. The webhook says the conclusion

- [x] 3.1 Notify `delivered` for a message completed by inference, and do not notify `expired` for it
- [x] 3.2 Test: exactly one notification, and it is `delivered`
      <!-- The census test in test_delivery_hooks caught the new status writer before I
           wired its webhook, which is exactly what it exists for. -->
- [x] 3.3 Test: the late-report correction path still sends `expired` then `delivered`, because that one is a genuine correction after the fact rather than a decision the gateway could have made in time

## 4. Evidence it worked

- [x] 4.1 Report how many historical messages would have been completed rather than expired, from the existing data
      <!-- Twenty-two. Each one was a delivery reported to its owner as a failure. -->
- [ ] 4.2 Live: send a two-part message to a number on the operator that reports once, and confirm it ends `delivered` with one webhook
- [ ] 4.3 Live: confirm a single-part message to an unreachable number still expires

## 5. Ship

- [x] 5.1 Full test suite green
- [x] 5.2 Changelog entry saying plainly that messages were reported failed while arriving
- [ ] 5.3 Ship and verify against prod
- [ ] 5.4 Archive so the modified requirements land in `openspec/specs/`
