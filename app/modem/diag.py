"""Pure decoders for modem AT diagnostic responses (no I/O). Each takes the raw
AT response string and returns a dict; an unparseable input returns {}."""

import re

_REG_STATUS = {
    0: "not registered", 1: "registered (home)", 2: "searching",
    3: "registration denied", 4: "unknown", 5: "registered (roaming)",
}
_ACT = {
    0: "GSM", 1: "GSM Compact", 2: "UTRAN", 3: "GSM/EGPRS",
    4: "UTRAN/HSDPA", 5: "UTRAN/HSUPA", 6: "UTRAN/HSDPA+HSUPA",
    7: "LTE (E-UTRAN)",
}


def decode_cpin(resp: str) -> dict:
    m = re.search(r'\+CPIN:\s*(\S+)', resp)
    return {"state": m.group(1)} if m else {}


def decode_reg(resp: str) -> dict:
    m = re.search(r'\+C[EG]?REG:\s*\d+,\s*(\d+)', resp)
    if not m:
        return {}
    stat = int(m.group(1))
    return {"stat": stat, "status": _REG_STATUS.get(stat, "unknown")}


def decode_csq(resp: str) -> dict:
    m = re.search(r'\+CSQ:\s*(\d+),\s*(\d+)', resp)
    if not m:
        return {}
    rssi, ber = int(m.group(1)), int(m.group(2))
    dbm = None if rssi == 99 else -113 + 2 * rssi
    return {"rssi": rssi, "dbm": dbm, "ber": ber}


def decode_cops(resp: str) -> dict:
    m = re.search(r'\+COPS:\s*\d+,\s*\d+,\s*"([^"]*)",\s*(\d+)', resp)
    if not m:
        return {}
    act = int(m.group(2))
    return {"operator": m.group(1), "act": act, "rat": _ACT.get(act, str(act))}


def decode_csca(resp: str) -> dict:
    m = re.search(r'\+CSCA:\s*"([^"]*)"', resp)
    return {"smsc": m.group(1)} if m else {}


def decode_qnwinfo(resp: str) -> dict:
    m = re.search(r'\+QNWINFO:\s*"([^"]*)",\s*"([^"]*)",\s*"([^"]*)",\s*(\d+)', resp)
    if not m:
        return {}
    return {"act": m.group(1), "operator": m.group(2),
            "band": m.group(3), "channel": int(m.group(4))}


def decode_qcsq(resp: str) -> dict:
    m = re.search(r'\+QCSQ:\s*"([^"]*)"\s*,\s*(.+)', resp)
    if not m:
        return {}
    sysmode = m.group(1)
    nums = []
    for tok in m.group(2).split(","):
        tok = tok.strip()
        try:
            nums.append(int(tok))
        except ValueError:
            pass
    out = {"sysmode": sysmode, "values": nums}
    if sysmode.upper().endswith("LTE") and len(nums) >= 4:   # Quectel LTE order
        out.update(rssi=nums[0], rsrp=nums[1], sinr=nums[2], rsrq=nums[3])
    return out
