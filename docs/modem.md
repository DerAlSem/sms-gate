# SMS Gate — Modem Integration (Quectel EP06E)

## Serial Port

The modem exposes 4 `/dev/ttyUSB*` ports (ttyUSB0–ttyUSB3). Confirmed port assignments:
- **ttyUSB2** — AT command port (sending: AT+CMGS and other commands)
- **ttyUSB3** — unsolicited responses (+CDS delivery reports arrive here)

These are two separate serial connections in the app. No asyncio.Lock needed between them since they're independent.

Detect with:
```bash
ls -la /dev/ttyUSB*
# or more reliably:
dmesg | grep ttyUSB
```

Serial settings: `115200 8N1` (baud 115200, 8 data bits, no parity, 1 stop bit).

---

## Initialization Sequence

Run these AT commands on startup, in order:

```
AT                          # Check modem alive → expect "OK"
ATE0                        # Disable echo
AT+CMGF=1                  # Default text mode; sends/reads toggle to PDU (CMGF=0) per operation
AT+CSCS="GSM"              # Text-mode charset default; outbound now uses PDU mode (encoding chosen per message)
AT+CNMI=2,1,2,1,0          # Enable delivery report notifications
AT+CSMP=49,167,0,0         # Request delivery reports on send
```

### AT+CNMI=2,1,2,1,0 explained

| Param | Value | Meaning |
|-------|-------|---------|
| mode | 2 | Buffer unsolicited results, flush when possible |
| mt | 1 | Incoming SMS → +CMTI notification (not full content) |
| bm | 2 | CBM → route to TE |
| ds | 1 | **Delivery reports → +CDS sent directly to TE** |
| bfr | 0 | Flush buffer on mode change |

The key param is `ds=1` — this makes the modem send `+CDS` lines when delivery reports arrive.

### AT+CSMP=49,167,0,0 explained

First param `49` = bits: `00110001`
- Bit 5 = 1: Status Report Request enabled (tells network we want delivery reports)
- Bits 0-1 = 01: SMS-SUBMIT

Without this, the network won't generate delivery reports even if the modem is listening.

---

## Sending an SMS

> **Note:** Outbound sending now uses **PDU mode** (`AT+CMGF=0`), with the
> encoding chosen automatically per message (GSM 7-bit when the text fits the
> GSM alphabet, otherwise UCS2) and UDH multipart concatenation for long text.
> The text-mode flow below is kept for reference.

```
AT+CMGS="+79991234567"      # Start send, modem responds with "> "
Your code: 4821\x1a          # Message text + Ctrl+Z (0x1A) to send
```

Response on success:
```
+CMGS: 42                    # 42 = message reference number

OK
```

Response on error:
```
+CMS ERROR: 500              # or similar error code
```

### Implementation Notes

1. Write `AT+CMGS="phone"\r` to serial
2. Wait for `>` prompt (timeout 5s)
3. Write `message_text` + `\x1a`
4. Wait for `+CMGS: <ref>` or `+CMS ERROR` (timeout 30s — network can be slow)
5. Parse reference number, record it against `(message_id, seq)` in
   `message_parts` with that segment's own submit time, set status = `sent`
6. On error → set status = `failed`, save error text

---

## Receiving Delivery Reports

After `AT+CNMI` setup, the modem sends unsolicited lines like:

```
+CDS: 25
07...PDU_DATA...
```

Or in text mode:
```
+CDS: 6,42,"+79991234567",145,"26/04/17,12:00:01+12","26/04/17,12:00:03+12",0
```

Text mode format: `+CDS: fo,mr,ra,tora,scts,dt,st`

| Field | Meaning |
|-------|---------|
| fo | First octet |
| mr | **Message Reference** — matches `+CMGS` ref |
| ra | Recipient address (phone) — **used**: it eliminates a candidate it contradicts |
| tora | Type of recipient address |
| scts | Service Centre Time Stamp of the original submit — **used**: it orders candidates. `YY/MM/DD,hh:mm:ss` plus an offset in **quarter-hours**, so `+12` is UTC+03:00, not UTC+12:00 |
| dt | Discharge Time (when delivered) |
| st | **Status** — 0 = delivered, >0 = error/pending |

### Status Values (st field)

GSM 03.40 §9.2.3.15 splits the byte into **four** ranges, and the two temporary ones are
not interchangeable — they disagree about whether the service centre will try again:

