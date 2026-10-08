"""The uCaller rung, as the ladder calls it.

The adapter below this knows the wire; this knows the money and the waiting. Four
orderings are the whole of it.

1. **An answer carrying a `ucaller_id` is an authorisation, whatever `status` said.** The
   id is recorded before anything else happens, because on a real number it is a charge
   that exists and because it is the only handle by which the call can be asked about
   afterwards. Measured 22.09.2026: the vendor allocates the id and answers
   `status: false` in the same breath, with our own code in the payload.

2. **The code goes out with the call, so it is read before anything is bought.** The
   opposite order of the Telegram rung, and for a plain reason: there the code rides on a
   second, free request after a billed check, and here it is the first request's argument.
   A verification that ended under us therefore costs nothing at all on this rung.

3. **The wait for an outcome is the ladder's bound, not the vendor's.** `call_status: -1`
   is "информация проверяется (от 1 сек до 1 минуты)" — longer than the ladder's whole
   patience, and a person is standing in front of a synchronous HTTP request for all of
   it. So the poll stops at the bound and the outcome is recorded as **unknown**: neither
   a placed call nor a failure, and the ladder stops rather than advancing, because the
   call has been placed and advancing would buy the same code at the other vendor.

4. **The vendor's `code` report is read and trusted with nothing.** Measured 08.10 over
   every flash_call rung to date: the `code` field — in `initCall`'s echo, in `getInfo`
   and in the vendor's own cabinet — is systematically not the digits that were dialled.
   All six rungs where it disagreed with the request were confirmed by this gateway's own
   `/check` 9–23 s after placement, and all eight where it agreed expired unconfirmed.
   A disagreement therefore decides nothing: while nothing else is known the outcome is
   recorded as unknown with the disagreement named, and once the vendor reports the call
   placed the rung is carried with the disagreement named; either way the ladder does not
   advance to buy the same code elsewhere, and the person confirms against the code this
   gateway asked for. Both places the vendor states a code are still read — as evidence,
   not as authority.

🟢 **The outcome that arrives after the bound is read by `resolve_outstanding` at the foot
of this module** (task 4.17e), from the one sweep that already sees every way a
verification can end. Until it existed, a subscriber the vendor could not reach watched the
verification expire instead of being told the call failed, and the call's `cost` was never
recorded against the rung that incurred it.
"""

from __future__ import annotations

import asyncio
import logging
import time

from app.db import queries
from app.settings_store import store
from app.verification import balance, ladder, ucaller
from app.verification.routes import FLASH_CALL
from app.verification.ucaller import configured_bearer

logger = logging.getLogger(__name__)

VENDOR = balance.VENDOR[FLASH_CALL]

# How long to leave between two `getInfo` calls while the vendor makes up its mind. The
# vendor's own floor for deciding is one second, so anything faster is spending requests
# against the per-IP rate limit to learn nothing.
POLL_INTERVAL = 1.0

# How the adapter's kinds map onto what the ladder does next. `ACCEPTED` is absent on
# purpose: it is the only one that goes on to spend and to wait, and it is handled in code
# rather than in a table so that it cannot be reached by a lookup that fell through.
_OUTCOME = {
    ucaller.DECLINED: ladder.DECLINED,
    ucaller.REFUSED: ladder.REFUSED,
    ucaller.UNCLASSIFIED: ladder.UNCLASSIFIED,
    ucaller.UNANSWERED: ladder.UNANSWERED,
}

# The two kinds nobody would otherwise find out about. A refusal of *us* is a credential,
# a balance or a cabinet switch and stops the rung working for everyone; an unplaceable
# refusal read as a decline would advance every verification to the other rung and tell
# nobody.
_LOUD = frozenset({ucaller.REFUSED, ucaller.UNCLASSIFIED})


