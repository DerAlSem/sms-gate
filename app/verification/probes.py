"""What each rung this change bears has to prove before it is offered.

A probe answers one question — "can this rung carry a verification for this number, right
now" — and answers it without placing anything. The registry does the rest: bounding the
set, refusing stale evidence, and keeping the ladder's order.

`flash_call` said that sentence until 22.09.2026 and no longer does: the account exists,
the samples are captured and the adapter is built, so the rung has a probe and is offered
wherever uCaller's credential is held. Blank credential, no offer — which is the same
answer it gave before and now gives for a reason rather than for want of code.

`sms_out` was in that sentence until 21.09.2026 and never belonged there: the modem is
this gateway's own hardware, with no account to open and no balance to fund. It is
offered now — the owner's decision of 21.09.2026, task 4.17c — and two things had to be
settled before its probe could be registered, because each of them is a way the rung
would have been offered wrongly rather than not at all.

🔴 **Its precondition is not `sms_in`'s, and writing both as `link_in_service` would have
retired `sms_in` outright.** `sms_in` sits last in the offer order and is dropped
whenever anything earlier proves itself, so an identical precondition means it is never
offered again — and `sms_in` is the whole subject of the sibling change
`verify-by-inbound-contact`. The two rungs are the two directions: this gateway sending
(`modem.can_transmit`, the command port) against the subscriber sending to us
(`modem.can_receive`, the URC port). Written that way, the state where the sender port is
gone and the reader is not is exactly the state in which asking the person to text us is
the right offer.

🔴 **The rule is part of the precondition, and it is read here rather than at the door.**
An operator the rule diverts *away* from the modem must not be offered the modem: the
answer would be honoured — a rung the rule does not name is still carried, alone, by the
owner's decision of the same day — and the code would go out over the route that operator
has been rejecting, which reads to the application as a delivery and behaves to the
person as a silence. That is the one failure this whole change exists to prevent, and it
would have been reached through the offer rather than through the ladder. Here rather
than at the door because `offer` has three call sites and a rule read at each of them is
a census; a probe is asked once, about this number, which is the shape of the question.

`tg_gateway` is the exception to that sentence, and the exception is argued rather than
assumed — see its probe below.
"""

from __future__ import annotations

from app.db import queries
from app.verification import rule
from app.verification.routes import (
    CALL_IN, FLASH_CALL, SMS_IN, SMS_OUT, TG_GATEWAY, Proof,
)


def build_probes(
    modem, *, ims_proof=None, excluding: int | None = None,
    tg_token: str = "", tg_reachability=None, ucaller_bearer: str = "",
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
        SMS_OUT: _sms_out_probe(modem),
        TG_GATEWAY: _tg_gateway_probe(tg_token, tg_reachability),
        FLASH_CALL: _flash_call_probe(ucaller_bearer),
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
        # link being in service — the same link `+CMTI` arrives on. Deliberately **not**
        # the conjunction: a sender port that is gone does not stop a message arriving,
        # and asking this rung about the sender is what made it unofferable the moment
        # `sms_out` could prove itself.
        if not modem.can_receive:
            return Proof(holds=False, reason="the modem cannot receive right now")
        return Proof(holds=True)

    return probe


def _sms_out_probe(modem):
    """The gateway's own SIM sends — if it can, and if the rule sends this number here.

    Two conditions, and the second is not a condition of the hardware. See the module
    docstring: an operator the rule diverts away from the modem must not be offered the
    modem, because the offer would be honoured and the code would go out over the route
    that operator has been rejecting.

    The operator is read from the cache and never looked up. The application's answer
    does not wait for enrichment — the owner's placement of that wait, 20.09.2026, is in
    the sender and nowhere else — and a number with no row takes the rule's
    unknown-operator entry, which is what that entry is for.

    **What is deliberately not asked is the application's template.** A probe is given a
    number and answers about the rung; which application is asking is not in the
    question, and an entitlement dressed up as a precondition would report "the modem
    cannot carry this number" for a configuration gap. That refusal is the door's, and
    it is task 4.47.

    Registration is not asked either, and that is the ladder's own shape: the sender
    holds a message back while the modem is off the network rather than failing it, so a
    momentary deregistration is a delay of seconds and not a rung that cannot carry.
    """
    async def probe(phone: str) -> Proof:
        if not modem.can_transmit:
            return Proof(holds=False, reason="the modem cannot transmit right now")
        row = await queries.get_number_operator(phone)
        operator = (row["operator"] or "").strip() if row is not None else ""
        try:
            named = rule.route_for(operator or None)
        except rule.UnreadableRule as exc:
            # The reader has already alerted. Unreadable is never read as "no rule": read
            # that way it would send every diverted operator's traffic straight back to
            # the route that is rejecting it.
            return Proof(holds=False,
                         reason=f"the routing rule cannot be read: {exc}")
        if SMS_OUT not in named:
            return Proof(
                holds=False,
                reason=f"the routing rule does not send "
                       f"{operator or 'an unresolved operator'} to the modem")
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


def _flash_call_probe(bearer):
    """The uCaller rung, offered on a held credential for the Telegram rung's own reason.

    The same asymmetry, argued the same way. Nothing uCaller will answer about a
    subscriber is free: `checkPhone` costs 0,04 ₽ and answers about the operator rather
    than about reachability, and the only question that answers reachability is placing
    the call itself. Asking during the offer would buy the rung before the blacklist, the
    per-number limits, the entitlement and the spend ceiling had run — and a gate
    evaluated after a placed call refuses something already paid for.

    What justifies offering it on a held credential is that this rung does **not** die
    silently. A dead uCaller answers: the credential is `401`, an empty account is `1002`,
    a switched-off service is `4`, and every one of them arrives over HTTP 200 inside the
    ladder's bound and wakes the operator by name. The rung that dies silently is
    `call_in`, where `RING` simply stops arriving, and that is the one this registry was
    built for.

    ⚠️ **Measured for promptness on the other rung, not on this one.** The 260 ms figure
    behind the Telegram probe's argument is the Telegram vendor's; uCaller's round trip
    was measured once and only from the backup uplink (0.17 s, 18.09.2026, task 1.12) —
    which is evidence that the host reaches it and not a bound on how long it takes to
    answer. The adapter's own timeout is what holds meanwhile.
    """
    async def probe(phone: str) -> Proof:
        if not bearer:
            return Proof(holds=False, reason="no uCaller credential is held")
        return Proof(holds=True)

    return probe
