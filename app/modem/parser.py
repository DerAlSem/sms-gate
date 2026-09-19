import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass
class DeliveryReport:
    modem_ref: int
    delivered: bool
    status_code: int
    # Everything below is optional by design: the line may carry it, and a line that
    # does not must still produce a usable report. Absent evidence never closes a door.
    recipient: str | None = None        # `ra` — recipient address of the original submit
    submitted_at: datetime | None = None    # `scts` — when the SMSC took the submit
    discharged_at: datetime | None = None   # `dt`  — when the network reached its verdict
    raw_line: str = ""


@dataclass
class InboundSms:
    index: int
    phone: str
    text: str


# +CDS: fo,mr,ra,tora,scts,dt,st  (docs/modem.md:103)
#
# ⚠️ The groups are positional and `parse_cds` reads them by number. `ra`, `scts` and `dt`
# are captured *ahead* of the status, so every group reference below is indexed against
# this comment, not against the shape this pattern used to have. Getting it wrong reads
# the status out of a timestamp and turns every delivery in the system into a failure.
#             1=mr        2=ra          3=scts     4=dt      5=st
_CDS_PATTERN = re.compile(
    r'\+CDS:\s*\d+,(\d+),"([^"]*)",\d+,"([^"]*)","([^"]*)",(\d+)'
)
_CMTI_PATTERN = re.compile(r'\+CMTI:\s*"([^"]+)"\s*,\s*(\d+)')

# +CLIP: <number>,<type>[,<subaddr>,<satype>[,[<alpha>][,<CLI validity>]]]
#
# Captured live from the production EP06-E on 2026-09-18, not inferred:
#   RING
#   +CLIP: "+79261234888",145,,,,0
# `145` is the type of address (international) and the last field is CLI validity —
# 0 the number is valid, 1 the caller withheld it, 2 the network could not supply it.
#
# Only the first two fields are required by the format, so the validity is its own
# optional group: a modem that stops short of it has not told us the number is invalid.
_CLIP_PATTERN = re.compile(
    r'\+CLIP:\s*"?([^",]*)"?\s*,\s*(\d+)(?:\s*,[^,]*,[^,]*,[^,]*,\s*(\d+))?'
)
_CMGR_PATTERN = re.compile(
    r'\+CMGR:\s*"[^"]*"\s*,\s*"([^"]*)"\s*,[^\r\n]*\r?\n([^\r\n]*)'
)
_CMGL_PATTERN = re.compile(
    r'\+CMGL:\s*(\d+)\s*,\s*"[^"]*"\s*,\s*"([^"]*)"\s*,[^\r\n]*\r?\n([^\r\n]*)'
)
_CMGR_PDU_PATTERN = re.compile(
    r'\+CMGR:\s*\d+\s*,\s*(?:"[^"]*")?\s*,\s*\d+\s*\r?\n\s*([0-9A-Fa-f]+)'
)
_CMGL_PDU_PATTERN = re.compile(
    r'\+CMGL:\s*(\d+)\s*,\s*\d+\s*,\s*(?:"[^"]*")?\s*,\s*\d+\s*\r?\n\s*([0-9A-Fa-f]+)'
)
_HEX_RE = re.compile(r'^[0-9A-Fa-f]+$')


# GSM 07.05 +CMS / +CME numeric result codes we actually see in the wild.
# Anything not listed falls back to the bare "+CMS ERROR <n>" label.
_CMS_ERRORS = {
    1: "unassigned number",
    21: "short message transfer rejected",
    28: "unidentified subscriber",
    38: "network out of order",
    41: "temporary failure",
    42: "congestion",
    50: "operation barred",
    69: "requested facility not implemented",
    96: "invalid mandatory information",
    300: "modem failure",
    301: "SMS service reserved",
    302: "operation not allowed",
    303: "operation not supported",
    304: "invalid PDU mode parameter",
    305: "invalid text mode parameter",
    310: "SIM not inserted",
    311: "SIM PIN required",
    313: "SIM failure",
    321: "invalid memory index",
    330: "SMSC address unknown",
    331: "no network service",
    332: "network timeout",
    350: "network/SMSC rejected the message",
    500: "unknown error",
}
_CME_ERRORS = {
    3: "operation not allowed",
    4: "operation not supported",
    10: "SIM not inserted",
    11: "SIM PIN required",
    13: "SIM failure",
    30: "no network service",
    31: "network timeout",
    100: "unknown error",
}
_AT_ERROR_NUM = re.compile(r'\+(CM[SE]) ERROR:\s*(\d+)')
_AT_ERROR_TXT = re.compile(r'\+(CM[SE]) ERROR:\s*([^\r\n]+)')


