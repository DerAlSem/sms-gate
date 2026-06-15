import re
from dataclasses import dataclass


@dataclass
class DeliveryReport:
    modem_ref: int
    delivered: bool
    status_code: int


@dataclass
class InboundSms:
    index: int
    phone: str
    text: str


_CDS_PATTERN = re.compile(
    r'\+CDS:\s*\d+,(\d+),"[^"]*",\d+,"[^"]*","[^"]*",(\d+)'
)
_CMTI_PATTERN = re.compile(r'\+CMTI:\s*"([^"]+)"\s*,\s*(\d+)')
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


def parse_cds(line: str) -> DeliveryReport | None:
    """Parse +CDS delivery report line into DeliveryReport."""
    match = _CDS_PATTERN.search(line)
    if not match:
        return None
    modem_ref = int(match.group(1))
    status_code = int(match.group(2))
    return DeliveryReport(
        modem_ref=modem_ref,
        delivered=(status_code == 0),
        status_code=status_code,
    )


def parse_cmti(line: str) -> int | None:
    """Parse +CMTI: "<storage>",<index> → index. Storage ignored — modem decides."""
    match = _CMTI_PATTERN.search(line)
    return int(match.group(2)) if match else None


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
