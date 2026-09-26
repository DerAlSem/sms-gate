import json
import logging
import secrets
from urllib.parse import quote, urlencode, urlparse

import aiosqlite
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse, HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app import periods
from app.admin import settings_layout
from app.admin.i18n import get_translations, render, resolve_locale, SUPPORTED
from app.phone import country_choices, is_dialable
from app.config import settings
from app.db import queries
from app.routing import config as route_config
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



# The gateway's own senders: `admin` (a resend from this console) and `telegram` (a reply
# to a notification). They send free text, never a verification code, so having no SMS
# template is their normal state rather than a gap to flag in red.
_INTERNAL_SENDERS = frozenset({"admin", "telegram"})

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
    from app.verification import template as verification_template

    apps = await queries.list_apps()
    # Read once for every row, not once per row: it is one setting shared by every
    # application, so a broken store is a fact about the page, not about any one app.
    try:
        templates_by_app = verification_template.parse(
            store.get("verification_templates") or ""
        )
        templates_unreadable = False
    except verification_template.UnreadableTemplates:
        templates_by_app = {}
        templates_unreadable = True
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
            # SG-33.5: keyed on (app_id, route) since SG-34 — an SMS goes out when
            # sms_out has its own entry or the application's entry with no route.
            "has_template": (
                (a["id"], "sms_out") in templates_by_app
                or (a["id"], None) in templates_by_app
            ),
            "internal": a["id"] in _INTERNAL_SENDERS,
            "templates_unreadable": templates_unreadable,
        })
    # review #1: an id with a leftover record in one of the three app-owned settings,
    # but no row in `apps` (the application was deleted) — the list names it, since
    # it no longer has a row of its own to be named from.
    existing_ids = {a["id"] for a in apps}
    leftover_ids = sorted(_app_ids_with_leftover_records() - existing_ids)
    return render("apps.html", request, {
        "rows": rows,
        "active": "apps",
        "new_token": new_token,
        "new_id": new_id,
        "error": request.query_params.get("error"),
        "leftover_ids": leftover_ids,
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


# --------------------------------------------------------------------- app detail page
#
# SG-33.4: an application's own settings — its verification template, its delivery
# webhook, the messenger brands it may send under — used to be edited as raw JSON on
# the settings screen, keyed by `app_id` among every other application's rows. Storage
# is unchanged (the same three `settings` keys, the same store validators); this page
# only ever reads and rewrites the one entry (or, for brands, the one `apps[app_id]`
# key) that belongs to the application whose page it is.


def _find_app_entry(raw: str, id_field: str, app_id: str) -> tuple[dict | None, int]:
    """This application's entry in a stored `routes`/`templates`-shaped list, and how
    many further entries for the same id also exist.

    Unparsable or non-list stored raw reads as no entries — reading has to survive a
    broken store so the page can render at all (and say the store is broken); refusing
    to *save* from one is `_replace_app_entry`'s job below.
    """
    try:
        data = json.loads(raw) if raw and raw.strip() else []
    except json.JSONDecodeError:
        data = []
    if not isinstance(data, list):
        data = []
    matches = [
        item for item in data
        if isinstance(item, dict) and str(item.get(id_field, "")) == app_id
    ]
    first = matches[0] if matches else None
    return first, max(0, len(matches) - 1)


def _app_ids_in_list(raw: str) -> set[str]:
    """Every `app_id` named in a `routes`/`templates`-shaped stored value.

    Used only to notice a leftover record belongs to no row in `apps` — reading has to
    survive a broken store here too, so an unparsable value simply names none.
    """
    try:
        data = json.loads(raw) if raw and raw.strip() else []
    except json.JSONDecodeError:
        return set()
    if not isinstance(data, list):
        return set()
    return {
        str(item["app_id"]).strip() for item in data
        if isinstance(item, dict) and str(item.get("app_id", "")).strip()
    }


def _app_ids_in_brands(raw: str) -> set[str]:
    """Every `app_id` named in `messenger_brands`'s `apps` map, tolerant of a broken
    store for the same reason `_app_ids_in_list` is."""
    try:
        data = json.loads(raw) if raw and raw.strip() else {}
    except json.JSONDecodeError:
        return set()
    if not isinstance(data, dict):
        return set()
    apps = data.get("apps")
    if not isinstance(apps, dict):
        return set()
    return {str(k) for k in apps}


def _app_ids_with_leftover_records() -> set[str]:
    """Every application id named in the three settings this page edits, read live —
    including one with no row in `apps` at all: the application that made it is gone,
    but the record it left behind still blocks a save that would touch it (a template
    list is validated whole, a brand an orphan permits is still a brand). Such an id
    gets a page — SG-33.4 review #1 — rather than a 404 that leaves the record
    reachable only by hand.
    """
    return (
        _app_ids_in_list(store.get("verification_templates") or "")
        | _app_ids_in_list(store.get("delivery_dispatch") or "")
        | _app_ids_in_brands(store.get("messenger_brands") or "")
    )


def _replace_app_entry(
    raw: str, id_field: str, app_id: str, new_entry: dict | None, *, key: str
) -> str:
    """The stored list with only this application's entry replaced (or removed).

    Only the *first* matching entry is touched. Every other entry — including a
    further one for this same `app_id`, which the page says does not act — is kept
    exactly as stored, in the same position: this page edits the one record that
    `find_route`/`for_app` actually use, and nothing else about the setting.

    Raises `ValueError` when `raw` is non-blank but does not read as a JSON list —
    review #2: building "the rest of the list" from nothing here would silently erase
    every other application's record in it the moment this one is saved, and that is
    worse than refusing outright.
    """
    if raw and raw.strip():
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"the stored {key} cannot be read ({exc}) — saving would erase every "
                "other application's records in it"
            ) from exc
        if not isinstance(data, list):
            raise ValueError(
                f"the stored {key} is not a JSON list — saving would erase every "
                "other application's records in it"
            )
    else:
        data = []
    out = []
    done = False
    for item in data:
        is_match = isinstance(item, dict) and str(item.get(id_field, "")) == app_id
        if is_match and not done:
            done = True
            if new_entry is not None:
                out.append(new_entry)
            continue
        out.append(item)
    if new_entry is not None and not done:
        out.append(new_entry)
    return json.dumps(out, ensure_ascii=False)


def _load_brands_object_or_refuse(raw: str) -> dict:
    """`messenger_brands` as a JSON object, refusing a non-blank value that is not one
    — the brands-block save below only ever rewrites `apps[app_id]` inside it, and
    rebuilding "the rest" from `{}` would erase every other key (review #2, the
    `messenger_brands`-shaped half of it)."""
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"the stored messenger_brands cannot be read ({exc}) — saving would erase "
            "every other application's binding in it"
        ) from exc
    if not isinstance(data, dict):
        raise ValueError(
            "the stored messenger_brands is not a JSON object — saving would erase "
            "every other application's binding in it"
        )
    return data