| Range | Class | What it means for us |
|-------|-------|----------------------|
| `0x00–0x1F` (0–31) | completed | delivered |
| `0x20–0x3F` (32–63) | temporary, SC **still trying** | a verdict is still owed; not a failure yet |
| `0x40–0x5F` (64–95) | permanent, SC stopped | failed, and counts toward the destination's blacklist |
| `0x60–0x7F` (96–127) | temporary, SC **stopped** | failed at once, but **never** counts toward the blacklist — the cause is the network's |

Common values:

| st | Range | Meaning |
|----|-------|---------|
| 0 | completed | delivered successfully |
| 1 | completed | forwarded, no delivery confirmation |
| 32 | temporary, still trying | congestion |
| 33 | temporary, still trying | recipient busy |
| 64 | permanent | remote procedure error |
| 65 | permanent | incompatible destination |
| 70 | permanent | message validity period expired |
| 96 | temporary, stopped | congestion |
| 99 | temporary, stopped | service rejected — the most common failure this gateway sees |

**Key logic**: `st == 0` → `delivered`, save `delivered_at`. `st >= 64` → `failed`. The
blacklist is the part that is easy to get wrong: only `0x40–0x5F` may count toward it
(`_is_permanent_status`), because a `0x60–0x7F` failure says nothing bad about the
destination. Do not reach for the word "temporary" to make this decision — `_tp_status_class`
returns it for both temporary ranges. Use the range.

---

## Background Serial Reader

The modem manager must run a **continuous background reader** on the serial port:

```python
# Pseudocode
async def serial_reader():
    while True:
        line = await read_line_from_serial()  # non-blocking
        if line.startswith("+CDS:"):
            parse_delivery_report(line)
            update_message_status_in_db()
        elif line.startswith("+CMTI:"):
            pass  # incoming SMS, ignore for now
        # other unsolicited responses...
```

Use `pyserial-asyncio` for non-blocking serial I/O that integrates with FastAPI's event loop.

---

## Serial Port Locking

Only one process can open the serial port. Opening it is **not** part of startup: the gateway
serves HTTP first and a background linker brings the link up, so a port that cannot be opened
never stops the service or the admin console.

1. The linker tries to open both ports and run the init sequence
2. `FileNotFoundError` (no node) and `PermissionError` (node recreated, udev has not applied
   ownership yet) both mean "not back yet" — log, wait, try again. Neither ends the process
3. Attempts continue for as long as the process runs, backing off to a ceiling; the health
   snapshot reports the link as not detected meanwhile
4. Consider using `/var/lock/LCK..ttyUSB2` lockfile (standard UUCP convention)

---

## Voice Route (IMS / VoLTE)

The module can be reached by an incoming voice call only while IMS is up. This was switched
on by hand on **2026-09-18** and there was no written way back until this section existed.

### Reading it

```bash
AT+QCFG="ims"       # +QCFG: "ims",<IMS_conf>,<VoLTE_cap>
```

Vendor reference: *Quectel LTE-A(Q) Series IMS Application Note V1.0* (2021-08-18), §2.3.1;
§1.1 lists EP06 Series. Maximum response time 300 ms — it answers out of the module's own
memory, no network round-trip.

| field | value | meaning |
|---|---|---|
| `<IMS_conf>` | `0` | **factory position** — whether IMS is enabled is decided by the carrier profile (MBN) on the module |
| | `1` | enable IMS compulsorily — **what this gateway sets** |
| | `2` | disable IMS compulsorily |
| `<VoLTE_cap>` | `0` | VoLTE not available |
| | `1` | VoLTE available |

⚠️ **`0` is not "off".** A module reading `0,1` has a working voice route supplied by its
profile. A module reading `0,0` — which is what this one read before 2026-09-18 — has a
profile that does not enable VoLTE. Neither means somebody switched IMS off; that is `2`.

⚠️ **`<VoLTE_cap>` reads `0` on a module that is not registered to the network**, whatever
the truth would be. After `AT+CFUN=1,1` this module sat outside the network for about three
minutes reading `0` throughout. Read it only on a registered module.

⚠️ **The vendor does not say the second field is the carrier's verdict.** Its parameter table
calls it the capability of VoLTE; its prose (§1.3.1) calls it the IMS registration status.
Do not tell an operator the carrier refused us — nothing here reads that.

