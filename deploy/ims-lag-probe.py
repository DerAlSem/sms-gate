#!/usr/bin/env python3
"""Task 1.4 of watch-the-voice-route: does the voice
route lag network registration, and by how long?

Reproduces the watchdog's own soft recovery
(CFUN=4 -> CFUN=1 -> COPS=0, then re-subscribe CNMI)
and samples AT+CEREG? and AT+QCFG="ims" together at
the production poll cadence of 2 s.

Needs the command port, so sms-gate must be stopped.
Stops early once the route has been up for three
consecutive samples, to keep the outage short.
"""
import re
import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB2"
BAUD = 115200
POLL = 2.0
CEILING = 300.0
CNMI = "AT+CNMI=2,1,2,1,0"

s = serial.Serial(PORT, BAUD, timeout=1)


def at(cmd, wait=0.5):
    s.reset_input_buffer()
    s.write((cmd + "\r").encode())
    time.sleep(wait)
    raw = s.read(600).decode("latin-1")
    return " ".join(raw.split())


CEREG_RE = re.compile(r"\+CEREG:\s*\d+\s*,\s*(\d+)")
IMS_RE = re.compile(r'"ims"\s*,\s*(\d+)\s*,\s*(\d+)')


def is_registered(cereg):
    """<stat> 1 is home, 5 is roaming; both count."""
    m = CEREG_RE.search(cereg)
    return bool(m) and m.group(1) in ("1", "5")


def is_route_up(ims):
    """Second field is <VoLTE_cap>. The first is the
    configuration and has three states, so it must not
    be read as a boolean and is not read here at all."""
    m = IMS_RE.search(ims)
    return bool(m) and m.group(2) == "1"


def sample():
    return at("AT+CEREG?"), at('AT+QCFG="ims"')


print("port:", PORT)
print("before:", sample(), flush=True)

print("CFUN=4:", at("AT+CFUN=4", 5.0), flush=True)
print("CFUN=1:", at("AT+CFUN=1", 10.0), flush=True)
print("COPS=0:", at("AT+COPS=0", 1.0), flush=True)

t0 = time.time()
good = 0
reg_at = None
route_at = None
while time.time() - t0 < CEILING:
    dt = round(time.time() - t0, 1)
    cereg, ims = sample()
    registered = is_registered(cereg)
    up = is_route_up(ims)
    if registered and reg_at is None:
        reg_at = dt
    if up and route_at is None:
        route_at = dt
    print(dt, "|", cereg, "|", ims, flush=True)
    good = good + 1 if (registered and up) else 0
    if good >= 3:
        break
    time.sleep(POLL)

print("CNMI:", at(CNMI), flush=True)
s.close()

print("registered at:", reg_at)
print("route up at:", route_at)
if reg_at is not None and route_at is not None:
    print("LAG seconds:", round(route_at - reg_at, 1))
else:
    print("LAG: not established within", CEILING, "s")
