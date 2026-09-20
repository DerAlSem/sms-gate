#!/usr/bin/env python3
"""Task 1.4 of watch-the-voice-route: does the voice
route lag network registration, and by how long?

The first version of this probe answered "0.0" and had
measured nothing: it blocked ten seconds waiting for
CFUN=1 to reply and one more on COPS=0, so the whole
reattach happened inside its own pause. It also never
sampled between CFUN=4 and CFUN=1, so it could not even
show that the radio had cycled.

This version issues each command with a short wait and
samples throughout, at 1 s. It answers two questions
from one run:

  * is there a window where the module is registered
    and the route is not yet up (the design's gate
    rests on there being none);
  * when could the production path first look? The
    watchdog blocks through COPS=0, so the mark
    "COPS returned" is that earliest moment.

A run that never sees the module leave the network
proves nothing about coming back, and says so.

Needs the command port, so sms-gate must be stopped.
"""
import re
import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB2"
BAUD = 115200
POLL = 1.0
CEILING = 300.0
CNMI = "AT+CNMI=2,1,2,1,0"

CEREG_RE = re.compile(r"\+CEREG:\s*\d+\s*,\s*(\d+)")
IMS_RE = re.compile(r'"ims"\s*,\s*(\d+)\s*,\s*(\d+)')

s = serial.Serial(PORT, BAUD, timeout=1)


def at(cmd, wait=0.4):
    s.reset_input_buffer()
    s.write((cmd + "\r").encode())
    time.sleep(wait)
    raw = s.read(600).decode("latin-1")
    return " ".join(raw.split())


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


t0 = time.time()
left_network = False
reg_at = None
route_at = None
cops_at = None


def tick(mark=""):
    global left_network, reg_at, route_at
    dt = round(time.time() - t0, 1)
    cereg = at("AT+CEREG?")
    ims = at('AT+QCFG="ims"')
    reg = is_registered(cereg)
    up = is_route_up(ims)
    if not reg:
        left_network = True
    elif reg_at is None and left_network:
        reg_at = dt
    if up and route_at is None and left_network:
        route_at = dt
    print(dt, "|", cereg, "|", ims, mark, flush=True)
    return reg, up


print("port:", PORT)
tick("before")

at("AT+CFUN=4", 0.4)
print("--- CFUN=4 issued ---", flush=True)
for _ in range(8):
    tick()
    time.sleep(POLL)

at("AT+CFUN=1", 0.4)
print("--- CFUN=1 issued ---", flush=True)
at("AT+COPS=0", 0.4)
cops_at = round(time.time() - t0, 1)
print("--- COPS=0 issued at", cops_at, "---", flush=True)

good = 0
while time.time() - t0 < CEILING:
    reg, up = tick()
    good = good + 1 if (reg and up) else 0
    if good >= 3:
        break
    time.sleep(POLL)

print("CNMI:", at(CNMI), flush=True)
s.close()

print("left the network:", left_network)
print("re-registered at:", reg_at)
print("route back up at:", route_at)
print("production could look from:", cops_at)
if not left_network:
    print("VERDICT: radio never cycled - measures nothing")
elif reg_at is None or route_at is None:
    print("VERDICT: did not come back within", CEILING, "s")
else:
    print("LAG seconds:", round(route_at - reg_at, 1))