# SG-33.5: since SG-34 a template entry is keyed on (app_id, route) — `route` absent for
# the entry that stands in for every worded rung. The page edits one slot per key, and
# the form field each is posted as; the no-route slot keeps the name it had in SG-33.4.
_TEMPLATE_SLOTS = (
    ("template", None),
    ("template_sms_out", "sms_out"),
    ("template_tg_user", "tg_user"),
)


def _template_route(item: dict) -> str | None:
    """The entry's route as `template.parse` reads it: blank and absent are both None."""
    route = item.get("route")
    route = str(route).strip() if route is not None else ""
    return route or None


def _app_templates(raw: str, app_id: str) -> dict[str | None, str]:
    """This application's template text per route, first entry per slot winning —
    tolerant of a broken store for the same reason `_find_app_entry` is."""
    try:
        data = json.loads(raw) if raw and raw.strip() else []
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, list):
        return {}
    out: dict[str | None, str] = {}
    for item in data:
        if isinstance(item, dict) and str(item.get("app_id", "")).strip() == app_id:
            out.setdefault(_template_route(item), str(item.get("template", "")))
    return out


def _replace_app_templates(
    raw: str, app_id: str, texts: dict[str | None, str]
) -> str:
    """The stored template list with this application's entries for the routes in
    `texts` replaced in place (blank text removes the entry, a new one is appended).

    Every other entry — another application's, or this one's for a route not in
    `texts` — is kept as stored and where it stood. Refuses an unreadable store for the
    reason `_replace_app_entry` does.
    """
    key = "verification_templates"
    if raw and raw.strip():
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"the stored {key} cannot be read ({exc}) — saving would erase every "
                "other application's records in it"
            ) from exc
        if not isinstance(data, list):
            raise ValueError(
                f"the stored {key} is not a JSON list — saving would erase every "
                "other application's records in it"
            )
    else:
        data = []

    def entry(route: str | None) -> dict | None:
        text = texts[route]
        if not text.strip():
            return None
        new = {"app_id": app_id}
        if route is not None:
            new["route"] = route
        new["template"] = text
        return new

    out = []
    done: set[str | None] = set()
    for item in data:
        if isinstance(item, dict) and str(item.get("app_id", "")).strip() == app_id:
            route = _template_route(item)
            if route in texts and route not in done:
                done.add(route)
                new = entry(route)
                if new is not None:
                    out.append(new)
                continue
        out.append(item)
    for route in texts:
        if route not in done:
            new = entry(route)
            if new is not None:
                out.append(new)
    return json.dumps(out, ensure_ascii=False)


