import asyncio
import logging
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.dependencies import get_app_id
from app.api.schemas import (
    RouteOffer, RouteSelectRequest, RouteSelectResponse, SmsSendRequest,
    SmsSendResponse, SmsStatusResponse, VerificationCheckRequest,
    VerificationCheckResponse, VerificationCreateRequest, VerificationCreateResponse,
    VerificationStatusResponse,
)
from app.db import queries
from app.lookup.operator import record_operator, resolve_within_bound
from app.modem.manager import ModemManager
from app.settings_store import store
from app.verification import placement, routes as routes_vocab, template, ucaller
from app.verification.probes import build_probes
from app.verification.tg_callback import PATH as TG_CALLBACK_PATH, handle_callback
from app.verification.routes import CALL_IN, SMS_IN, Registry, unavailable

router = APIRouter()
logger = logging.getLogger(__name__)

# Strong references to the spawned lookups: the event loop holds tasks weakly, and a
# lookup collected mid-flight would leave the number unresolved with nothing said.
_lookup_tasks: set = set()


def _spawn_lookup(phone: str) -> None:
    """Resolve this number's operator behind the answer, never in front of it."""
    async def run() -> None:
        try:
            await record_operator(phone)
        except Exception:
            # Enrichment failing is not the caller's problem and never was. Logged
            # rather than swallowed, because a resolver that has been dead for a week
            # is something an operator should be able to find in the journal.
            logger.exception("operator lookup failed for %s", phone)

    task = asyncio.create_task(run())
    _lookup_tasks.add(task)
    task.add_done_callback(_lookup_tasks.discard)



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
    # Spawned, never awaited. The lookup is enrichment and the application is not
    # waiting for it — an unreachable resolver used to show up here as a slow API, five
    # seconds per number nobody had messaged before. What routing needs from it is read
    # by the sender, which has its own bound and is not in front of anybody's HTTP
    # request (`ModemManager._operator_for`).
    _spawn_lookup(body.phone)
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
                            tg_token=store.tg_gateway_token,
                            ucaller_bearer=ucaller.configured_bearer() or ""),
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
        # `0000` is four digits and outside uCaller's range, which the vendor states as
        # 0001–9999 while explaining why `code` is a string. Minted, it would be a
        # verification the `flash_call` rung could not carry at all — one in ten thousand,
        # advancing to another rung without anybody being told, which is the invisible
        # failure this change exists to remove. Redrawn rather than the draw narrowed, so
        # that the digits a draw produces are the digits themselves.
        if code != "0000" and code not in taken:
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
    if not any(routes_vocab.carries_a_code_without_our_words(o.route) for o in offers) \
            and not template.for_app(app_id):
        # 4.47. Every rung left to this verification carries a code only inside wording
        # this gateway composes, and this application has configured none — so the code
        # could never be written down, whichever rung the consumer picks. Refused here
        # rather than at the rung, because the requirement forbids accepting a request
        # the gateway already knows it cannot fulfil in order to fail it afterwards: an
        # acceptance would spend a code, a row and the person's patience to say this.
        #
        # 🔴 **Keyed on the rungs that are left, never on the routing rule.** The rule
        # naming `sms_out` for this operator does not mean this verification needs our
        # words: a rung the rule does not name is still carried alone (the owner's
        # decision of 21.09.2026), so a consumer offered the Telegram rung may pick it
        # and be carried with no text of ours anywhere. Keyed on the rule, this would
        # refuse requests the gateway can in fact fulfil — the same requirement's other
        # half, read backwards.
        raise HTTPException(
            status_code=422,
            detail={"error": "no_template",
                    "message": "every route left for this number carries a code only "
                               "inside a message this gateway composes, and this "
                               "application has no verification template configured"},
        )
    code = _new_code(await queries.open_codes_for(body.phone))
    verification_id = await queries.create_verification(
        app_id, body.phone, code=code, ttl_seconds=store.verification_ttl_seconds,
    )
    # Resolved under the routing bound, and only where there is no operator at all: a
    # stale row still names one, and refreshing it changes no routing decision this rule
    # can make. Measured 22.09.2026 — this door used to refresh unconditionally, so a row
    # 400 days old held the request for three seconds on the resolver's own timeout,
    # which bounds the patience of one HTTP call and not what a person waits at a
    # barrier. The waiting that is owed is the other case, and it is owed: the answer
    # names a method, and the numbers with no row are first-time numbers, which is who a
    # confirmation code is usually for.
    await resolve_within_bound(body.phone)
    return VerificationCreateResponse(
        id=verification_id,
        status="pending",
        routes=[RouteOffer(route=o.route, instruction=o.instruction, number=o.number)
               for o in offers],
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
    # Per rung attempted, from the moment it is the rung being attempted. A ladder has
    # more than one, and "what did this person's login cost" is unanswerable from a table
    # that keeps only the last.
    #
    # 🔴 **Only for the rungs nothing is placed for.** A rung the gateway itself places
    # gets its row from `ladder.walk`, written before the carrier is called, and a second
    # row here would not be bookkeeping — it would be money. Both ceilings count *every*
    # row on a paid route whatever its outcome (deliberately: an ability check that never
    # answered may have been charged without our learning its `request_id`), so two rows
    # for one attempt halve them for the one rung that actually spends. And it is
    # self-blocking: that row is a paid attempt aged zero seconds, the minimum gap between
    # two of them ships at fifteen, and the per-number gate would refuse every Gateway
    # selection with `too_soon` — while looking exactly like a gate doing its job.
    if not placement.places_here(body.route):
        await queries.record_verification_rung(verification_id, route=body.route,
                                               outcome="selected")

    if body.route == CALL_IN:
        # This rung carries its own window, and it is the rung whose residual risk scales
        # with it: an attacker can open a verification on a victim's number and, inside
        # the window, give the victim a reason to call. Clamped to the ladder's, so a
        # configuration cannot lengthen what the application was already told.
        await queries.shorten_verification_window(
            verification_id, ttl_seconds=store.verification_call_in_ttl_seconds)

    if placement.places_here(body.route):
        return await _walk_the_ladder(verification_id, app_id=app_id, row=row,
                                      route=body.route,
                                      modem=request.app.state.modem)

    # The one rung where the person must type the code back is the one rung where the
    # owning application is given it — it has no other way to show them. Read after the
    # selection so that a verification whose selection lost a race hands over nothing.
    code = None
    if body.route == SMS_IN:
        selected = await queries.get_verification(verification_id, app_id)
        code = selected["code"]
    return RouteSelectResponse(
        id=verification_id, route=body.route, status="pending", code=code)


async def _walk_the_ladder(
    verification_id: int, *, app_id: str, row, route: str, modem,
) -> RouteSelectResponse:
    """Carry a rung the gateway itself places, and answer with the method it took.

    The answer is read back from the store rather than composed from the walk, so that it
    cannot claim an outcome the record does not hold — the one failure mode a door like
    this has is telling the application something the database disagrees with.

    The operator is read rather than resolved: `POST /verifications` already awaited the
    lookup, and a door that waited again would pay five seconds for a number nobody has
    ever messaged, in front of a person standing at a barrier. An unresolved operator is
    handed on as None and the rule's `?` entry answers for it — which is what it is for.
    """
    operator_row = await queries.get_number_operator(row["phone"])
    walk = await placement.place(
        verification_id, app_id=app_id,
        operator=operator_row["operator"] if operator_row else None,
        phone=row["phone"], route=route, modem=modem,
    )
    if walk.refused_by and walk.carried_by is None:
        # Refused before any rung was contacted: nothing was placed, nothing was charged,
        # and this is emphatically not a vendor failure. Answered as a refusal rather than
        # as a 200 the consumer would have to poll to find the truth of.
        raise HTTPException(
            status_code=422,
            detail={"error": "refused", "route": route, "reason": walk.refused_by,
                    "message": "this verification was refused before any rung was "
                               "contacted; nothing was placed"},
        )
    carried = await queries.get_verification(verification_id, app_id)
    return RouteSelectResponse(
        id=verification_id,
        # The rung that carried, never the one chosen — and where nothing carried, the
        # record still holds the selection, which is the honest answer to "by what".
        route=carried["route"] or route,
        status=carried["status"],
        reason=carried["reason"],
        # Never on a rung the gateway carries: a code handed back here would let the
        # application confirm without the person ever being reached.
        code=None,
    )


@router.post(TG_CALLBACK_PATH)
async def tg_gateway_callback(request: Request):
    """Where the Telegram Gateway reports what became of a message it took.

    The one door on this router with no `Depends(get_app_id)`, and deliberately: the
    vendor holds no application token. Its signature is what stands in place of one, and
    it is checked before anything is read or changed.

    ⚠️ The literal `tg-callback` does **not** today compete with
    `/verifications/{verification_id}` — that one is a GET, and every parameterised
    sibling takes three path segments where this takes two. It would compete the moment
    a two-segment `POST /verifications/{something}` is added, and FastAPI resolves such
    a competition by declaration order, silently answering the vendor with a 422 it can
    do nothing about. Whoever adds that route owns this sentence.

    A refused callback answers 403 and says no more than that: which half of the check
    failed is our business, not the caller's.
    """
    outcome = await handle_callback(
        await request.body(),
        timestamp=request.headers.get("X-Request-Timestamp", ""),
        signature=request.headers.get("X-Request-Signature", ""),
        token=store.tg_gateway_token,
        tolerance=store.tg_gateway_callback_tolerance_seconds,
        now=time.time(),
    )
    if not outcome.accepted:
        raise HTTPException(status_code=403, detail="callback refused")
    return {"ok": True}


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
        routes=[RouteOffer(route=o.route, instruction=o.instruction, number=o.number)
               for o in offers],
        created_at=row["created_at"], expires_at=row["expires_at"],
        confirmed_at=row["confirmed_at"],
    )
