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
5. Parse reference number, save to `messages.modem_ref`, set status = `sent`
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
| ra | Recipient address (phone) |
| tora | Type of recipient address |
| scts | Service Centre Time Stamp |
| dt | Discharge Time (when delivered) |
| st | **Status** — 0 = delivered, >0 = error/pending |

### Status Values (st field)

| st | Meaning |
|----|---------|
| 0 | Delivered successfully |
| 1 | Forwarded, no delivery confirmation |
| 32 | Still trying (temporary) |
| 64 | Permanent error: remote procedure error |
| 96 | Permanent error: incompatible destination |

**Key logic**: if `st == 0` → set message status = `delivered`, save `delivered_at`. If `st >= 64` → set status = `failed`.

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

Only one process can open the serial port. On startup:
1. Try to open the port
2. If `PermissionError` or `SerialException` → log error, exit with clear message
3. Consider using `/var/lock/LCK..ttyUSB2` lockfile (standard UUCP convention)

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
