import base64
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.admin.router import router

_AUTH = {"Authorization": "Basic " + base64.b64encode(b"admin:change-me").decode()}

_SAMPLE = [
    {"key": "sim", "cmd": "AT+CPIN?", "raw": "+CPIN: READY", "parsed": {"state": "READY"}},
    {"key": "eps_reg", "cmd": "AT+CEREG?", "raw": "+CEREG: 0,1",
     "parsed": {"stat": 1, "status": "registered (home)"}},
    {"key": "signal_lte", "cmd": "AT+QCSQ", "error": "AT+QCSQ failed"},
]


class FakeModem:
    async def collect_diagnostics(self):
        return _SAMPLE


def _app():
    app = FastAPI()
    app.include_router(router)
    app.state.modem = FakeModem()
    return app


def test_modem_json_ok():
    c = TestClient(_app())
    r = c.get("/admin/modem.json", headers=_AUTH)
    assert r.status_code == 200
    assert r.json() == _SAMPLE


def test_modem_json_requires_auth():
    c = TestClient(_app())
    assert c.get("/admin/modem.json").status_code == 401


def test_modem_html_renders():
    c = TestClient(_app())
    r = c.get("/admin/modem", headers=_AUTH)
    assert r.status_code == 200
    assert "AT+CEREG?" in r.text
    assert "registered (home)" in r.text


def test_modem_html_no_cyrillic_literals_in_template():
    import re
    from pathlib import Path
    t = Path("app/admin/templates/modem.html").read_text(encoding="utf-8")
    assert not re.search(r"[А-Яа-яЁё]", t)
