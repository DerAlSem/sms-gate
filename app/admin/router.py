import json
import logging
import secrets
from urllib.parse import urlencode, urlparse

import aiosqlite
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app import periods
from app.admin import settings_layout
from app.admin.i18n import render, resolve_locale, SUPPORTED
from app.phone import country_choices, is_dialable
from app.config import settings
from app.db import queries
from app.settings_store import store, SETTINGS_SPEC, SPEC_BY_KEY, validate_raw, _TRUE

router = APIRouter(prefix="/admin", tags=["admin"])
logger = logging.getLogger(__name__)

_basic = HTTPBasic()

PAGE_SIZE = 50
DIALOG_LIMIT = 100


def admin_auth(credentials: HTTPBasicCredentials = Depends(_basic)) -> str:
    user_ok = secrets.compare_digest(
        credentials.username.encode(), settings.admin_user.encode()
    )
    pass_ok = secrets.compare_digest(
        credentials.password.encode(), settings.admin_password.encode()
    )
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


def same_origin(request: Request) -> None:
    """Refuse a destructive POST that came from another site.

    The console authenticates with HTTP Basic and carries no per-request token, so a
    browser will attach cached credentials to a cross-site form post — and this
    change introduces the first irreversible action reachable that way. A request
    with neither header is allowed through, so curl and the tests keep working: this
    is a cheap guard against a browser-driven post, not a CSRF token scheme.
    """
    origin = request.headers.get("origin") or request.headers.get("referer")
    if not origin:
        return
    ours = (request.headers.get("host") or "").split(":")[0]
    theirs = urlparse(origin).hostname or ""
    if ours and theirs and theirs != ours:
        logger.warning("cross-site %s refused: origin=%s host=%s",
                       request.url.path, theirs, ours)
        raise HTTPException(status_code=403, detail="Cross-site request refused")


def _view_query(
    period: str = "",
    phone: str = "",
    status: str = "",
    direction: str = "",
    page: int = 1,
    open: str = "",
) -> str:
    """The query string that reproduces the current view.

    Every action redirects through this, which is what makes "return to the same
    period, filters, page and expanded conversation" a property of the URL rather
    than a mechanism of its own. urlencode is not optional: a number in E.164 form
    starts with `+`, which decodes to a space.
    """
    params = [
        (key, value)
        for key, value in (
            ("period", period if period and period != periods.DEFAULT else ""),
            ("phone", phone),
            ("status", status),
            ("direction", direction),
            ("page", str(page) if page > 1 else ""),
            ("open", open),
        )
        if value
    ]
    return ("?" + urlencode(params)) if params else ""


def _parse_open(key: str | None) -> tuple[str, int] | None:
    """`out-1154` / `in-88` -> ("out", 1154). Expansion is addressed by the row, not
    by its number: a number can hold many rows in the window, and matching on the
    number would render its conversation under every one of them."""
    if not key or "-" not in key:
        return None
    direction, _, raw_id = key.partition("-")
    if direction not in ("in", "out") or not raw_id.isdigit():
        return None
    return direction, int(raw_id)


@router.get("/")
async def admin_root(_: str = Depends(admin_auth)) -> RedirectResponse:
    return RedirectResponse(url="/admin/messages", status_code=302)


