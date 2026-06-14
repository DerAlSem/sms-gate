import logging
import secrets
from urllib.parse import urlparse

import aiosqlite
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.admin.i18n import render, resolve_locale, SUPPORTED
from app.phone import country_choices
from app.config import settings
from app.db import queries
from app.settings_store import store, SETTINGS_SPEC, SPEC_BY_KEY, validate_raw

router = APIRouter(prefix="/admin", tags=["admin"])
logger = logging.getLogger(__name__)

_basic = HTTPBasic()

PAGE_SIZE = 50


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


@router.get("/")
async def admin_root(_: str = Depends(admin_auth)) -> RedirectResponse:
    return RedirectResponse(url="/admin/messages", status_code=302)


@router.get("/messages")
async def admin_messages(
    request: Request,
    status: str | None = None,
    phone: str | None = None,
    page: int = 1,
    _: str = Depends(admin_auth),
):
    page = max(page, 1)
    offset = (page - 1) * PAGE_SIZE
    rows = await queries.list_messages(status, phone, PAGE_SIZE, offset)
    total = await queries.count_messages(status, phone)
    pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    return render(
        "messages.html",
        request,
        {
            "messages": rows,
            "status": status or "",
            "phone": phone or "",
            "page": page,
            "pages": pages,
            "total": total,
            "active": "messages",
        },
    )


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


@router.get("/inbound")
async def admin_inbound(
    request: Request,
    phone: str | None = None,
    page: int = 1,
    _: str = Depends(admin_auth),
):
    page = max(page, 1)
    offset = (page - 1) * PAGE_SIZE
    rows = await queries.list_inbound(phone, PAGE_SIZE, offset)
    total = await queries.count_inbound(phone)
    pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    return render(
        "inbound.html",
        request,
        {
            "rows": rows,
            "phone": phone or "",
            "page": page,
            "pages": pages,
            "total": total,
            "active": "inbound",
        },
    )


@router.post("/inbound/delete")
async def admin_inbound_delete(
    id: int = Form(...),
    _: str = Depends(admin_auth),
) -> RedirectResponse:
    await queries.delete_inbound(id)
    return RedirectResponse(url="/admin/inbound", status_code=303)


@router.get("/dialogs")
async def admin_dialogs(
    request: Request,
    _: str = Depends(admin_auth),
):
    rows = await queries.dialog_phones(limit=200)
    return render("dialogs.html", request, {"rows": rows, "active": "dialogs"})


@router.get("/dialogs/{phone}")
async def admin_dialog_detail(
    request: Request,
    phone: str,
    _: str = Depends(admin_auth),
):
    rows = await queries.dialog_for(phone)
    return render("dialog.html", request, {"phone": phone, "rows": rows, "active": "dialogs"})


@router.post("/dialogs/{phone}/reply")
async def admin_dialog_reply(
    request: Request,
    phone: str,
    text: str = Form(..., min_length=1, max_length=160),
    _: str = Depends(admin_auth),
) -> RedirectResponse:
    from app.lookup.operator import record_operator
    from app.phone import validate_and_normalize
    from app.settings_store import store

    try:
        phone = validate_and_normalize(phone, store.phone_region, restrict_region=False)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if await queries.is_phone_blocked(phone):
        raise HTTPException(status_code=422, detail="Number is blacklisted")
    await record_operator(phone)
    message_id = await queries.create_message("admin", phone, text)
    modem = request.app.state.modem
    await modem.enqueue(message_id, phone, text, "admin")
    return RedirectResponse(url=f"/admin/dialogs/{phone}", status_code=303)


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
    _: str = Depends(admin_auth),
):
    counts = await queries.status_counts()
    daily = await queries.daily_counts(days=14)
    by_day: dict[str, dict[str, int]] = {}
    for row in daily:
        by_day.setdefault(row["day"], {})[row["status"]] = int(row["n"])
    return render(
        "stats.html",
        request,
        {
            "counts": counts,
            "by_day": sorted(by_day.items(), reverse=True),
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
            validate_raw(SPEC_BY_KEY[key].type, raw)
        except ValueError as exc:
            errors[key] = str(exc)
    if errors:
        return render("settings.html", request, {
            "sections": _settings_view_rows(), "active": "settings", "errors": errors,
            "countries": country_choices(resolve_locale(request))})
    await store.set_many(changes)          # one transaction + section hooks (alerting reconfigure)
    return RedirectResponse(url="/admin/settings", status_code=303)


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