def carrier(
    verification_id: int, *, app_id: str, bearer: str, client_label: str = "",
    poll_interval: float = POLL_INTERVAL,
):
    """A carrier the ladder can call for this verification.

    `bearer` is handed in rather than read from the settings here for the reason the
    Telegram rung's token is: a caller that forgets it builds a map without this rung in
    it, which is the failing direction, instead of a module silently reaching for global
    state.
    """
    async def carry(phone: str, *, seconds_left: float, rung_id: int) -> ladder.Attempt:
        deadline = time.monotonic() + max(0.0, seconds_left)

        row = await queries.get_verification(verification_id, app_id)
        code = row["code"] if row is not None else None
        if not code:
            # The verification ended before anything was placed. Nothing is bought, and
            # deliberately not a decline: a decline is a statement about the subscriber,
            # and a rung that appears to decline people for a reason of ours is a rung
            # taken out of the routing rule for the wrong reason.
            logger.info("verification %d ended before the call rung could place anything",
                        verification_id)
            return ladder.Attempt(
                outcome=ladder.INCAPABLE,
                reason="the verification ended before a call could be placed")
        try:
            ucaller.validate_code(code)
        except ValueError as e:
            # Unreachable while the door refuses to mint `0000`, and kept because the two
            # guards answer to different owners: the vendor's range is the vendor's, and
            # a rung that pays a round trip to be told its argument is wrong is a rung
            # that pays for our bug.
            logger.warning("verification %d holds a code this rung cannot dial (%s)",
                           verification_id, e)
            return ladder.Attempt(outcome=ladder.INCAPABLE, reason=str(e))

        call = await ucaller.init_call(
            phone, code=code, unique=ucaller.idempotency_key(rung_id), bearer=bearer,
            timeout=max(0.1, seconds_left), client_label=client_label)

        if call.kind in _LOUD:
            _alert(call)
        if call.kind != ucaller.ACCEPTED:
            return ladder.Attempt(
                outcome=_OUTCOME.get(call.kind, ladder.UNANSWERED), reason=call.error)

        placed = call.placed
        if placed is None or placed.ucaller_id is None:
            # An authorisation may exist that we can neither follow up nor attribute a
            # cost to. That is where an unexplained fall in the vendor's balance comes
            # from, and it needs a name to look for rather than a silent success.
            logger.warning("verification %d: uCaller accepted the call and named no "
                           "ucaller_id; the authorisation cannot be followed up",
                           verification_id)
            return ladder.Attempt(
                outcome=ladder.UNANSWERED,
                reason="the vendor accepted the call without naming an authorisation id")

        vendor_ref = str(placed.ucaller_id)
        # Recorded before the outcome is waited for, and that ordering is the money one: a
        # crash during the wait would otherwise leave a charge attributable to nothing.
        await queries.set_rung_outcome(
            rung_id, outcome=ladder.ATTEMPTING, vendor_ref=vendor_ref,
            reason="the authorisation was allocated and is billable")

        if _digits_changed(placed.code, code):
            # The echo has named other digits, and the report is not the dialled digits
            # (point 4 of this module's docstring), so it settles nothing — least of all
            # what became of the call, which nobody has said yet. Unknown, with the
            # disagreement named, and `resolve_outstanding` asks the vendor later.
            _report_disagrees(verification_id, vendor_ref, theirs=placed.code)
            return ladder.Attempt(
                outcome=ladder.UNRESOLVED, vendor_ref=vendor_ref,
                reason=f"the vendor's echo named code {placed.code} against the one "
                       f"requested; the report is not the dialled digits, so nothing is "
                       f"known about the call yet")

        info = await _await_outcome(placed.ucaller_id, bearer=bearer, deadline=deadline,
                                    poll_interval=poll_interval)
        if info is None:
            return ladder.Attempt(
                outcome=ladder.UNRESOLVED, vendor_ref=vendor_ref,
                reason="the vendor had not said what became of the call within the "
                       "ladder's bound")

        # The one place this gateway ever learns uCaller's balance, and the subtraction is
        # the reference's: `getInfo`'s `balance` is the balance *before* this operation is
        # charged, so a floor held against it as it stands fires one verification late.
        balance.observe(FLASH_CALL, info.balance_after)

        disagrees = _digits_changed(info.code, code)
        if disagrees:
            # Journal only, and the digits are named: the report is the evidence the
            # claim against the vendor rests on, and a disagreement line without the
            # digits reported proves nothing after the journal has rotated.
            _report_disagrees(verification_id, vendor_ref, theirs=info.code)

        if info.call_status == ucaller.PLACED:
            # The analogue of a message having been sent, and nothing more. The
            # verification is confirmed by a correct code at `/check` and by nothing the
            # vendor says: uCaller never learns whether the person read the digits.
            # A disagreeing report names itself in the reason and settles nothing else:
            # the vendor has said what became of the call, and recording that now saves
            # the sweep a second question to a vendor that rate-limits per IP.
            reason = ""
            if disagrees:
                reason = (f"the vendor reported the call placed and named code "
                          f"{info.code} against the one requested; the report is not "
                          f"the dialled digits, so the disagreement settles nothing")
            return ladder.Attempt(outcome=ladder.CARRIED, vendor_ref=vendor_ref,
                                  cost=info.cost, reason=reason)

        return ladder.Attempt(
            outcome=ladder.FAILED, vendor_ref=vendor_ref, cost=info.cost,
            reason="the vendor could not connect the call to this subscriber")

    return carry


