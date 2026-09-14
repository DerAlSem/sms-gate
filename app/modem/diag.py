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


_CLIP_PROVISION = {0: "not provisioned", 1: "provisioned", 2: "unknown"}


def decode_clip(resp: str) -> dict:
    """`+CLIP: <n>,<m>` — two facts about calling-line identification, not one.

    `n` is our own URC subscription: whether this port was told to report the caller's
    number. `m` is the one that costs money to learn any other way — whether the
    *network* provisions calling-line identification on this subscription.

    An unparseable response returns `{}` rather than zeros: a firmware that does not
    know the command answers `ERROR`, and "the operator does not provide caller ID"
    and "we never managed to ask" are different facts that must not render alike.
    """
    m = re.search(r'\+CLIP:\s*(\d+)\s*,\s*(\d+)', resp)
    if not m:
        return {}
    provision = int(m.group(2))
    return {"urc": int(m.group(1)), "provision": provision,
            "network": _CLIP_PROVISION.get(provision, "unknown")}


def decode_clip_test(resp: str) -> dict:
    """`AT+CLIP=?` — does this firmware know the command at all.

    Asked separately from `AT+CLIP?` because it is the cheaper question and the one
    that can end the enquiry: a build with voice stripped answers `ERROR` here, and no
    amount of network provisioning would help. The accepted forms cover both list and
    range notation (`(0,1)` and `(0-1)`) because firmwares differ on which they print.
    """
    return {"supported": True} if re.search(r'\+CLIP:\s*\(', resp) else {}


_SERVICE_DOMAIN = {0: "CS only", 1: "PS only", 2: "CS & PS"}


def decode_servicedomain(resp: str) -> dict:
    """`AT+QCFG="servicedomain"` — which domains the module registers for at all.

    Vendor manual (EC25/EC21 AT commands, shared by the EP06 series): 0 CS only,
    1 PS only, 2 CS & PS. `1` would end an enquiry on its own — a module that never
    registers for circuit-switched service cannot be paged for a voice call, however
    healthy its data registration looks and however willingly it reports caller ID.

    An unreadable response returns `{}`. `0` is itself a meaningful value here, so a
    failed read must not render as one: that would report the opposite of the case
    under suspicion.
    """
    m = re.search(r'\+QCFG:\s*"servicedomain"\s*,\s*(\d+)', resp)
    if not m:
        return {}
    domain = int(m.group(1))
    return {"domain": domain, "service": _SERVICE_DOMAIN.get(domain, "unknown")}


def decode_cireg(resp: str) -> dict:
    """`AT+CIREG?` — IMS registration, the other way an incoming call could land.

    On LTE a voice call arrives either over VoLTE, which needs the module registered to
    IMS, or by falling back to circuit-switched service. The EP06-E datasheet marks
    VoLTE `Optional`, so this is a real question rather than a formality: not registered
    to IMS leaves CS fallback as the only remaining route.

    3GPP 27.007: `+CIREG: <n>,<reg_info>[,<ext_info>]`. `<n>` is only the URC
    subscription; `<reg_info>` is the answer.
    """
    m = re.search(r'\+CIREG:\s*\d+\s*,\s*(\d+)', resp)
    if not m:
        return {}
    reg = int(m.group(1))
    return {"ims": reg, "state": "registered" if reg else "not registered"}


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


# The readings an alert carries. Four, not nine: `_bounded(record.getMessage(), 500)`
# truncates what Telegram delivers, and a summary that needs truncating loses the reading
# it was added for. These four are the ones that answer the question the operator actually
# has — is this the radio, the network, or the card.
_ALERT_READINGS = ("sim", "cs_reg", "signal", "operator")


def summarise_for_alert(diag: list[dict]) -> str:
    """One line of observations for an operator alert, from a collect_diagnostics() result.

    Reports; does not conclude. On 2026-09-06 every alert of a two-hour outage read
    "check antenna/operator" while the signal had never been read and the fault was the
    SIM — a guess presented as a finding, and it was acted on. A reading the gateway does
    not have is rendered `?` rather than left out, because a silently absent field reads
    as a field that was fine.
    """
    by_key = {item.get("key"): item for item in diag}

    alive = by_key.get("alive")
    if alive is not None and alive.get("error"):
        return f"observations unavailable: {alive['error']}".rstrip(": ")

    def parsed(key: str) -> dict:
        item = by_key.get(key) or {}
        return item.get("parsed") or {}

    sim = parsed("sim").get("state") or "?"
    reg = parsed("cs_reg").get("status") or "?"

    signal = parsed("signal")
    dbm = signal.get("dbm")
    signal_txt = f"{dbm}dBm" if dbm is not None else "?"

    op = parsed("operator")
    name = op.get("operator")
    op_txt = f"{name}/{op.get('rat', '?')}" if name else "?"

    return f"SIM={sim} reg={reg} signal={signal_txt} operator={op_txt}"
