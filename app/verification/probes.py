"""What each rung this change bears has to prove before it is offered.

A probe answers one question — "can this rung carry a verification for this number, right
now" — and answers it without placing anything. The registry does the rest: bounding the
set, refusing stale evidence, and keeping the ladder's order.

Only the two rungs this change bears are built here. `sms_out`, `flash_call` and
`tg_gateway` belong to `route-sends-by-operator` and are blocked on accounts and balances
rather than on code; until their probes are registered the registry treats them exactly as
it treats any other rung nothing can prove, which is as unavailable. That is the correct
answer rather than a placeholder: being configured was never evidence.
"""

from __future__ import annotations

from app.db import queries
from app.verification.routes import CALL_IN, SMS_IN, Proof


def build_probes(modem, *, ims_proof=None, excluding: int | None = None) -> dict:
    """The probes the gateway can actually run today, ready for the registry.

    `ims_proof` is the seam onto the sibling change `watch-the-voice-route`, which is
    required to report when the voice route was last successfully measured. It is a
    callable returning a `Proof` whose `measured_at` is that time — the registry applies
    the maximum age, because how stale a proof may be is this capability's decision and
    not the measurer's. Absent, the `call_in` rung is unavailable, which is the failing
    direction the norm demands: an unread precondition is not a satisfied one.

    `excluding` names a verification whose own open window must not count against it. It
    is set when a rung is re-proved *under* an open verification, and left unset when the
    question is "can a new one be carried".
    """
    return {
        CALL_IN: _call_in_probe(modem, ims_proof, excluding),
        SMS_IN: _sms_in_probe(modem),
    }


def _call_in_probe(modem, ims_proof, excluding=None):
    async def probe(phone: str) -> Proof:
        # Three separate things have to hold, and they fail for different reasons.
        #
        # The caller-ID subscription is the gateway's own record — `AT+CLIP?` does not
        # answer on this device — and without it a call arrives anonymous, which confirms
        # nothing. That is the difference between "the caller withheld their number"
        # (ordinary) and "this rung should not have been offered".
        if not modem.caller_id_held:
            return Proof(holds=False, reason="the caller-ID subscription is not held")

        # An incoming call reaches this modem only while IMS is registered, and when it
        # goes off `RING` simply stops arriving — no error anywhere. This is the silent
        # death the whole norm exists for.
        if ims_proof is None:
            return Proof(holds=False,
                         reason="no reading of the voice route is available")
        proof = await ims_proof()
        if not proof.holds:
            return proof

        # A call carries no code, so attribution rests entirely on the number and the
        # window. Two open windows on one number would leave an arriving call belonging
        # to neither with certainty.
        if await queries.has_open_verification(
                phone, route=CALL_IN, excluding=excluding):
            return Proof(holds=False,
                         reason="this number already has a call verification open")
        return proof

    return probe


def _sms_in_probe(modem):
    async def probe(phone: str) -> Proof:
        # The person sends; the gateway only has to be able to receive. That is the URC
        # link being in service — the same link `+CMTI` arrives on.
        if not modem.link_in_service:
            return Proof(holds=False, reason="the modem link is not in service")
        return Proof(holds=True)

    return probe
