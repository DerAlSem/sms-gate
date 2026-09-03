# SMS Gate — Implementation Notes

Important details for developers that are not obvious from the rest of the documentation.

---

## Serial Port — Single Writer

The modem accepts only one command at a time. Sending an SMS and reading a delivery report cannot happen simultaneously — they share the same serial port.

**Solution**: use `asyncio.Lock` for writes to the port. The background reader listens continuously, but when an SMS needs to be sent the reader yields the lock, the sender sends, and then releases it.

```python
class ModemManager:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._queue = asyncio.Queue()

    async def send_sms(self, phone, text):
        async with self._lock:
            # Send AT+CMGS and wait for response
            ...

    async def reader_loop(self):
        while True:
            # Read available bytes (non-blocking, without lock)
            # Lock only needed for writing
            line = await self._read_line()
            if line.startswith("+CDS:"):
                self._handle_delivery(line)
```

---

## modem_ref Collision

`AT+CMGS` returns a reference in the range 0–255, then wraps around. At this
gateway's volume it repeats roughly every three weeks — measured, not assumed:
across 1765 messages the reference decreases eight times, seven of them exactly
`255 -> 0`. The counter wraps; it has never been observed to restart.

A reference alone therefore does not identify a message, and "the most recent
`sent` message with that ref" is not a solution — a report that arrives late,
which is the normal case for a permanent failure, lands on whichever message
holds the reference *now*.

**What the gateway does instead** (`app/modem/attribution.py`): every part
carrying the reference is collected, unfiltered, and then graded.

1. A part whose message is already finished, or whose status a report has
   already set, is `superseded` — ordinary traffic, recorded and silent.
2. A part older than `delivery_report_max_age_hours` (default 168) is outside
   the window. A part whose submit time is unknown counts as *inside* it:
   unknown is not old, and a NULL compared in SQL answers "does not qualify",
   which fails closed in a rule that must fail open.
3. A part addressed to a different number than the report names is
   `contradicted`. Numbers are compared by their last ten significant digits —
   not by canonicalizing, which needs a region and can turn a national-format
   address into a *different valid* number. This is the only rule that can
   refuse a delivery, so it is the only one behind a switch
   (`delivery_report_strict_attribution`, default off).
4. Of what survives: one candidate wins outright; several are separated by
   whichever submit time is nearest the report's `scts`; a remaining tie falls
   to the most recent, and a report attributed that way does **not** count
   toward the destination's blacklist. An irreversible penalty may not rest on a
   tiebreak.

The filters are applied in code rather than in the `WHERE` clause on purpose: a
query that discards the rows cannot say what it excluded, and "one match, too
old" would be recorded as "nothing matched". Every report and every candidate
considered is written to `delivery_reports`.

---

## Expired Messages

A background task runs every 60 seconds:

```python
async def expire_stale_messages():
    while True:
        await asyncio.sleep(60)
        await db.execute("""
            UPDATE messages
            SET status = 'expired'
            WHERE status = 'sent'
              AND sent_at < datetime('now', '-5 minutes')
        """)
```

---

## Phone Number Validation

Phone numbers are validated with the `phonenumbers` library and normalized to E.164.
The validation country is controlled by the `phone_region` soft setting (default `RU`,
editable at `/admin/settings`).  For inbound-reply paths the region check is relaxed so
that existing numbers stored in the DB are not re-validated against the current region.

**Operator/region lookup** (voxlink) is **RF-only**: gated to `+7` numbers.
Non-`+7` numbers are accepted and sent normally but `operator` and `region` will be empty.

---

## Graceful Shutdown

When the service stops:
1. Stop accepting new requests
2. Wait for the current SMS to finish sending (if one is in progress)
3. Close the serial port
4. Close the SQLite connection

The FastAPI lifespan handler takes care of this automatically via `yield`.

---

## Logging

Use the standard `logging` module. Log levels:
- `INFO` — startup, each SMS sent, each delivery report
- `WARNING` — delivery timeout, modem slow response
- `ERROR` — modem error, serial port lost

Format:
```python
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
```

systemd + journalctl will capture stdout/stderr automatically.

---

## Cyrillic in SMS

Outbound SMS is sent in **PDU mode** (`AT+CMGF=0` per send). The encoder
(`app/modem/pdu_encode.py`) chooses the alphabet automatically:

- **GSM 7-bit** when every character fits the GSM default alphabet (up to 160
  chars single / 153 per concatenated part).
- **UCS2** (UTF-16) otherwise — this is what carries Cyrillic and emoji (up to
  70 chars single / 67 per concatenated part).

Long messages are split into **UDH-concatenated** parts (8-bit reference =
`message_id % 256`), so the recipient's handset reassembles them into one
message. UCS2 splits never sever a surrogate pair; GSM7 splits never sever an
escape sequence. Each part is sent with its own `AT+CMGS` and tracked in the
`message_parts` table, keyed on `(message_id, seq)` and carrying that segment's
own submit time; the message becomes `delivered` only once every part's `+CDS`
report arrives — and a message with no part records at all is *not* treated as
having every part delivered. The `max_sms_parts` setting (default 6) caps length;
longer text fails before anything is transmitted.

Shared GSM7 alphabet tables live in `app/modem/gsm7.py` (used by both the
encoder and the inbound decoder in `app/modem/pdu.py`).

---

## Testing Without a Modem

For development without a physical modem, create a `MockModemManager` with the same interface:
- `send_sms()` → immediately returns a random ref and sets status=sent
- `reader_loop()` → 2 seconds after send, changes status to delivered

Switch via env var:
```env
MODEM_MOCK=true
```
