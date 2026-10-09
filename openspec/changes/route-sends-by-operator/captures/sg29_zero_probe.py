"""SG-29/SG-39: does uCaller serialize a leading-zero code as a number?

Two free reads, the key is read from `settings` and never printed, no live
subscriber is called:

  1. `getInfo` for the live authorisation 57409114 (the 08.10 mismatch
     alert) — what `code` the vendor reports for it now;
  2. `initCall` on the vendor's free test number 79000000001 ("always
     success", never billed) with code "0427", then `getInfo` — whether a
     leading zero survives the vendor's JSON.

The discriminator: `code` reported as an int or a short digit-string means
the vendor number-mangles leading zeros and `flash_carrier._digits_changed`
fails a call whose tail was our digits; a full 4-character string means the
vendor reports whole codes and a mismatch is a genuinely different tail.

Run on the host:
    python3 sg29_zero_probe.py [path/to/sms.db]
"""
import json
import sqlite3
import sys
import time
import urllib.request
import uuid

DB = sys.argv[1] if len(sys.argv) > 1 else "/opt/sms-gate/data/sms.db"
BASE = "https://api.ucaller.ru/v1.0"
UID = 57409114
PHONE = "79000000001"
CODE = "0427"

con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
rows = dict(con.execute(
    "SELECT key, value FROM settings"
    " WHERE key IN ('ucaller_key', 'ucaller_service_id')"))
key, sid = rows.get("ucaller_key"), rows.get("ucaller_service_id")
if not key or not sid:
    sys.exit(f"no ucaller credential in {DB}")
AUTH = {"Authorization": f"Bearer {key}.{sid}",
        "User-Agent": "sms-gate/1.0"}


def call(method, body):
    req = urllib.request.Request(
        f"{BASE}/{method}", data=json.dumps(body).encode(), method="POST",
        headers={**AUTH, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def show(tag, env):
    if env.get("error"):
        print(f"{tag}: REFUSED code={env.get('code')} error={env.get('error')!r}")
        return None
    code = env.get("code", "<absent>")
    print(f"{tag}: status={env.get('status')} ucaller_id={env.get('ucaller_id')}"
          f" call_status={env.get('call_status')} cost={env.get('cost')}"
          f" code={code!r} (type {type(code).__name__})")
    return env.get("ucaller_id")


env = call("getInfo", {"uid": UID})
show(f"getInfo uid={UID}", env)

env = call("initCall", {"phone": int(PHONE), "code": CODE,
                        "unique": str(uuid.uuid4())})
uid = show("initCall test number, code 0427", env)
if uid:
    time.sleep(3)
    env = call("getInfo", {"uid": uid})
    show("getInfo the same authorisation", env)