### Turning it on

```bash
AT+QCFG="ims",1
AT+CFUN=1,1
```

The setting is saved automatically and survives a power cycle (§2.3.1, *Characteristics*).
It takes effect only after the reboot, so `AT+CFUN=1,1` is not optional.

🔴 **Writing it costs a service stop.** The command port is held by `sms-gate`, so the write
means stopping the unit, and this gateway carries live customer traffic. Reading is free
once the gateway asks for it as part of its own sweep.

### Rolling it back

```bash
AT+QCFG="ims",0
AT+CFUN=1,1
```

**Use `0`, not `2`.** `0` restores the state the module was in before 2026-09-18 — the
profile decides. `2` pins IMS off against any future profile, which is a *different* state
from the one being rolled back to and would silently outlive the reason for the rollback.

**When to roll back.** The one risk this switch carries is that IMS may take SMS delivery off
the circuit-switched path — the application note documents SMS over IMS (§1.3.2.2) and the
`+g.3gpp.smsip` capability in the IMS registration, so the mechanism is real. Judge it by
**inbound messages continuing to arrive**, not by a test send and not by a delivery report.

Seven inbound messages arrived in the two days after the switch (first ≈90 minutes after it),
so no harm is visible so far. The window runs to **2026-10-18**, watched by registry row
`sms-gate-ec2f9e87/20260918-03`. Harm here is an *absence*, which no probe can catch — if
inbound messages have stopped while outbound traffic is still healthy, roll back.

### Losing it without anyone touching it

§1.2.1 of the application note: an MBN activated or deactivated **restores an NV item written
by AT command to the profile's default**. §1.2.3: the MBN is selected automatically from the
SIM's IMSI. §1.2.2: *"not all operator MBN files enable IMS by default"*.

**Changing the SIM can therefore disarm the voice route silently**, with no reboot ordered by
us and nothing in the journal saying so. If the SIM is swapped, read `AT+QCFG="ims"`
afterwards and write `1` again if it has moved.

### When an alert arrives

The gateway reads `AT+QCFG="ims"` once per watchdog tick and alerts on three conditions.
They are three different notifications on purpose: they ask for three different things, and
two of them are not about the same half of the reading.

An alert may reach somebody who was not here in September 2026 and has never run the
measurement. Each one below says what to look at first and what to do.

| alert | what the gateway saw | what to do |
|---|---|---|
| ⚙️ **IMS configuration** | `<IMS_conf>` is no longer `1` | Somebody or something moved the setting. Open `/admin/modem`, read the `ims` row. Write it back — *Turning it on* above — which costs a service stop and a module reboot. **First ask whether the SIM was changed**: §1.2.1 says an MBN activation resets it, and if the SIM is new the setting will move again the same way next time. |
| 📵 **Voice route** | the module is registered and `<VoLTE_cap>` is `0` | Nothing local is known to fix this, and the gateway deliberately does not name a cause — it has no reading that says one. Check `/admin/modem`: if the `ims` row shows `1,0` the setting is still ours and the route is not there. An incoming call will not land. Escalate to the carrier only with the observation, not with a diagnosis. |
| 🕒 **Voice route unknown** | no reading could be taken for over an hour | This is *not* the route being lost — it is nobody being able to look. Usually the modem is not answering at all, which the watchdog is already working on; check the gateway row on `/admin/modem` for `recovering` and the link state. If the modem is healthy and this still fires, the response format has changed and the decoder needs a look. |

All three follow the system-errors notification switch, like the link alert does, and each
is raised once per episode with a notification when it clears.

⚠️ **The route's availability is not read while the module is off the network.** That is
deliberate: the field reads `0` on an unregistered module whatever the truth. So a modem
reset, a radio cycle and a recovery produce no voice-route alert — and produce no reading
either, which is what the staleness alert above is counting.

---

## Useful Debug Commands

```bash
# Test modem manually
screen /dev/ttyUSB2 115200

# Check signal strength
AT+CSQ              # Response: +CSQ: 20,99 (20 = good)

# Check network registration
AT+CREG?            # +CREG: 0,1 means registered

# Check operator
AT+COPS?            # +COPS: 0,0,"Tele2"

# List stored SMS
AT+CMGL="ALL"
```

---

## Dependencies

```
pyserial==3.5
pyserial-asyncio==0.6
```
