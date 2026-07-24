## Why

A message attempted while the modem is off the network fails for a reason that has
nothing to do with the message. Prod 2026-07-24: registration dropped for about three
minutes, message 976 was attempted at 17:39:59, and part 1 of a two-part SMS had already
been accepted when part 2 timed out. That message can never be retried automatically —
resending would deliver part 1 twice — so it needed a human.

**The measured scale is small, and worth stating plainly.** Registration was lost four
times in thirty days, and never for long enough to reach even a soft recovery, so roughly
ten minutes of outage a month. At 12.8 messages a day, most outages contain no message at
all. This is worth single-digit messages a year.

What makes it worth doing anyway is *which* messages. Retries already recover a send that
never reached the modem. The one class they cannot recover is a multipart whose first
part was accepted — and that class is created precisely by starting a send into a network
that is about to refuse it. Not starting is the only fix.

## What Changes

- Before transmitting, the gateway asks the modem whether it is registered, and holds the
  message back if it is definitively not.
- **The check is made fresh, at send time.** An earlier sketch of this change was rejected
  for leaning on the watchdog's once-a-minute sample — deciding not to send on
  minute-old information. One `AT+CEREG?` inside the serial session the send needs anyway
  removes that objection entirely, at a cost of one command per message on a gateway that
  sends about thirteen a day.
- A held message consumes **no attempt**: it was never offered to the network, so it
  should lose time, not chances — the same rule the recovery gate already follows.
- A check that *fails* is not a refusal. Only a definitive "not registered" holds a
  message; an error or a timeout means we do not know, and not knowing must not stop the
  gateway sending.
- Holding is bounded by the existing pending deadline. A message the gateway declines to
  attempt still becomes `failed` once it is too old, so declining can never become silent
  indefinite retention.

## Impact

- `app/modem/manager.py` — one check in the send path, and a short reschedule when it
  says no.
- No schema change, no API change, no new status. `send_retry_backoff` and the pending
  deadline already bound the behaviour.

## Not in this change

- Acting on the watchdog's registration sample. It is stale by up to a minute and exists
  to decide recovery, not to gate individual sends.
- Holding back for anything other than registration — signal quality, operator, SMSC
  address. Each would need its own evidence that it predicts failure.
