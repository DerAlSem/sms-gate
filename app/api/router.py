import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.dependencies import get_app_id
from app.api.schemas import (
    RouteOffer, RouteSelectRequest, RouteSelectResponse, SmsSendRequest,
    SmsSendResponse, SmsStatusResponse, VerificationCheckRequest,
    VerificationCheckResponse, VerificationCreateRequest, VerificationCreateResponse,
    VerificationStatusResponse,
)
from app.db import queries
from app.lookup.operator import record_operator
from app.modem.manager import ModemManager
from app.settings_store import store
from app.verification.probes import build_probes
from app.verification.routes import CALL_IN, SMS_IN, Registry, unavailable

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/sms/send", response_model=SmsSendResponse)
async def send_sms(
    request: Request,
    body: SmsSendRequest,
    app_id: str = Depends(get_app_id),
) -> SmsSendResponse:
    if await queries.is_phone_blocked(body.phone):
        raise HTTPException(
            status_code=422,
            detail={"error": "number_blacklisted", "phone": body.phone},
        )
    await record_operator(body.phone)
    modem: ModemManager = request.app.state.modem
    message_id = await queries.create_message(app_id, body.phone, body.text)
    await modem.enqueue(message_id, body.phone, body.text, app_id)
    return SmsSendResponse(id=message_id, status="pending")


