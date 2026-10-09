"""SG-29: which part of the initCall body earns `code 1`.

Five calls to the vendor's free test number 79000000001
("always success", never billed), 17 s apart to stay under
4-per-minute-per-number. Each differs from the adapter's
body in one field. The key is read from `settings` and
never printed; our code is never printed either.

Run on the host, as the service user:
    sudo -u smsgate python3 sg29_probe.py [path/to/sms.db]
"""
import json
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
import uuid

DB = sys.argv[1] if len(sys.argv) > 1 else "/opt/sms-gate/data/sms.db"
URL = "https://api.ucaller.ru/v1.0/initCall"
PHONE = "79000000001"
CODE = "4827"

con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
rows = dict(con.execute(
    "SELECT key, value FROM settings"
    " WHERE key IN ('ucaller_key', 'ucaller_service_id')"))
key, sid = rows.get("ucaller_key"), rows.get("ucaller_service_id")
if not key or not sid:
    sys.exit(f"no ucaller credential in {DB}")
AUTH = {"Authorization": f"Bearer {key}.{sid}",
        "User-Agent": "sms-gate/1.0"}


def post(body):
    req = urllib.request.Request(
        URL, data=json.dumps(body).encode(), method="POST",
        headers={**AUTH, "Content-Type": "application/json"})
    return send(req)


def get(params):
    q = urllib.parse.urlencode(params)
    return send(urllib.request.Request(f"{URL}?{q}", headers=AUTH))


def send(req):
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status, json.loads(r.read())


def u():
    return str(uuid.uuid4())


VARIANTS = [
    ("A adapter as-is (phone str)",
     lambda: post({"phone": PHONE, "code": CODE, "unique": u()})),
    ("B phone int",
     lambda: post({"phone": int(PHONE), "code": CODE, "unique": u()})),
    ("C phone int, code int",
     lambda: post({"phone": int(PHONE), "code": int(CODE),
                   "unique": u()})),
    ("D phone str, no unique",
     lambda: post({"phone": PHONE, "code": CODE})),
    ("E GET control (1.3 form)",
     lambda: get({"phone": PHONE, "code": CODE, "unique": u()})),
]

for i, (name, call) in enumerate(VARIANTS):
    if i:
        time.sleep(17)
    try:
        http, env = call()
    except Exception as e:  # noqa: BLE001 - a probe reports, never dies
        print(f"{name}: no answer ({type(e).__name__})")
        continue
    if env.get("error"):
        print(f"{name}: HTTP {http} REFUSED code={env.get('code')}"
              f" error={env.get('error')!r}")
    else:
        print(f"{name}: HTTP {http} status={env.get('status')}"
              f" ucaller_id={env.get('ucaller_id')}")
