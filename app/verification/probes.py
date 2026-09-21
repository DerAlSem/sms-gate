"""What each rung this change bears has to prove before it is offered.

A probe answers one question — "can this rung carry a verification for this number, right
now" — and answers it without placing anything. The registry does the rest: bounding the
set, refusing stale evidence, and keeping the ladder's order.

`flash_call` belongs to `route-sends-by-operator` and is blocked on an account and a
balance rather than on code; until its probe is registered the registry treats it exactly
as it treats any other rung nothing can prove, which is as unavailable. That is the
correct answer rather than a placeholder: being configured was never evidence.

🔴 **`sms_out` stood in that sentence until 21.09.2026 and does not belong in it.** The
modem is this gateway's own hardware: there is no account to open and no balance to fund,
so the rung is unoffered for a reason that was never true of it — while
`verification_route_order` has shipped naming it **second** and the routing rule ships
sending every operator but one to it. It is still absent, and now for a reason that is
measured rather than assumed: **registering its probe retires `sms_in` outright.** Both
probes hold on exactly one thing, `modem.link_in_service`, and `sms_in` is dropped
whenever anything earlier in the order proved itself — so `sms_out` proving is `sms_in`
never being offered again, and `sms_in` is the whole subject of the sibling change
`verify-by-inbound-contact`. Two further things collide with it and neither is settled:
the offer is not filtered by the routing rule, so the rung would be offered for the one
operator the rule diverts *away* from it; and an application with no template would be
offered a rung that cannot compose its code (task 4.47). The carrier exists and the
ladder reaches it as a continuation; whether the consumer may **choose** it is the
owner's, and it is task 4.17c.

`tg_gateway` is the exception to that sentence, and the exception is argued rather than
assumed — see its probe below.
"""

from __future__ import annotations

from app.db import queries
from app.verification.routes import CALL_IN, SMS_IN, TG_GATEWAY, Proof


def build_probes(
    modem, *, ims_proof=None, excluding: int | None = None,
    tg_token: str = "", tg_reachability=None,
) -> dict:
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

    `tg_token` is passed rather than read from the settings here so that a caller that
    forgets it leaves the rung unoffered — the failing direction — instead of a probe
    silently reaching for global state. `tg_reachability` is the seam onto
    `carry-telegram-on-any-uplink`, on the same terms as `ims_proof`.
    """
    return {
        CALL_IN: _call_in_probe(modem, ims_proof, excluding),
        SMS_IN: _sms_in_probe(modem),
        TG_GATEWAY: _tg_gateway_probe(tg_token, tg_reachability),
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


def _tg_gateway_probe(token, reachability):
    """The Telegram rung, whose precondition cannot be bought during the offer.

    The asymmetry with the other two is deliberate and worth stating, because it looks
    at first like the very thing the registry forbids — treating configuration as
    evidence.

    The only question the vendor will answer about a subscriber is `checkSendAbility`,
    and it is **billed when it confirms**. Asking it here would buy the rung during the
    offer, before the blacklist, the per-number limits, the application's entitlement
    and the spend ceiling have run — and a gate evaluated after a confirmed ability
    check refuses something already paid for, with no refund path, because the refund is
    tied to non-delivery within a `ttl` and a `ttl` only starts when a message is sent.
    So the probe places nothing, and there is nothing free left for it to place.

    What justifies offering the rung on a held token is that this rung does **not** die
    silently, which is the property the whole registry exists for. When `call_in` is
    dead, `RING` simply stops arriving and the person waits out the window for a call
    that can never come. When this rung is dead, the adapter's own bound expires, the
    check is recorded as possibly charged, and the ladder advances to `flash_call`. A
    loud, bounded failure is handled where it happens rather than pre-empted here.

    🟢 **That argument stopped being an argument on 20.09.2026 and became a number.**
    "Dies loudly" is only worth anything if the noise arrives inside the ladder's
    patience, and until 1.7 nobody had measured how long the vendor takes to speak.
    Measured from derserver over the wire: a **confirmation** in 260 ms, a **decline**
    in 190 ms, and every other method between 178 and 285 ms. The floor of the round
    trip — three calls with a deliberately invalid token, which reach the vendor and
    are refused without touching the balance — is 180, 188 and 241 ms, so nearly all
    of it is network and TLS rather than the vendor thinking. Against a
    `verification_probe_timeout` of 5 s that is roughly eighteenfold headroom. The
    rung's failure is therefore loud *and* prompt on the wired path, and the probe
    stays as it is written here.

    That leaves one real weakness — on a failed-over uplink `gatewayapi.telegram.org`
    times out at fifteen seconds (measured 18.09.2026), which is longer than the
    ladder's patience. Its remedy is the adapter's bound plus the reading this seam
    will carry once `carry-telegram-on-any-uplink` supplies it; it is not a reason to
    withdraw the rung on days when nothing is measuring.
    """
    async def probe(phone: str) -> Proof:
        if not token:
            return Proof(holds=False,
                         reason="no Telegram Gateway token is held")
        if reachability is None:
            return Proof(holds=True)
        return await reachability()

    return probe