async def _await_outcome(uid, *, bearer, deadline, poll_interval):
    """Poll until the vendor has decided, or until the ladder's bound runs out.

    Asked at least once however little of the bound is left: an authorisation has been
    placed and paid for, and not asking at all would record "unknown" about a call whose
    outcome may already be sitting there.
    """
    while True:
        fetched = await ucaller.get_info(
            uid, bearer=bearer,
            timeout=max(0.1, deadline - time.monotonic()))
        if ucaller.resolved(fetched.info):
            return fetched.info
        # A refused or unreadable `getInfo` is not an outcome and is not fatal either: the
        # call is placed, and the next tick of the poll may answer. What bounds it is the
        # deadline, the same one that bounds a vendor still thinking.
        if time.monotonic() + poll_interval >= deadline:
            return None
        await asyncio.sleep(poll_interval)


def _digits_changed(theirs: str | None, ours: str) -> bool:
    """Whether the vendor named digits other than the ones asked for.

    A vendor that said nothing has not changed anything: `code` is absent from some
    answers, and reading an absence as a mismatch would fail paid calls for a field the
    vendor merely omitted.
    """
    return bool(theirs) and theirs != ours


def _report_disagrees(verification_id, vendor_ref, *, theirs) -> None:
    """The journal line for a code report that disagrees with the request.

    A line rather than an alert — measured 08.10 this fires on deliverable calls, and an
    operator woken by every one of them buries the refusals that do need one. The digits
    the vendor named are in the line because the report is the evidence the claim against
    the vendor (SG-39) rests on, and they are not this gateway's secret: a report that
    agreed would never reach this line.
    """
    logger.warning("verification %d: %s reported code %s against the one requested for "
                   "authorisation %s; the report is not the dialled digits, so it "
                   "settles nothing", verification_id, VENDOR, theirs, vendor_ref)


def _alert(call) -> None:
    from app.alerting import notify

    if call.kind == ucaller.REFUSED:
        text = (f"{VENDOR} refused this gateway rather than the subscriber "
                f"({call.error or 'no reason given'}, code {call.error_code}) — the rung "
                f"is not working for anyone until it is fixed, and the ladder is spending "
                f"on the rung beside it")
    else:
        text = (f"{VENDOR} refused with an error this gateway cannot place "
                f"({call.error or 'no reason given'}, code {call.error_code}); the ladder "
                f"advanced as it would past a decline")
    notify("routing", text, dedup_extra=f"flash_call:{call.error_code}")


# --- the outcome that arrives after the ladder has stopped waiting (task 4.17e) ----------

async def resolve_outstanding() -> int:
    """Ask the vendor what became of every call it had not decided in time.

    🔴 **This is not a tidy-up, it is the other half of the rung.** The ladder waits ten
    seconds because a person is standing in front of a synchronous request; the vendor
    takes up to a minute to set `call_status`. Without this pass a subscriber the vendor
    could not reach watches the verification expire instead of being told the call failed,
    and the call's `cost` is never recorded against the rung that incurred it — which is
    the number the weekly spend is reconciled with.

    Run from `announce_verification_outcomes`, which is the one pass that already sees
    every way a verification can end and already asks a vendor. Here rather than in its own
    loop for that reason: an ending learned in a pass of its own is an ending somebody has
    to remember to announce.

    Returns how many rungs it settled, which is what the caller logs. Never raises: a
    vendor's mood must not be able to stop the sweep that announces every other ending.
    """
    bearer = configured_bearer()
    if not bearer:
        return 0

    settled = 0
    for row in await queries.unresolved_rungs(
            FLASH_CALL, within_seconds=store.verification_ttl_seconds):
        try:
            settled += await _settle(row, bearer=bearer)
        except Exception:
            logger.exception("verification %s: settling the call rung %s raised",
                             row["verification_id"], row["vendor_ref"])
    return settled


