"""What the routing rule costs, counted per operator and per application, and said aloud.

The rule exists because an operator withdrew the modem route. The rule set during that
outage will outlive it: when МегаФон starts accepting traffic again, the entry is still
there, the applications that do not send codes are still refused, and nothing on any
screen says so. A count is the difference between a rule that is reviewed and a rule that
is forgotten — and the second instrument, for the same reason, is an alert once an entry
has been in force longer than the review period.

Four norms, each of which decides an implementation that would otherwise look fine:

**The count is in the database.** The rule is reviewed on a scale of months and this
gateway is deployed on a scale of days; a counter in the process answers zero to
everybody who ever asks.

**Operators are grouped on the folded name, in Python.** `number_operators` holds
МегаФон under two spellings, and the shipped SQLite's `upper()` and `LIKE` are ASCII-only
— a measurement taken with `upper()` on 08.09.2026 undercounted this operator's traffic
by half. A count split between two spellings makes a rule look half as expensive as it
is, which is the one direction that matters here.

**The alert does not hang on `notify_send_errors`.** That toggle is off on a stock
install, and every install that has this defect is a stock install. A refusal for want of
a route is not a send failing; it is carried by `notify_routing_errors`, which ships on.

**The alert is deduplicated on the operator and the route, never on the item.** At about
seventy refusals a month and rising, one alert per refused message teaches an operator to
ignore the channel that also carries "the vendor is out of credit". Deduplicating on the
operator alone would be the opposite mistake: one refusing operator would silence the
alert about the next one.

What this cannot do is say that the outage has ended. Once a rule is in force, the modem
route to that operator receives no attempts at all, so the count can only ever grow — the
one source of proof that the refusal has ended is the thing the rule switches off. That
is why the second instrument exists.
"""

from __future__ import annotations

import json
import logging

from app.db.connection import get_db
from app.verification import rule

logger = logging.getLogger(__name__)


async def record(*, operator: str | None, app_id: str, route: str) -> None:
    """Count one item refused for want of a route that could carry it, and say so.

    `operator` is `None` when the lookup could not resolve one; it is counted under the
    rule's own spelling for that case, because an unresolved operator is a case the owner
    configures rather than one that disappears into a total.
    """
    name = (operator or "").strip() or rule.UNKNOWN
    key = rule.fold(name)

    db = await get_db()
    await db.execute(
        "INSERT INTO route_refusals (operator_key, operator, app_id, route) "
        "VALUES (?, ?, ?, ?)",
        (key, name, app_id, route),
    )
    await db.commit()

    from app.alerting import notify
    logger.info("refused for want of a route: operator=%s app=%s route=%s",
                name, app_id, route)
    notify("routing",
           f"{app_id} was refused for {name}: the route the rule names for this "
           f"operator ({route}) cannot carry it. The rule is still in force — this is "
           f"what it costs",
           dedup_extra=f"refused:{key}:{route}")


async def counts(*, since: str | None = None, period: str | None = None) -> list[dict]:
    """What the rule has refused, per operator, with its applications and routes.

    `since` bounds it to refusals recorded at or after that timestamp, and `period` to
    one of the console's rolling windows. Without either, the answer is every refusal
    recorded — the honest default for a question asked about a rule rather than a day.
    """
    db = await get_db()
    sql = ("SELECT operator_key, operator, app_id, route, COUNT(*) AS n, "
           "       MAX(refused_at) AS last_at "
           "  FROM route_refusals ")
    params: tuple = ()
    if since is not None:
        sql += " WHERE refused_at >= ? "
        params = (since,)
    elif period is not None:
        from app import periods
        modifier = periods.bound(period)
        if modifier is not None:
            sql += " WHERE refused_at >= datetime('now', ?) "
            params = (modifier,)
    sql += " GROUP BY operator_key, operator, app_id, route"

    grouped: dict[str, dict] = {}
    async with db.execute(sql, params) as cur:
        async for row in cur:
            entry = grouped.setdefault(row["operator_key"], {
                "operator_key": row["operator_key"],
                # The spelling shown is whichever the rows carry; they are the same
                # operator by definition of the key, and picking one is a display choice
                # rather than an answer.
                "operator": row["operator"],
                "total": 0, "by_app": {}, "by_route": {}, "last_at": None,
            })
            n = int(row["n"])
            entry["total"] += n
            entry["by_app"][row["app_id"]] = entry["by_app"].get(row["app_id"], 0) + n
            entry["by_route"][row["route"]] = entry["by_route"].get(row["route"], 0) + n
            if entry["last_at"] is None or str(row["last_at"]) > str(entry["last_at"]):
                entry["last_at"] = row["last_at"]
    return sorted(grouped.values(), key=lambda e: (-e["total"], e["operator"]))


async def rule_entries() -> list[dict]:
    """Each entry of the rule in force, with how long it has been in force."""
    db = await get_db()
    rows = []
    async with db.execute(
        "SELECT operator_key, operator, routes, in_force_since, reviewed_at, "
        "       CAST(julianday('now') - julianday(in_force_since) AS INTEGER) AS days "
        "  FROM route_rule_entries ORDER BY in_force_since"
    ) as cur:
        async for row in cur:
            rows.append(dict(row))
    return rows


async def review_step() -> None:
    """One pass: reconcile what is in force, then report what has outlived its review.

    Split out of its loop so a test can drive it, in the manner of `verification_step`.
    Reconciling here rather than in a settings hook is deliberate — see the table's own
    comment in `app/db/migrate.py`.
    """
    await _reconcile()
    await _report_stale()