async def _save_app_entry_field(
    key: str, id_field: str, app_id: str, new_entry: dict | None
) -> str | None:
    """Replace this application's entry in `key`'s stored list, validate, save.

    Returns the validator's message on refusal, or `None` on success — the same pair
    (`validate_raw` then `store.set_many`) the settings screen saves every structured
    setting through, so a rule enforced there is enforced here too.
    """
    spec = SPEC_BY_KEY[key]
    try:
        new_raw = _replace_app_entry(
            store.get(key) or "", id_field, app_id, new_entry, key=key
        )
        validate_raw(spec.type, new_raw, spec.route_key)
        await store.set_many({key: new_raw})
    except ValueError as exc:
        return str(exc)
    return None


async def _render_app_detail(
    request: Request,
    app_id: str,
    *,
    saved: str = "",
    errors: dict[str, str] | None = None,
    overrides: dict[str, object] | None = None,
) -> HTMLResponse:
    app_row = await queries.get_app_full(app_id)
    orphan = False
    if app_row is None:
        # review #1: no row in `apps` is a 404 only when nothing else names this id
        # either — a leftover record in one of the three settings this page edits
        # still needs a page, so it can be fixed or cleared.
        if app_id not in _app_ids_with_leftover_records():
            raise HTTPException(status_code=404, detail="Application not found")
        orphan = True
        app_row = {"id": app_id, "description": "", "is_active": False, "may_spend": False}
    errors = errors or {}
    overrides = overrides or {}

    stored_templates = _app_templates(
        store.get("verification_templates") or "", app_id
    )
    template_values = {
        field: overrides.get(field, stored_templates.get(route, ""))
        for field, route in _TEMPLATE_SLOTS
    }

    hook_entry, hook_extra = _find_app_entry(
        store.get("delivery_dispatch") or "", "app_id", app_id
    )
    webhook_url_value = overrides.get(
        "webhook_url", (hook_entry or {}).get("webhook_url", "")
    )
    bearer_configured = bool((hook_entry or {}).get("bearer"))

    parsed_brands = route_config.parse_brands(store.get("messenger_brands") or "")
    available_brands = sorted(parsed_brands["brands"].keys())
    current_app_brands = parsed_brands["apps"].get(app_id)
    if not isinstance(current_app_brands, dict):
        current_app_brands = {}
    stored_selected = current_app_brands.get("brands", [])
    if not isinstance(stored_selected, list):
        stored_selected = []
    selected_brands = overrides.get("brands", stored_selected)
    default_brand = overrides.get(
        "default_brand", str(current_app_brands.get("default", ""))
    )

    return render("app_detail.html", request, {
        "active": "apps",
        "app": app_row,
        "orphan": orphan,
        "template_values": template_values,
        "webhook_url_value": webhook_url_value,
        "bearer_configured": bearer_configured,
        "webhook_extra": hook_extra,
        "available_brands": available_brands,
        "selected_brands": selected_brands,
        "default_brand": default_brand,
        "errors": errors,
        "saved": saved,
    })


@router.get("/apps/{app_id:path}")
async def admin_app_detail(
    request: Request,
    app_id: str,
    _: str = Depends(admin_auth),
):
    return await _render_app_detail(
        request, app_id, saved=request.query_params.get("saved", "")
    )