@router.get("/sms/{message_id}", response_model=SmsStatusResponse)
async def get_sms_status(
    message_id: int,
    app_id: str = Depends(get_app_id),
) -> SmsStatusResponse:
    row = await queries.get_message(message_id, app_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return SmsStatusResponse(**dict(row))


def _registry(request: Request) -> Registry:
    """The ladder, built per request from the settings in force right now.

    Per request rather than once at startup, because the order and membership are
    configuration and a change to them must not need a deployment. Building it costs a
    dictionary; what costs is the probing, and that is bounded.
    """
    modem = request.app.state.modem
    return Registry(
        probes=build_probes(modem, ims_proof=getattr(request.app.state, "ims_proof", None),
                            tg_token=store.tg_gateway_token),
        order=[name.strip() for name in store.verification_route_order.split(",")
               if name.strip()],
        probe_timeout=store.verification_probe_timeout,
        max_proof_age=store.verification_proof_max_age_seconds,
        gateway_number=store.gateway_msisdn,
    )


def _new_code(taken: set[str]) -> str:
    """Four digits, by the owner's decision of 07.09.2026, and not one already live.

    Four is enough to *attribute* an arriving answer to one open verification, which is
    the code's whole job — it is not a second factor, because the application displays it
    to whoever started the verification. What binds a person to a number is the origin of
    the event, on every route without exception.
    """
    for _ in range(100):
        code = f"{secrets.randbelow(10000):04d}"
        if code not in taken:
            return code
    raise HTTPException(
        status_code=503,
        detail={"error": "no_code_available",
                "message": "too many verifications are open for this number"},
    )


@router.post("/verifications", response_model=VerificationCreateResponse)
async def create_verification(
    request: Request,
    body: VerificationCreateRequest,
    app_id: str = Depends(get_app_id),
) -> VerificationCreateResponse:
    """Accept a number, prove the routes that can carry it, and place nothing.

    The ladder is not walked here: no vendor is asked to send, no call is placed and no
    message is composed until the consumer has selected a route. What acceptance costs is
    the set of precondition probes, bounded as a whole.
    """
    if await queries.is_phone_blocked(body.phone):
        raise HTTPException(
            status_code=422,
            detail={"error": "number_blacklisted", "phone": body.phone},
        )
    offers = await _registry(request).offer(body.phone)
    if unavailable(offers):
        # Refused in the same answer rather than opened. A verification whose only
        # possible outcome is to expire is worse than a refusal: the person waits out the
        # window for an answer that was never coming.
        raise HTTPException(
            status_code=422,
            detail={"error": "no_route_available",
                    "message": "no route can prove it can carry this number now"},
        )
    code = _new_code(await queries.open_codes_for(body.phone))
    verification_id = await queries.create_verification(
        app_id, body.phone, code=code, ttl_seconds=store.verification_ttl_seconds,
    )
    await record_operator(body.phone)
    return VerificationCreateResponse(
        id=verification_id,
        status="pending",
        routes=[RouteOffer(route=o.route, instruction=o.instruction) for o in offers],
    )


@router.post("/verifications/{verification_id}/route",
             response_model=RouteSelectResponse)
async def select_verification_route(
    request: Request,
    verification_id: int,
    body: RouteSelectRequest,
    app_id: str = Depends(get_app_id),
) -> RouteSelectResponse:
    """The consumer's choice, and the only moment a verification acquires a route.

    The offer is re-proved here rather than trusted from the creation answer. The proof
    decays after it is given, and the gap between offering and selecting is exactly where
    it decays — a rung whose precondition has since lapsed is refused with that reason
    rather than attempted.
    """
    row = await queries.get_verification(verification_id, app_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Verification not found")

    # A verification that ended is refused as ended, and before the hop check, because a
    # failed one holds a route and would otherwise be answered "already_selected" — an
    # answer about the route, which would send a consumer looking for a way to release it
    # when what actually happened is that the verification is over. Failure is terminal by
    # the owner's decision of 19.09.2026: a fresh verification carries the next attempt,
    # and the list of what remains rides on the poll of this one.
    if row["status"] != "pending":
        raise HTTPException(
            status_code=422,
            detail={"error": f"verification_{row['status']}", "reason": row["reason"],
                    "message": "this verification has ended; open a new one to try again"},
        )

    # Asked before the probes, and in this order deliberately. A verification that
    # already holds a route is not a rung that has become unavailable — it is the same
    # verification being selected twice, and the `call_in` rung's own one-window-per-number
    # rule would otherwise answer that with "not offered", which is true of the number and
    # false of the question.
    if row["route"] is not None:
        raise HTTPException(
            status_code=422,
            detail={"error": "already_selected", "route": row["route"],
                    "message": "a verification is carried by one route at a time"},
        )

    offers = {o.route for o in await _registry(request).offer(row["phone"])}
    if body.route not in offers:
        raise HTTPException(
            status_code=422,
            detail={"error": "route_not_offered", "route": body.route,
                    "message": "that route was not offered, or can no longer prove itself"},
        )
    outcome = await queries.select_route(verification_id, app_id, route=body.route)
    if outcome != "selected":
        raise HTTPException(
            status_code=422,
            detail={"error": outcome, "route": body.route},
        )
    # Nothing is placed for either rung this change bears: on both of them the subscriber
    # is the one who acts. Placing rungs hang their vendor call here.
    #
    # The one rung where the person must type the code back is the one rung where the
    # owning application is given it — it has no other way to show them. Read after the
    # selection so that a verification whose selection lost a race hands over nothing.
    # Per rung attempted, from the moment it is the rung being attempted. A ladder has
    # more than one, and "what did this person's login cost" is unanswerable from a table
    # that keeps only the last.
    await queries.record_verification_rung(verification_id, route=body.route,
                                           outcome="selected")

    if body.route == CALL_IN:
        # This rung carries its own window, and it is the rung whose residual risk scales
        # with it: an attacker can open a verification on a victim's number and, inside
        # the window, give the victim a reason to call. Clamped to the ladder's, so a
        # configuration cannot lengthen what the application was already told.
        await queries.shorten_verification_window(
            verification_id, ttl_seconds=store.verification_call_in_ttl_seconds)

    code = None
    if body.route == SMS_IN:
        selected = await queries.get_verification(verification_id, app_id)
        code = selected["code"]
    return RouteSelectResponse(
        id=verification_id, route=body.route, status="pending", code=code)


@router.post("/verifications/{verification_id}/check",
             response_model=VerificationCheckResponse)
async def check_verification(
    verification_id: int,
    body: VerificationCheckRequest,
    app_id: str = Depends(get_app_id),
) -> VerificationCheckResponse:
    outcome = await queries.check_verification(
        verification_id, app_id, code=body.code,
        max_attempts=store.verification_max_attempts,
    )
    if outcome == "not_found":
        raise HTTPException(status_code=404, detail="Verification not found")
    row = await queries.get_verification(verification_id, app_id)
    return VerificationCheckResponse(
        id=verification_id, status=row["status"], outcome=outcome,
    )


@router.get("/verifications/{verification_id}",
            response_model=VerificationStatusResponse)
async def get_verification_status(
    verification_id: int,
    request: Request,
    app_id: str = Depends(get_app_id),
) -> VerificationStatusResponse:
    row = await queries.get_verification(verification_id, app_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Verification not found")

    # A rung that failed ends the verification and the gateway does not move to another by
    # itself — but the consumer cannot make that move out of a reason string alone. What
    # is left is named here, on the failure and nowhere else, and asked of the ladder at
    # read time so the answer is as current as the one creation gives.
    #
    # The rung that failed is dropped by name rather than left to its own probe: it may
    # still prove itself perfectly well — an `sms_in` verification burns its attempts on a
    # mistyped code without `sms_in` becoming unavailable — and offering back the rung
    # that just failed is the hop this norm forbids, arriving by the other door.
    offers: list = []
    if row["status"] == "failed":
        without = {row["route"]} if row["route"] else set()
        offers = await _registry(request).offer(row["phone"], without=without)

    return VerificationStatusResponse(
        id=row["id"], phone=row["phone"], status=row["status"], route=row["route"],
        method=row["confirmed_by"], reason=row["reason"], attempts=row["attempts"],
        routes=[RouteOffer(route=o.route, instruction=o.instruction) for o in offers],
        created_at=row["created_at"], expires_at=row["expires_at"],
        confirmed_at=row["confirmed_at"],
    )