async def _reconcile() -> None:
    """Bring `route_rule_entries` level with the rule in force.

    An entry whose routes changed starts its review period again: the decision was
    revisited, which is exactly what the period measures. An entry that left the rule is
    forgotten — a rule that no longer names an operator is not a rule anybody needs
    reminding about.
    """
    try:
        in_force = rule.parse(_raw_rule())
    except rule.UnreadableRule:
        # The rule being unreadable already alerts where it is read. Reconciling against
        # an unreadable rule would delete every entry and start every period again, which
        # would hide a stale rule behind a broken one.
        logger.warning("routing rule unreadable; the review record is left as it is")
        return

    db = await get_db()
    stored: dict[str, str] = {}
    async with db.execute(
            "SELECT operator_key, routes FROM route_rule_entries") as cur:
        async for row in cur:
            stored[row["operator_key"]] = row["routes"]

    for key, routes in in_force.items():
        as_stored = json.dumps(routes, ensure_ascii=False)
        if key not in stored:
            await db.execute(
                "INSERT INTO route_rule_entries (operator_key, operator, routes) "
                "VALUES (?, ?, ?)",
                (key, _spelling(key, in_force), as_stored))
        elif stored[key] != as_stored:
            await db.execute(
                "UPDATE route_rule_entries "
                "   SET routes = ?, operator = ?, "
                "       in_force_since = CURRENT_TIMESTAMP, reviewed_at = NULL "
                " WHERE operator_key = ?",
                (as_stored, _spelling(key, in_force), key))
    for key in stored:
        if key not in in_force:
            await db.execute(
                "DELETE FROM route_rule_entries WHERE operator_key = ?", (key,))
    await db.commit()


async def _report_stale() -> None:
    """Alert on each entry in force longer than the review period, once per period.

    `*` and `?` are left out, and this is the one policy decision here. They name no
    operator — they are the gateway's baseline, answering for an operator with no entry
    and for one that could not be resolved — so a rule holding only them is a rule that
    diverts nothing, and reporting it every month would teach an operator to ignore the
    channel that also carries the entries that do divert. Set to `refuse`, either one is
    audible anyway: every item it refuses is counted and alerted by `record` above.
    """
    from app.settings_store import store

    days = store.operator_route_review_days
    db = await get_db()
    stale = []
    async with db.execute(
        "SELECT operator_key, operator, routes, in_force_since, "
        "       CAST(julianday('now') - julianday(in_force_since) AS INTEGER) AS days "
        "  FROM route_rule_entries "
        " WHERE operator_key NOT IN (?, ?) "
        "   AND julianday('now') - julianday(in_force_since) >= ? "
        "   AND (reviewed_at IS NULL "
        "        OR julianday('now') - julianday(reviewed_at) >= ?)",
        (rule.DEFAULT, rule.UNKNOWN, days, days),
    ) as cur:
        async for row in cur:
            stale.append(dict(row))

    if not stale:
        return

    from app.alerting import notify
    for entry in stale:
        cost = await counts(since=entry["in_force_since"])
        mine = next((c for c in cost if c["operator_key"] == entry["operator_key"]), None)
        if mine is None:
            what_it_cost = ("nothing has been refused for this operator since it came "
                            "into force")
        else:
            by_app = ", ".join(f"{app} {n}" for app, n in
                               sorted(mine["by_app"].items(), key=lambda kv: -kv[1]))
            what_it_cost = f"{mine['total']} items refused since then ({by_app})"
        notify("routing",
               f"the routing rule's entry for {entry['operator']} has been in force "
               f"{entry['days']} days and has not been revisited: it routes to "
               f"{entry['routes']}, and {what_it_cost}. If the operator is accepting "
               f"traffic again, nothing here can tell you so — the route the rule "
               f"replaced receives no attempts at all",
               dedup_extra=f"unreviewed:{entry['operator_key']}")
        await db.execute(
            "UPDATE route_rule_entries SET reviewed_at = CURRENT_TIMESTAMP "
            " WHERE operator_key = ?", (entry["operator_key"],))
    await db.commit()


def _raw_rule() -> str:
    from app.settings_store import store
    return store.get(rule.KEY)


def _spelling(key: str, in_force: dict[str, list[str]]) -> str:
    """The operator as the rule writes it, recovered from the folded key.

    `rule.parse` keys on the folded name and drops the written one, so the written one is
    found by folding each entry again rather than by trusting the key to be readable: the
    key of `МегаФон` is lower-case and would be shown to an operator as something they
    did not type.
    """
    try:
        data = json.loads(_raw_rule() or "[]")
    except json.JSONDecodeError:
        return key
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                written = str(item.get("operator", "")).strip()
                if written and rule.fold(written) == key:
                    return written
    return key


async def review_loop() -> None:
    """Reconcile what is in force and report what has outlived its review, hourly.

    Hourly rather than by the minute because the thing it watches moves on a scale of
    days, and rather than daily because the reconciliation half is also what dates a rule
    change — a rule rewritten and rewritten again inside one tick would otherwise look
    like one change, and its review period would start from the wrong end.

    Not essential: a gateway whose review loop has died still sends, still receives and
    still reaches every terminal status. What it loses is the ability to notice that a
    rule has been forgotten, which is a slow failure and not a stopped service.
    """
    import asyncio

    logger.info("Routing-rule review loop started")
    while True:
        try:
            await review_step()
        except Exception:
            logger.exception("Routing-rule review failed")
        await asyncio.sleep(3600)