async def _settle(row, *, bearer: str) -> int:
    try:
        uid = int(row["vendor_ref"])
    except (TypeError, ValueError):
        logger.warning("verification %s holds a call rung whose reference is not a "
                       "uCaller id (%r)", row["verification_id"], row["vendor_ref"])
        return 0

    fetched = await ucaller.get_info(uid, bearer=bearer)
    info = fetched.info
    if not ucaller.resolved(info):
        # Still thinking, or the vendor would not say. Left alone rather than given a
        # reading: the give-up is the age of the rung and it lives in the query, so a rung
        # that never resolves stops being chased without ever being told a story.
        return 0

    # The one place this gateway learns uCaller's balance outside a live ladder, and the
    # same subtraction: `balance` is the balance before this operation is charged.
    balance.observe(FLASH_CALL, info.balance_after)

    still_open = row["status"] == "pending"
    code = row["code"]

    if row["status"] == "confirmed":
        # A confirmation at `/check` is this gateway's own evidence: the person typed the
        # code this gateway asked for, so the call was placed and heard. Whatever the
        # vendor reports now cannot outrank it — and on a confirmed verification the code
        # is already spent, so reading its absence as a disagreement would let a late
        # report fail a rung minutes after the fact proved it carried (v118, 08.10).
        # What the report *did* say is kept: a vendor reporting a call unconnected while
        # its own digits were confirmed is evidence for the claim against it.
        said = ("the vendor later reported the call was not connected"
                if info.call_status != ucaller.PLACED else
                "the vendor later reported the call placed")
        await queries.set_rung_outcome(
            row["rung_id"], outcome=ladder.CARRIED, cost=info.cost,
            reason=f"the verification was confirmed by this gateway's own code check; "
                   f"{said}, and the report cannot outrank it")
        if info.call_status != ucaller.PLACED:
            logger.warning("verification %s: confirmed by this gateway's own code, yet "
                           "the vendor reports authorisation %s was not connected — kept "
                           "as evidence against the vendor",
                           row["verification_id"], uid)
        else:
            logger.info("verification %s: the call rung %s settled as carried by a "
                        "confirmation of ours", row["verification_id"], uid)
        return 1

    if info.call_status == ucaller.PLACED:
        # The call was placed, whatever its `code` report says: the report is not the
        # dialled digits (measured 08.10, 6/6 such rungs confirmed by this gateway's own
        # code), so a disagreement is named in the reason and settles nothing. The
        # comparison is made only while the verification still holds its code — every
        # ending spends it, and a spent code read as a disagreement would cry wolf on
        # the ordinary expired rung. The verification is deliberately left open: the
        # person may be reading the digits off their screen this minute, and the window,
        # not this sweep, ends it.
        reason = "the vendor reported the call placed after the ladder stopped waiting"
        if code and _digits_changed(info.code, code):
            _report_disagrees(row["verification_id"], str(uid), theirs=info.code)
            reason = (f"the vendor reported the call placed and named code {info.code} "
                      f"against the one requested; the report is not the dialled digits, "
                      f"so the disagreement settles nothing")
        await queries.set_rung_outcome(
            row["rung_id"], outcome=ladder.CARRIED, cost=info.cost, reason=reason)
        logger.info("verification %s: the call rung %s resolved as placed",
                    row["verification_id"], uid)
        return 1

    reason = "the vendor could not connect the call to this subscriber"
    await queries.set_rung_outcome(row["rung_id"], outcome=ladder.FAILED, cost=info.cost,
                                   reason=reason)
    if still_open:
        # The ending the person was owed and did not get. An expired verification would
        # have reported the one thing that did not happen: the window did not run out,
        # the call did not arrive.
        await queries.fail_verification(row["verification_id"], reason=reason)
    return 1
