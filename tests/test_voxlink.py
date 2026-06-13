import httpx

from app.lookup.voxlink import RangeInfo, parse_response
from app.lookup import voxlink


def test_parse_resolved():
    data = {"code": "916", "operator": "T-Mobile",
            "region": "Moscow and Moscow Oblast"}
    info = parse_response(data)
    assert info == RangeInfo(allocated=True, operator="T-Mobile",
                             region="Moscow and Moscow Oblast",
                             operator_inn=None)


def test_parse_not_found_returns_none():
    # voxlink "Number not found" body has `info`, no `operator`
    assert parse_response({"info": "Number not found. Check city code"}) is None


def test_parse_no_operator_returns_none():
    assert parse_response({"code": "916"}) is None


def test_parse_non_dict_returns_none():
    assert parse_response([]) is None


def test_parse_strips_and_nulls_missing_region():
    info = parse_response({"operator": "  MegaFon  "})
    assert info.operator == "MegaFon"
    assert info.region is None


import asyncio


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, raise_json=False):
        self.status_code = status_code
        self._payload = payload
        self._raise_json = raise_json

    def json(self):
        if self._raise_json:
            raise ValueError("no json")
        return self._payload


class _FakeClient:
    """Stands in for httpx.AsyncClient; records the last GET call."""
    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc
        self.calls = []

    async def get(self, url, params=None, headers=None):
        self.calls.append({"url": url, "params": params})
        if self._exc is not None:
            raise self._exc
        return self._response


def _run(coro):
    return asyncio.run(coro)


def test_lookup_resolved():
    client = _FakeClient(_FakeResponse(200, {"operator": "MTS", "region": "Samara"}))
    info = _run(voxlink.lookup("9171234567", "http://x/get/", 5.0, client=client))
    assert info == RangeInfo(allocated=True, operator="MTS", region="Samara")
    assert client.calls[0]["params"] == {"num": "9171234567"}


def test_lookup_not_found_returns_none():
    client = _FakeClient(_FakeResponse(200, {"info": "Number not found"}))
    assert _run(voxlink.lookup("9000000000", "http://x/get/", 5.0, client=client)) is None


def test_lookup_non_200_returns_none():
    client = _FakeClient(_FakeResponse(503, None))
    assert _run(voxlink.lookup("9171234567", "http://x/get/", 5.0, client=client)) is None


def test_lookup_bad_json_returns_none():
    client = _FakeClient(_FakeResponse(200, None, raise_json=True))
    assert _run(voxlink.lookup("9171234567", "http://x/get/", 5.0, client=client)) is None


def test_lookup_network_error_returns_none():
    client = _FakeClient(exc=httpx.ConnectError("boom"))
    assert _run(voxlink.lookup("9171234567", "http://x/get/", 5.0, client=client)) is None
