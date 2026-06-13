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
