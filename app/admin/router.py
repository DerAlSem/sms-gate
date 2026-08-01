import logging
import secrets
from urllib.parse import urlencode, urlparse

import aiosqlite
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app import periods
from app.admin.i18n import render, resolve_locale, SUPPORTED
from app.phone import country_choices, is_dialable
from app.config import settings
from app.db import queries
from app.settings_store import store, SETTINGS_SPEC, SPEC_BY_KEY, validate_raw

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
    parsed = _parse_open(open)
    if parsed is not None:
        row = await queries.get_thread_row(*parsed)
        if row is not None:
            open_key = f"{parsed[0]}-{parsed[1]}"
            open_phone = row["phone"]
            dialog = await queries.dialog_for(open_phone, limit=DIALOG_LIMIT)
            dialog_total = await queries.dialog_total(open_phone)

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
    in the history (its error is the evidence of what went wrong), and delivery
    reports key off `modem_ref`, which a re-send necessarily changes.
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
    return render(
        "stats.html",
        request,
        {
            "counts": counts,
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


@router.post("/apps/delete")
async def admin_apps_delete(
    id: str = Form(...),
    _: str = Depends(admin_auth),
) -> RedirectResponse:
    if id != "admin" and await queries.app_message_count(id) == 0:
        await queries.delete_app(id)
    return RedirectResponse(url="/admin/apps", status_code=303)


def _settings_view_rows():
    sections: dict[str, list] = {}
    for spec in SETTINGS_SPEC:
        current = store.get(spec.key)
        sections.setdefault(spec.section, []).append({
            "key": spec.key,
            "type": spec.type,
            "section": spec.section,
            "is_secret": spec.is_secret,
            "description": spec.description,
            "value": "" if spec.is_secret else current,
            "configured": bool(current) if spec.is_secret else None,
        })
    return sections


@router.get("/settings")
async def admin_settings(request: Request, _: str = Depends(admin_auth)):
    return render("settings.html", request, {
        "sections": _settings_view_rows(), "active": "settings", "errors": {},
        "countries": country_choices(resolve_locale(request))})


@router.post("/settings")
async def admin_settings_save(request: Request, _: str = Depends(admin_auth)):
    form = await request.form()
    changes: dict[str, str] = {}
    for spec in SETTINGS_SPEC:
        if spec.key not in form:
            continue
        raw = str(form[spec.key])
        if spec.is_secret and raw == "":
            continue                       # blank secret = leave unchanged
        changes[spec.key] = raw
    errors: dict[str, str] = {}
    for key, raw in changes.items():
        try:
            spec = SPEC_BY_KEY[key]
            validate_raw(spec.type, raw, spec.route_key)
        except ValueError as exc:
            errors[key] = str(exc)
    if errors:
        return render("settings.html", request, {
            "sections": _settings_view_rows(), "active": "settings", "errors": errors,
            "countries": country_choices(resolve_locale(request))})
    await store.set_many(changes)          # one transaction + section hooks (alerting reconfigure)
    return RedirectResponse(url="/admin/settings", status_code=303)


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
