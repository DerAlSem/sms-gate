## Why

The gateway reports messages as `expired` that the recipient received in full.

It requires a delivery report for **every** part before calling a multipart message
delivered. One network on this SIM sends a report for the last segment only, so those
messages never complete, sit until the timeout, and are swept to `expired` — carrying that
status to the owning application over the webhook.

Measured on live data: on that operator, single-part messages are 180 delivered and 0
expired, while two-part messages are 1 delivered and 21 expired. On every other operator
multipart is unremarkable. Four test messages sent to a consenting recipient reproduced it
exactly — one report each, always for the final segment — and the recipient confirmed all
four arrived whole.

So twenty-one reports of failure describe deliveries that happened.

## What Changes

- **A message whose parts are partly confirmed and none failed is `delivered`, not
  `expired`.** The change is confined to the moment the timeout fires — the point at which
  the current rule is already known to be guessing — and leaves the ordinary path untouched.
- **The inference is recorded rather than hidden.** A message completed this way is
  distinguishable afterwards from one every part confirmed, because "we were told" and "we
  concluded" are different facts and only one of them should be trusted without question.
- A message with **no** part confirmed still expires. Absence of any report is absence of
  evidence, and inventing a delivery from it would replace a wrong `expired` with a wrong
  `delivered`.
- A message with a part reported **failed** is unaffected: that path already moves the
  message to failed and is not a timeout question.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `outbound-send`: the rule that a message is delivered only when every part is reported.
  It is true as a description of the reports the gateway would like, and false as a
  description of what networks send.
- `delivery-dispatch`: the webhook consequence. The scenario that says a partly-reported
  multipart message sends no `delivered` notification stays true until the timeout, and
  stops being true at it.

## Impact

- `app/db/queries.py` — the sweep that selects messages to expire, and how a message
  completed by inference is recorded.
- `app/modem/manager.py` — the expiry loop, which currently dispatches `expired`
  unconditionally for whatever the sweep returned.
- The webhook contract gains no new status. An application already handling `delivered`
  needs no change; one that had learned to treat `expired` as normal for its Beeline users
  will simply stop seeing it.

## Depends on

Nothing. It is a narrowing of an existing rule, with the evidence for narrowing it already
collected.
