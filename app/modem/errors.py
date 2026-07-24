"""Is a send failure worth another attempt?

Kept apart from `parser.describe_at_error`, which turns a modem reply into words, and
from `manager._is_permanent_status`, which classifies a TP-status on a *delivery report*.
This module answers a third question about a third layer: the message never left the
modem, so should the gateway try again?

The default is asymmetric on purpose. Retrying a hopeless failure wastes a few seconds
inside a bounded budget; not retrying a recoverable one loses the message and pulls a
human in. So only failures that are known to be hopeless are permanent — everything
else, including a code nobody has catalogued yet, is retried.
"""

from __future__ import annotations

import re

# The network refuses this message or this destination, and will refuse it again.
_PERMANENT_CMS = {
    1,    # unassigned number
    21,   # short message transfer rejected
    28,   # unidentified subscriber
    50,   # operation barred
    69,   # requested facility not implemented
    96,   # invalid mandatory information
    # Malformed or misconfigured on our side — identical next time.
    301,  # SMS service reserved
    302,  # operation not allowed
    303,  # operation not supported
    304,  # invalid PDU mode parameter
    305,  # invalid text mode parameter
    321,  # invalid memory index
    330,  # SMSC address unknown
    # Hardware/SIM — a retry in minutes cannot fix it; the watchdog is the responder.
    310,  # SIM not inserted
    311,  # SIM PIN required
    313,  # SIM failure
}

# Same SIM conditions, as reported on the +CME side.
_PERMANENT_CME = {10, 11, 13}

_CODE_RE = re.compile(r'\+(CM[SE])\s+ERROR:?\s*(\d+)')

# Raised before any AT command is issued, so it carries no modem code of its own.
_TOO_LONG_RE = re.compile(r'message too long:')


def is_permanent_failure(error: str) -> bool:
    """True when re-attempting `error` cannot change the outcome.

    `error` is the text a send failure carries — `ATCommandError`'s message, possibly
    wrapped by the caller with the AT command or a helper's label.
    """
    if not error:
        return False
    if _TOO_LONG_RE.search(error):
        return True
    match = _CODE_RE.search(error)
    if not match:
        return False
    kind, code = match.group(1), int(match.group(2))
    table = _PERMANENT_CMS if kind == 'CMS' else _PERMANENT_CME
    return code in table


def is_retryable(error: str, *, pdu_submitted: bool, already_sent: bool) -> bool:
    """True when the gateway may transmit this message again.

    Three independent vetoes, because the cost of getting this wrong is a duplicate SMS
    on a real handset:

    - `pdu_submitted` — the message bytes reached the modem, so the SMSC may hold it
      even though the confirmation never came back. The wire cannot tell us which.
    - `already_sent` — an earlier part of a multipart message was accepted, so a resend
      would deliver that part twice (and reuse its concatenation reference).
    - a permanent failure, which a retry cannot change anyway.
    """
    if pdu_submitted or already_sent:
        return False
    return not is_permanent_failure(error)