def describe_at_error(response: str) -> str:
    """Turn a raw modem reply into a short, human-readable error string.

    Examples:
        '\\r\\n+CMS ERROR: 305\\r\\n' -> '+CMS ERROR 305 (invalid text mode parameter)'
        '\\r\\nERROR\\r\\n'           -> 'modem returned ERROR'
    """
    m = _AT_ERROR_NUM.search(response)
    if m:
        kind, code = m.group(1), int(m.group(2))
        table = _CMS_ERRORS if kind == 'CMS' else _CME_ERRORS
        desc = table.get(code)
        if desc is None and kind == 'CMS' and 300 <= code <= 511:
            # 300-511 is the +CMS operator/SMSC error band; vendor-specific codes
            # (e.g. 350) aren't all in the table — still classify rather than show bare.
            desc = "network/SMSC rejection (operator-specific)"
        label = f"+{kind} ERROR {code}"
        return f"{label} ({desc})" if desc else label
    m = _AT_ERROR_TXT.search(response)
    if m:
        return f"+{m.group(1)} ERROR: {m.group(2).strip()}"
    if 'ERROR' in response:
        return "modem returned ERROR"
    return response.strip()


# GSM 03.40 §9.2.3.15 TP-Status. Ranges give the class; the table names common codes.
_TP_STATUS = {
    0x00: "received by recipient",
    0x01: "forwarded, delivery not confirmed",
    0x02: "replaced",
    0x20: "congestion",
    0x21: "recipient busy",
    0x22: "no response from recipient",
    0x23: "service rejected",
    0x24: "quality of service not available",
    0x25: "error in recipient",
    0x40: "remote procedure error",
    0x41: "incompatible destination",
    0x42: "connection rejected by recipient",
    0x43: "not obtainable",
    0x44: "quality of service not available",
    0x45: "no interworking available",
    0x46: "message validity period expired",
    0x47: "message deleted by sender",
    0x48: "message deleted by SMSC admin",
    0x49: "message does not exist",
    0x60: "congestion",
    0x61: "recipient busy",
    0x62: "no response from recipient",
    0x63: "service rejected",
    0x64: "quality of service not available",
    0x65: "error in recipient",
}


def _tp_status_class(code: int) -> str:
    if 0x00 <= code <= 0x1F:
        return "completed"
    if 0x40 <= code <= 0x5F:
        return "permanent"
    return "temporary"   # 0x20–0x3F and 0x60–0x7F


def describe_tp_status(code: int) -> str:
    """Human-readable GSM 03.40 TP-Status, e.g. 'service rejected (temporary, st=99)'.
    Unknown codes fall back to 'delivery failed' with the range-derived class."""
    desc = _TP_STATUS.get(code, "delivery failed")
    return f"{desc} ({_tp_status_class(code)}, st={code})"


def parse_cmgs_ref(response: str) -> int | None:
    """Extract message reference from +CMGS: <ref> response."""
    match = re.search(r'\+CMGS:\s*(\d+)', response)
    return int(match.group(1)) if match else None


# GSM 03.40 §9.2.3.11 TP-SCTS: `YY/MM/DD,hh:mm:ss±zz`, where `zz` is the offset from UTC
# in **quarter-hours** — `+12` is UTC+03:00, not UTC+12:00. An implementation reading it as
# hours is nine hours out, and since a timestamp may only *order* candidates and never
# eliminate one, that error would never surface as a failure: only as the wrong candidate
# chosen, silently, for ever.
_SCTS_PATTERN = re.compile(
    r'^(\d{2})/(\d{2})/(\d{2}),(\d{2}):(\d{2}):(\d{2})([+-]\d{1,2})$'
)