@router.get("/messages")
async def admin_messages(
    request: Request,
    period: str | None = None,
    status: str | None = None,
    phone: str | None = None,
    direction: str | None = None,
    page: int = 1,
    open: str | None = None,
    _: str = Depends(admin_auth),
):
    """The SMS view: both directions in one stream, one row expandable in place."""
    period = periods.resolve(period)
    status, direction = queries.normalize_filters(status, direction)
    page = max(page, 1)
    offset = (page - 1) * PAGE_SIZE

    rows = await queries.list_thread_page(
        period, phone, status, direction, PAGE_SIZE, offset
    )
    total = await queries.count_thread_page(period, phone, status, direction)
    pages = (total + PAGE_SIZE - 1) // PAGE_SIZE

    # Expansion is resolved from the row the key names, and rendered under that row
    # only — never under every row that happens to share its number.
    open_key, dialog, dialog_total, open_phone = "", [], 0, ""
    verifications, rungs = [], {}
    parsed = _parse_open(open)
    if parsed is not None:
        row = await queries.get_thread_row(*parsed)
        if row is not None:
            open_key = f"{parsed[0]}-{parsed[1]}"
            open_phone = row["phone"]
            dialog = await queries.dialog_for(open_phone, limit=DIALOG_LIMIT)
            dialog_total = await queries.dialog_total(open_phone)
            # Beside the conversation, not on a page of its own: a support call is about
            # one person, and the question "what did their login do" is asked with their
            # messages already open.
            verifications = await queries.verifications_for_phone(open_phone)
            rungs = await queries.rungs_for_verifications([v["id"] for v in verifications])

    return render(
        "messages.html",
        request,
        {
            "messages": rows,
            "period": period,
            "periods": periods.PERIODS,
            # Built here, not in the template: this is where urlencode lives, and a
            # `+`-prefixed number pasted into a query decodes to a space.
            "period_links": {
                p: "/admin/messages"
                + _view_query(period=p, phone=phone or "", status=status,
                              direction=direction)
                for p in periods.PERIODS
            },
            "status": status,
            "phone": phone or "",
            "direction": direction,
            "page": page,
            "pages": pages,
            "total": total,
            "open_key": open_key,
            "open_phone": open_phone,
            "open_dialable": is_dialable(open_phone, store.phone_region),
            "open_blocked": (
                await queries.is_phone_blocked(open_phone) if open_phone else False
            ),
            "dialog": dialog,
            "dialog_total": dialog_total,
            "verifications": verifications,
            "rungs": rungs,
            "dialog_limit": DIALOG_LIMIT,
            "error": request.query_params.get("error"),
            "active": "messages",
        },
    )


def _back_to_view(
    period: str = "",
    phone: str = "",
    status: str = "",
    direction: str = "",
    page: int = 1,
    open: str = "",
    error: str = "",
) -> RedirectResponse:
    query = _view_query(period, phone, status, direction, page, open)
    if error:
        joiner = "&" if query else "?"
        query = f"{query}{joiner}error={error}"
    return RedirectResponse(url=f"/admin/messages{query}", status_code=303)