@router.post("/apps/{app_id:path}/save")
async def admin_app_detail_save(
    request: Request,
    app_id: str,
    _: str = Depends(admin_auth),
):
    # review #3: a separate suffix rather than POST on the same path as the GET —
    # `/apps/{app_id}` collided with the literal `/apps/create|toggle|entitlement|
    # delete` routes only by accident of no application ever being named one of
    # those; an application actually named `delete` made the collision real.
    # review #1: an id with no row in `apps` may still hold a leftover record this
    # page exists to fix or clear, so existence is the same check `_render_app_detail`
    # makes, not a plain 404 on a missing row.
    if (await queries.get_app_full(app_id)) is None:
        if app_id not in _app_ids_with_leftover_records():
            raise HTTPException(status_code=404, detail="Application not found")

    form = await request.form()
    part = str(form.get("_part", ""))
    errors: dict[str, str] = {}
    overrides: dict[str, object] = {}

    if part == "template":
        # A slot absent from the form is left as stored; a blank one removes its entry.
        texts: dict[str | None, str] = {}
        for field, route in _TEMPLATE_SLOTS:
            value = form.get(field)
            if value is None:
                continue
            texts[route] = str(value)
            overrides[field] = str(value)
        spec = SPEC_BY_KEY["verification_templates"]
        try:
            new_raw = _replace_app_templates(
                store.get("verification_templates") or "", app_id, texts
            )
            validate_raw(spec.type, new_raw, spec.route_key)
            await store.set_many({"verification_templates": new_raw})
        except ValueError as exc:
            errors["template"] = str(exc)

    elif part == "webhook":
        url = str(form.get("webhook_url", "")).strip()
        overrides["webhook_url"] = url
        old_entry, _extra = _find_app_entry(
            store.get("delivery_dispatch") or "", "app_id", app_id
        )
        old_bearer = str((old_entry or {}).get("bearer", "") or "")
        clear_bearer = str(form.get("clear_bearer", "")) == "true"
        typed_bearer = str(form.get("bearer", ""))
        if url:
            if clear_bearer:
                bearer = ""
            elif typed_bearer:
                bearer = typed_bearer
            else:
                bearer = old_bearer
            new_entry = {"app_id": app_id, "webhook_url": url}
            if bearer:
                new_entry["bearer"] = bearer
        else:
            new_entry = None
        error = await _save_app_entry_field(
            "delivery_dispatch", "app_id", app_id, new_entry
        )
        if error:
            errors["webhook"] = error

    elif part == "brands":
        checked = [str(b) for b in form.getlist("brands")]
        default_brand = str(form.get("default", ""))
        overrides["brands"] = checked
        overrides["default_brand"] = default_brand
        try:
            data = _load_brands_object_or_refuse(store.get("messenger_brands") or "")
            apps = dict(data.get("apps")) if isinstance(data.get("apps"), dict) else {}
            if checked:
                entry: dict = {"brands": checked}
                if default_brand:
                    entry["default"] = default_brand
                apps[app_id] = entry
            else:
                apps.pop(app_id, None)
            data["apps"] = apps
            new_raw = json.dumps(data, ensure_ascii=False)
            validate_raw("brands", new_raw)
            await store.set_many({"messenger_brands": new_raw})
        except ValueError as exc:
            errors["brands"] = str(exc)

    else:
        raise HTTPException(status_code=400, detail="Unknown form part")

    if errors:
        return await _render_app_detail(
            request, app_id, errors=errors, overrides=overrides
        )
    # review #4: `app_id` reaches this f-string as the decoded path parameter, so a
    # literal "#" or "?" in it must be re-encoded before it goes back into a URL, or
    # it is read as the start of the fragment/query rather than as part of the id.
    return RedirectResponse(
        url=f"/admin/apps/{quote(app_id, safe='/')}?saved={part}#{part}",
        status_code=303,
    )


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


def _format_json_for_display(raw: str) -> str:
    """Pretty-print a JSON value for the settings screen's own read-only display.

    Applied to the stored value only — same reasoning as `_mask_bearers` and
    `_strip_apps_for_display` above: a refused save redisplays exactly what the operator
    typed, and reformatting that would be a second, silent edit on top of theirs.
    Unparsable or blank text is returned unchanged; reporting a syntax error is
    `validate_raw`'s job, not this one's.
    """
    if not raw or not raw.strip():
        return raw
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    return json.dumps(data, indent=2, ensure_ascii=False)


def _strip_apps_for_display(raw: str) -> str:
    """`messenger_brands` without its `apps` key — the settings screen shows the
    account map only; which application may send under which brand is set on that
    application's own page (SG-33.4). Applied to the stored value only: a refused
    save redisplays exactly what the operator submitted, which never carries `apps`
    in the first place because the field they typed into never showed it.
    """
    if not raw or not raw.strip():
        return raw
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if not isinstance(data, dict) or "apps" not in data:
        return raw
    return json.dumps({k: v for k, v in data.items() if k != "apps"}, ensure_ascii=False)