def parse_scts(value: str) -> datetime | None:
    """Service-centre timestamp → aware datetime, or None when it cannot be read.

    Unreadable is *absent*, never epoch zero: a report that lands in 1970 would be
    ordered against every candidate as impossibly old, and the rules that use this
    value must degrade to not using it rather than to using a wrong one.
    """
    match = _SCTS_PATTERN.match(value.strip())
    if not match:
        return None
    yy, mm, dd, hh, mi, ss, quarters = match.groups()
    try:
        offset = timedelta(minutes=15 * int(quarters))
        return datetime(
            2000 + int(yy), int(mm), int(dd), int(hh), int(mi), int(ss),
            tzinfo=timezone(offset),
        )
    except ValueError:
        # An out-of-range field (month 13, hour 25) or an offset past ±24h. The shape
        # matched and the content did not; still absent, still not a rejection.
        return None


def parse_cds(line: str) -> DeliveryReport | None:
    """Parse +CDS delivery report line into DeliveryReport.

    Group numbers follow `_CDS_PATTERN` above: 1=mr, 2=ra, 3=scts, 4=dt, 5=st.
    """
    match = _CDS_PATTERN.search(line)
    if not match:
        return None
    modem_ref = int(match.group(1))
    status_code = int(match.group(5))
    recipient = match.group(2).strip()
    return DeliveryReport(
        modem_ref=modem_ref,
        delivered=(status_code == 0),
        status_code=status_code,
        # An empty `ra` is the network saying nothing, not a number with no digits.
        recipient=recipient or None,
        submitted_at=parse_scts(match.group(3)),
        discharged_at=parse_scts(match.group(4)),
        raw_line=line,
    )


def parse_cmti(line: str) -> int | None:
    """Parse +CMTI: "<storage>",<index> → index. Storage ignored — modem decides."""
    match = _CMTI_PATTERN.search(line)
    return int(match.group(2)) if match else None


def parse_clip(line: str) -> str | None:
    """The caller's number from one `+CLIP`, as the network gave it, or None.

    None means "this line carries no number we may act on", and it covers three
    different arrivals on purpose: the field is empty because the caller withheld it,
    the validity says the network could not supply it, or the line is not readable as a
    `+CLIP` at all. They differ in why, not in what may be concluded — and what may be
    concluded is nothing about who called. The raw line is kept by the caller either way,
    so the distinction is not lost, merely not made here.

    Canonicalisation is deliberately elsewhere. This returns the network's own text; what
    a phone number is belongs to `app.phone`, which owns that question for the whole
    gateway.
    """
    match = _CLIP_PATTERN.search(line)
    if not match:
        return None
    number = match.group(1).strip()
    validity = match.group(3)
    if validity is not None and validity != "0":
        # The network is telling us the caller ID is not to be trusted. A number in the
        # field alongside that is not an exception to it.
        return None
    return number or None


def _decode_text(raw: str) -> str:
    """Heuristic decode: hex-only even-length string → UCS2-BE, else as-is."""
    s = raw.strip()
    if len(s) >= 4 and len(s) % 2 == 0 and _HEX_RE.match(s):
        try:
            return bytes.fromhex(s).decode('utf-16-be')
        except (ValueError, UnicodeDecodeError):
            return raw
    return raw


def parse_cmgr(response: str, index: int) -> InboundSms | None:
    """Parse +CMGR response into InboundSms. Phone and text are auto-decoded from UCS2 hex."""
    match = _CMGR_PATTERN.search(response)
    if not match:
        return None
    return InboundSms(
        index=index,
        phone=_decode_text(match.group(1)),
        text=_decode_text(match.group(2)),
    )


def parse_cmgl(response: str) -> list[InboundSms]:
    """Parse +CMGL response into a list of InboundSms (one per stored message)."""
    return [
        InboundSms(
            index=int(m.group(1)),
            phone=_decode_text(m.group(2)),
            text=_decode_text(m.group(3)),
        )
        for m in _CMGL_PATTERN.finditer(response)
    ]


def parse_cmgr_pdu(response: str) -> str | None:
    """+CMGR in PDU mode → PDU hex string, or None."""
    match = _CMGR_PDU_PATTERN.search(response)
    return match.group(1) if match else None


def parse_cmgl_pdu(response: str) -> list[tuple[int, str]]:
    """+CMGL in PDU mode → [(index, hex_pdu), ...]."""
    return [
        (int(m.group(1)), m.group(2))
        for m in _CMGL_PDU_PATTERN.finditer(response)
    ]