@router.post("/messages/{message_id}/resend")
async def admin_message_resend(
    request: Request,
    message_id: int,
    period: str = Form(""),
    page: int = Form(1),
    status: str = Form(""),
    phone: str = Form(""),
    direction: str = Form(""),
    open: str = Form(""),
    _: str = Depends(admin_auth),
) -> RedirectResponse:
    """Queue a fresh copy of a failed/expired message.

    A new row is created rather than the old one revived: the failed attempt stays
    in the history — its error is the evidence of what went wrong — and a re-send puts
    new segments on the wire under new references, which are recorded against the new
    message. A delivery report is attributed to a part, by `(message_id, seq)`, so the
    two attempts keep separate records and a report about either can still be placed.
    """
    row = await queries.get_message_any(message_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Message not found")
    if row["status"] not in ("failed", "expired"):
        raise HTTPException(
            status_code=422, detail="Only failed or expired messages can be resent"
        )
    if await queries.is_phone_blocked(row["phone"]):
        raise HTTPException(status_code=422, detail="Number is blacklisted")

    new_id = await queries.create_message(
        row["app_id"], row["phone"], row["text"], resent_from=message_id
    )
    await request.app.state.modem.enqueue(
        new_id, row["phone"], row["text"], row["app_id"]
    )
    logger.info(
        "admin resend: source=%d new=%d phone=%s", message_id, new_id, row["phone"]
    )
    return _back_to_view(period, phone, status, direction, page, open)


@router.post("/messages/reply")
async def admin_reply(
    request: Request,
    to: str = Form(...),
    # No upper bound: long texts are split into parts by the sender (UCS2 for
    # Cyrillic, 70 chars per part), so 160 was an artificial GSM-7 single-part cap.
    text: str = Form(..., min_length=1),
    period: str = Form(""),
    page: int = Form(1),
    status: str = Form(""),
    phone: str = Form(""),
    direction: str = Form(""),
    open: str = Form(""),
    _: str = Depends(admin_auth),
) -> RedirectResponse:
    from app.lookup.operator import record_operator
    from app.phone import validate_and_normalize

    try:
        to = validate_and_normalize(to, store.phone_region, restrict_region=False)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if await queries.is_phone_blocked(to):
        raise HTTPException(status_code=422, detail="Number is blacklisted")
    await record_operator(to)
    message_id = await queries.create_message("admin", to, text)
    await request.app.state.modem.enqueue(message_id, to, text, "admin")
    return _back_to_view(period, phone, status, direction, page, open)


@router.post("/messages/delete")
async def admin_message_delete(
    id: int = Form(...),
    row_direction: str = Form(...),
    period: str = Form(""),
    page: int = Form(1),
    status: str = Form(""),
    phone: str = Form(""),
    direction: str = Form(""),
    open: str = Form(""),
    _: str = Depends(admin_auth),
    __: None = Depends(same_origin),
) -> RedirectResponse:
    """Remove a message. Irreversible — there is no soft delete, so the log line is
    the only trace that survives."""
    if row_direction == "in":
        row = await queries.get_thread_row("in", id)
        if row is None:
            return _back_to_view(period, phone, status, direction, page, open,
                                 error="not_found")
        await queries.delete_inbound(id)
        logger.info("admin delete: inbound id=%d phone=%s", id, row["phone"])
        return _back_to_view(period, phone, status, direction, page, open)

    row = await queries.get_message_any(id)
    reason = await queries.delete_outbound(id)
    if reason is not None:
        return _back_to_view(period, phone, status, direction, page, open, error=reason)
    logger.info(
        "admin delete: outbound id=%d phone=%s text=%.40r",
        id, row["phone"] if row else "?", row["text"] if row else "",
    )
    return _back_to_view(period, phone, status, direction, page, open)


@router.post("/messages/block")
async def admin_message_block(
    to: str = Form(...),
    action: str = Form(...),
    period: str = Form(""),
    page: int = Form(1),
    status: str = Form(""),
    phone: str = Form(""),
    direction: str = Form(""),
    open: str = Form(""),
    _: str = Depends(admin_auth),
    __: None = Depends(same_origin),
) -> RedirectResponse:
    if not is_dialable(to, store.phone_region):
        return _back_to_view(period, phone, status, direction, page, open,
                             error="not_dialable")
    if action == "block":
        await queries.block_phone(to)
        logger.info("admin block: phone=%s", to)
    else:
        await queries.unblock_phone(to)
        logger.info("admin unblock: phone=%s", to)
    return _back_to_view(period, phone, status, direction, page, open)


@router.get("/blacklist")
async def admin_blacklist(
    request: Request,
    _: str = Depends(admin_auth),
):
    rows = await queries.list_bad_numbers()
    return render("blacklist.html", request, {"rows": rows, "active": "blacklist"})


@router.post("/blacklist/unblock")
async def admin_unblock(
    phone: str = Form(...),
    _: str = Depends(admin_auth),
) -> RedirectResponse:
    await queries.unblock_phone(phone)
    return RedirectResponse(url="/admin/blacklist", status_code=303)


# The Inbound and Dialogs tabs are gone — their content is the SMS view now. The
# paths stay answerable because they are in bookmarks and in the deep links Telegram
# alerts have already sent.


@router.get("/inbound")
async def admin_inbound(_: str = Depends(admin_auth)) -> RedirectResponse:
    return RedirectResponse(url="/admin/messages?direction=in", status_code=303)


@router.get("/dialogs")
async def admin_dialogs(_: str = Depends(admin_auth)) -> RedirectResponse:
    return RedirectResponse(url="/admin/messages", status_code=303)


@router.get("/dialogs/{phone}")
async def admin_dialog_detail(phone: str, _: str = Depends(admin_auth)) -> RedirectResponse:
    """A deep link names a conversation, so it lands with that conversation open.

    Over all time on purpose: 30-day bounding could land the link on an empty table
    with nothing to expand.
    """
    rows = await queries.list_thread_page("all", phone, None, None, 1, 0)
    open_key = f"{rows[0]['direction']}-{rows[0]['id']}" if rows else ""
    return RedirectResponse(
        url=f"/admin/messages{_view_query(period='all', phone=phone, open=open_key)}",
        status_code=303,
    )


@router.get("/ranges")
async def admin_ranges(
    request: Request,
    _: str = Depends(admin_auth),
):
    rows = await queries.list_number_operators()
    return render("ranges.html", request, {"rows": rows, "active": "ranges"})


@router.post("/ranges/backfill")
async def admin_ranges_backfill(
    _: str = Depends(admin_auth),
) -> RedirectResponse:
    from app.lookup.backfill import backfill_ranges

    result = await backfill_ranges()
    logger.info("admin-triggered backfill: %s", result)
    return RedirectResponse(url="/admin/ranges", status_code=303)


@router.get("/stats")
async def admin_stats(
    request: Request,
    period: str | None = None,
    _: str = Depends(admin_auth),
):
    period = periods.resolve(period)
    counts = await queries.status_counts(period)
    buckets = await queries.period_buckets(period)
    by_bucket: dict[str, dict[str, int]] = {}
    for row in buckets:
        by_bucket.setdefault(row["bucket"], {})[row["status"]] = int(row["n"])
    from app.verification import refusals as route_refusals
    return render(
        "stats.html",
        request,
        {
            "counts": counts,
            "refusals": await route_refusals.counts(period=period),
            # What the paid rungs cost, on the same period control as every other count
            # on this page. Here rather than on a page of its own for the reason the
            # refusals are here: an operator asking "what did the call route cost last
            # month" is asking a counters question, and the answer must come from our own
            # records rather than from the vendor's invoice.
            "spend": await queries.verification_spend(period),
            "spend_by_app": await queries.verification_spend_by_app(period),
            "rule_entries": await route_refusals.rule_entries(),
            "review_days": store.operator_route_review_days,
            "inbound_total": await queries.inbound_count(period),
            "by_bucket": sorted(by_bucket.items(), reverse=True),
            "period": period,
            "periods": periods.PERIODS,
            "period_links": {
                p: "/admin/stats" + _view_query(period=p) for p in periods.PERIODS
            },
            "active": "stats",
        },
    )


async def _render_apps(request: Request, new_id=None, new_token=None):
    apps = await queries.list_apps()
    rows = []
    for a in apps:
        rows.append({
            "id": a["id"],
            "description": a["description"] or "",
            "is_active": a["is_active"],
            # Shown beside `is_active` rather than folded into it: one answers whether
            # this application may talk to the gateway at all, the other whether it may
            # spend money doing so, and they are refused by different people.
            "may_spend": a["may_spend"],
            "token_masked": (a["token"][:6] + "…") if a["token"] else "",
            "msg_count": await queries.app_message_count(a["id"]),
            "protected": a["id"] == "admin",
        })
    return render("apps.html", request, {
        "rows": rows,
        "active": "apps",
        "new_token": new_token,
        "new_id": new_id,
        "error": request.query_params.get("error"),
    })


@router.get("/apps")
async def admin_apps(request: Request, _: str = Depends(admin_auth)):
    return await _render_apps(request)


@router.post("/apps/create")
async def admin_apps_create(
    request: Request,
    id: str = Form(...),
    description: str = Form(""),
    _: str = Depends(admin_auth),
):
    app_id = id.strip()
    if not app_id:
        return RedirectResponse(url="/admin/apps?error=empty", status_code=303)
    token = "tok_" + secrets.token_urlsafe(32)
    try:
        await queries.create_app(app_id, token, description.strip())
    except aiosqlite.IntegrityError:
        return RedirectResponse(url="/admin/apps?error=exists", status_code=303)
    return await _render_apps(request, new_id=app_id, new_token=token)


@router.post("/apps/toggle")
async def admin_apps_toggle(
    id: str = Form(...),
    active: str = Form(...),
    _: str = Depends(admin_auth),
) -> RedirectResponse:
    await queries.set_app_active(id, active == "1")
    return RedirectResponse(url="/admin/apps", status_code=303)


@router.post("/apps/entitlement")
async def admin_apps_entitlement(
    id: str = Form(...),
    may_spend: str = Form(...),
    _: str = Depends(admin_auth),
) -> RedirectResponse:
    """Grant or revoke this application's right to spend on a paid verification.

    Here rather than in the routing rule: the rule answers what reaches a subscriber and
    is keyed on the operator, this answers who is allowed to pay for it. It takes effect
    on the next verification — the gate reads the row per call, so no restart is needed,
    which is the same guarantee the rule itself has.
    """
    await queries.set_app_may_spend(id, may_spend == "1")
    return RedirectResponse(url="/admin/apps", status_code=303)


@router.post("/apps/delete")
async def admin_apps_delete(
    id: str = Form(...),
    _: str = Depends(admin_auth),
) -> RedirectResponse:
    if id != "admin" and await queries.app_message_count(id) == 0:
        await queries.delete_app(id)
    return RedirectResponse(url="/admin/apps", status_code=303)


# A route's bearer is write-only past this point: the page never carries it back out,
# whether it is the stored value or one just typed for a brand-new route in the same
# textarea. Chosen over blanking it outright because a route with a literal empty bearer
# is indistinguishable, on this page, from one that has none — and the save-time repair
# below (`_resolve_bearer_sentinel`) needs a value it can tell apart from "no bearer" and
# from anything an operator would plausibly type.
BEARER_SENTINEL = "••••••"


def _mask_bearers(raw: str) -> str:
    """Replace every non-blank `bearer` in a `routes`-typed value with the sentinel.

    Applied to the stored value only. A refused save redisplays the operator's submission
    as typed (see `_settings_view_rows`): what they just typed is already on their screen,
    and masking it would turn the next save into a silent revert to the saved bearer.

    Unparsable JSON is returned unchanged — there is nothing here to find a `bearer` in,
    and reporting the syntax error is `validate_raw`'s job, not this one's.
    """
    if not raw or not raw.strip():
        return raw
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if not isinstance(data, list):
        return raw
    changed = False
    masked = []
    for item in data:
        if isinstance(item, dict) and item.get("bearer"):
            item = dict(item)
            item["bearer"] = BEARER_SENTINEL
            changed = True
        masked.append(item)
    if not changed:
        return raw
    return json.dumps(masked, ensure_ascii=False)


def _resolve_bearer_sentinel(key: str, raw: str) -> tuple[str, str | None]:
    """Swap a still-sentinel bearer back for the saved one with the same route key.

    Runs on the submitted text before validation. A route the operator did not touch
    carries the sentinel back on save — masking is exactly what makes that page
    indistinguishable from one where the bearer *was* edited — so this is what makes
    "saved without a change" not overwrite the real bearer with six bullets. A route named
    by the sentinel with no saved match is refused: silently storing the literal sentinel
    as a bearer would be a route that fails at the vendor on the first call, which on the
    dispatch routes lands as a webhook nobody can debug from this page.

    Returns the resolved JSON text and an error message, or `None` if every sentinel
    resolved (or there was none to resolve — unparsable/malformed input is passed through
    for `validate_raw` to report as it always has).
    """
    spec = SPEC_BY_KEY[key]
    if not raw or not raw.strip():
        return raw, None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw, None                       # validate_raw reports the syntax error
    if not isinstance(data, list):
        return raw, None                       # validate_raw reports the shape error

    # A list per key, consumed in order: nothing refuses two routes with one key, and a
    # single slot would hand both sentinels the bearer of whichever came last.
    saved_by_route: dict[str, list[dict]] = {}
    saved_raw = store.get(key)
    if saved_raw:
        try:
            saved_data = json.loads(saved_raw)
        except json.JSONDecodeError:
            saved_data = []
        if isinstance(saved_data, list):
            for item in saved_data:
                if not isinstance(item, dict):
                    continue
                route_id = str(item.get(spec.route_key, "")).strip()
                if route_id:
                    saved_by_route.setdefault(route_id, []).append(item)

    error: str | None = None
    resolved = []
    for item in data:
        if isinstance(item, dict) and item.get("bearer") == BEARER_SENTINEL:
            item = dict(item)
            route_id = str(item.get(spec.route_key, "")).strip()
            candidates = saved_by_route.get(route_id)
            match = candidates.pop(0) if candidates else None
            if match is not None:
                item["bearer"] = match.get("bearer", "")
            elif error is None:
                error = (
                    f"bearer is hidden, and no saved route has "
                    f"{spec.route_key}={route_id!r} — enter the bearer"
                )
        resolved.append(item)
    return json.dumps(resolved, ensure_ascii=False), error


def _settings_view_rows(overrides: dict[str, str] | None = None):
    """The sections `settings.html` renders, in `settings_layout.SECTIONS` order.

    `overrides` carries the raw, as-submitted text for the keys of the one section a
    refused save came from — every other section renders the stored value, which is what
    keeps an error in one section from disturbing what another shows. A secret is never
    taken from `overrides`: it is either blank (kept) or not validated at all (`str`), so
    what changed, if anything, is exactly what is already stored, and the field says only
    whether it is configured, never a value — submitted or stored.

    The grouping itself — which section a key falls in, its label and its help text —
    comes entirely from `settings_layout`; `Spec.section` here is only ever used to look
    a spec up, never to group it.
    """
    overrides = overrides or {}
    rows_by_key: dict[str, dict] = {}
    for spec in SETTINGS_SPEC:
        if spec.is_secret:
            current = store.get(spec.key)
            value = ""
            configured = bool(current)
        elif spec.key in overrides:
            raw = overrides[spec.key]
            if spec.type == "bool":
                value = raw.strip().lower() in _TRUE
            elif spec.type == "routes":
                # As submitted: an untouched bearer already arrives as the sentinel, and
                # one just typed must come back as typed. Masking it here would put the
                # sentinel in its place, and the next save would quietly resolve that to
                # the OLD saved bearer — the edit lost behind a green save.
                value = raw
            else:
                value = raw
            configured = None
        else:
            current = store.get(spec.key)
            value = _mask_bearers(current) if spec.type == "routes" else current
            configured = None
        field_layout = settings_layout.FIELD_BY_KEY[spec.key]
        rows_by_key[spec.key] = {
            "key": spec.key,
            "type": spec.type,
            "is_secret": spec.is_secret,
            "label": field_layout.label,
            "help": field_layout.help,
            "value": value,
            "configured": configured,
            "changed": settings_layout.is_changed(spec),
        }
    sections = []
    for section in settings_layout.SECTIONS:
        fields = [rows_by_key[f.key] for f in section.fields]
        sections.append({
            "id": section.id,
            "title": section.title,
            "collapsed": section.collapsed,
            "fields": fields,
            "changed_count": sum(1 for f in fields if f["changed"]),
        })
    return sections


@router.get("/settings")
async def admin_settings(request: Request, _: str = Depends(admin_auth)):
    return render("settings.html", request, {
        "sections": _settings_view_rows(), "active": "settings", "errors": {},
        "saved": request.query_params.get("saved", ""),
        "countries": country_choices(resolve_locale(request)),
        "tg_account": settings_layout.tg_account_overview()})


@router.post("/settings")
async def admin_settings_save(request: Request, _: str = Depends(admin_auth)):
    form = await request.form()
    section = str(form.get("_section", ""))
    submitted: dict[str, str] = {}         # as typed, for redisplay on refusal
    changes: dict[str, str] = {}           # to validate and save
    errors: dict[str, str] = {}
    for spec in SETTINGS_SPEC:
        if spec.key not in form:
            continue
        raw = str(form[spec.key])
        submitted[spec.key] = raw
        if spec.is_secret and raw == "":
            continue                       # blank secret = leave unchanged
        if spec.type == "routes":
            raw, bearer_error = _resolve_bearer_sentinel(spec.key, raw)
            if bearer_error:
                errors[spec.key] = bearer_error
                continue                   # unresolved sentinel: nothing to validate yet
        changes[spec.key] = raw
    for key, raw in changes.items():
        try:
            spec = SPEC_BY_KEY[key]
            validate_raw(spec.type, raw, spec.route_key)
        except ValueError as exc:
            errors[key] = str(exc)
    if not errors:
        try:
            # One transaction + section hooks (e.g. alerting reconfigure).
            await store.set_many(changes)
        except ValueError as exc:
            # The one refusal `set_many` itself can raise: a brand with no rate bound.
            # It names an account, not a field, so both settings that together decide the
            # bound carry the message — neither is wrong on its own.
            errors["messenger_brands"] = str(exc)
            errors["messenger_limits"] = str(exc)
    if errors:
        return render("settings.html", request, {
            "sections": _settings_view_rows(submitted), "active": "settings",
            "errors": errors, "saved": "",
            "countries": country_choices(resolve_locale(request)),
            "tg_account": settings_layout.tg_account_overview()})
    query = ("?" + urlencode({"saved": section})) if section else ""
    fragment = f"#{section}" if section else ""
    return RedirectResponse(url=f"/admin/settings{query}{fragment}", status_code=303)


@router.get("/modem")
async def admin_modem(request: Request, _: str = Depends(admin_auth)):
    diag = await request.app.state.modem.collect_diagnostics()
    return render("modem.html", request, {"diag": diag, "active": "modem"})


@router.get("/modem.json")
async def admin_modem_json(request: Request, _: str = Depends(admin_auth)):
    return JSONResponse(await request.app.state.modem.collect_diagnostics())


@router.get("/lang/{code}")
async def admin_set_lang(
    code: str,
    request: Request,
    _: str = Depends(admin_auth),
) -> RedirectResponse:
    parsed = urlparse(request.headers.get("referer", ""))
    target = parsed.path if parsed.path.startswith("/admin") else "/admin/messages"
    if parsed.path.startswith("/admin") and parsed.query:
        target = f"{target}?{parsed.query}"
    resp = RedirectResponse(url=target, status_code=303)
    if code in SUPPORTED:
        resp.set_cookie("lang", code, max_age=31_536_000, httponly=True,
                        path="/admin", samesite="lax")
    return resp