def _reinsert_messenger_apps(raw: str) -> tuple[str, str | None]:
    """Before validating a submitted `messenger_brands`, put its stored `apps` back.

    The field never shows `apps` (see `_strip_apps_for_display`), so an ordinary save
    carries none; this is what makes that save keep every application's binding
    exactly as it was. A submission that *does* carry `apps` — someone pasted a whole
    stored value back, `apps` included — is refused rather than accepted and possibly
    overwritten by another save a moment later: that binding lives on the application's
    own page now, and silently accepting a stale copy of it here would be surprising
    the next time an application's page is opened.

    Returns the text to validate and store, and an error message, or `None` when
    nothing needs the field refused (including when `raw` does not parse at all —
    `validate_raw` reports that, as always).
    """
    stored_apps: dict = {}
    stored_raw = store.get("messenger_brands") or ""
    if stored_raw.strip():
        try:
            stored_data = json.loads(stored_raw)
        except json.JSONDecodeError:
            stored_data = None
        if isinstance(stored_data, dict):
            apps = stored_data.get("apps")
            if isinstance(apps, dict):
                stored_apps = apps

    if raw.strip() == "":
        if not stored_apps:
            return raw, None
        return json.dumps({"brands": {}, "apps": stored_apps}, ensure_ascii=False), None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw, None                        # validate_raw reports the syntax error
    if not isinstance(data, dict):
        return raw, None                        # validate_raw reports the shape error
    if "apps" in data:
        return raw, (
            "'apps' is not edited here — which application may send under which brand "
            "is set on that application's own page (Apps)"
        )
    data = dict(data)
    data["apps"] = stored_apps
    return json.dumps(data, ensure_ascii=False), None


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
            if spec.type == "routes":
                value = _mask_bearers(current)
            elif spec.key == "messenger_brands":
                value = _format_json_for_display(_strip_apps_for_display(current))
            elif spec.key == "messenger_limits":
                value = _format_json_for_display(current)
            else:
                value = current
            configured = None
        field_layout = settings_layout.FIELD_BY_KEY[spec.key]
        rows_by_key[spec.key] = {
            "key": spec.key,
            "type": spec.type,
            "is_secret": spec.is_secret,
            "app_owned": field_layout.app_owned,
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


# The two examples the settings screen's "Insert example" button offers for
# `messenger_brands` and `messenger_limits` — the same shapes named in `Spec.description`
# for each, formatted the way the field itself is (see `_format_json_for_display`).
#
# Both examples name the same account, "@sokol_parking" (SG-33.3 review, 26.09.2026):
# `route_config.check_every_account_is_rate_bound` refuses a brand's account that has no
# matching key in the limit rule, and the two examples are meant to be pasted in together —
# an account name that did not match would fail that check the moment both landed.
_JSON_EXAMPLES: dict[str, str] = {
    "messenger_brands": json.dumps(
        {"brands": {"sokol": {"tg_user": {
            "account": "@sokol_parking", "number": "+79990000000",
            "intro": "Это Сокол Паркинг, вы запросили код",
        }}}},
        indent=2, ensure_ascii=False,
    ),
    "messenger_limits": json.dumps(
        {"accounts": {"@sokol_parking": {"per_hour": 5, "per_day": 20}},
         "recipient_window_seconds": 600},
        indent=2, ensure_ascii=False,
    ),
}


def _rung_choices(request: Request) -> list[dict]:
    """`settings_layout.RUNGS`, translated for the requesting locale — see settings.html's
    picker for `verification_route_order` and `operator_routes`. Translated here, not in
    the template, so the JSON blob the JS reads is built by `json.dumps` (correct escaping)
    rather than by hand-assembling a Jinja expression."""
    tr = get_translations(resolve_locale(request))
    return [{"code": code, "label": tr.gettext(label)} for code, label in settings_layout.RUNGS]


@router.get("/settings")
async def admin_settings(request: Request, _: str = Depends(admin_auth)):
    return render("settings.html", request, {
        "sections": _settings_view_rows(), "active": "settings", "errors": {},
        "saved": request.query_params.get("saved", ""),
        "countries": country_choices(resolve_locale(request)),
        "tg_account": settings_layout.tg_account_overview(),
        "rung_choices": _rung_choices(request), "bearer_sentinel": BEARER_SENTINEL,
        "json_examples": _JSON_EXAMPLES})


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
        elif spec.key == "messenger_brands":
            raw, apps_error = _reinsert_messenger_apps(raw)
            if apps_error:
                errors[spec.key] = apps_error
                continue                   # 'apps' submitted here: nothing to validate
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
            "tg_account": settings_layout.tg_account_overview(),
            "rung_choices": _rung_choices(request), "bearer_sentinel": BEARER_SENTINEL,
            "json_examples": _JSON_EXAMPLES})
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
