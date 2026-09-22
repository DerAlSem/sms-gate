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

4. **The digits are the vendor's, and they are checked.** Nothing in the reference
   promises the vendor can allocate a number ending in the four digits we asked for, and a
   verification matched against digits nobody dialled is indistinguishable, from the
   outside, from every subscriber suddenly typing the wrong code — while every instance of
   it is paid for. Both places the vendor states a code are read.

⚠️ **What this module does not do is learn an outcome that arrives after the bound.** A
`call_status` that resolves in the vendor's fortieth second is never read here; the rung
keeps its `unresolved` row and its `ucaller_id`, and the verification ends on its own
deadline unless somebody checks a code. Closing that costs a sweep over open `flash_call`
rungs, and it is named here rather than left to be discovered.
"""

from __future__ import annotations

import asyncio
import logging
import time

from app.db import queries
from app.verification import balance, ladder, ucaller
from app.verification.routes import FLASH_CALL

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
            return _mismatch(verification_id, vendor_ref, ours=code, theirs=placed.code)

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

        if _digits_changed(info.code, code):
            return _mismatch(verification_id, vendor_ref, ours=code, theirs=info.code,
                             cost=info.cost)

        if info.call_status == ucaller.PLACED:
            # The analogue of a message having been sent, and nothing more. The
            # verification is confirmed by a correct code at `/check` and by nothing the
            # vendor says: uCaller never learns whether the person read the digits.
            return ladder.Attempt(outcome=ladder.CARRIED, vendor_ref=vendor_ref,
                                  cost=info.cost)

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


def _mismatch(verification_id, vendor_ref, *, ours, theirs, cost=None) -> ladder.Attempt:
    """The vendor will dial digits the person cannot be matched against.

    Failed rather than adopted, which is the branch this change chose of the two the
    requirement allows: adopting would mean rewriting a live verification's code from a
    vendor's word, and the code is the one value in this gateway that is never written
    twice.

    The operator is woken because the alternative is invisible: from the outside this is
    indistinguishable from every subscriber suddenly typing the wrong code, and every
    instance of it has been paid for.
    """
    from app.alerting import notify

    logger.warning("verification %d: %s dialled digits other than the ones requested "
                   "(authorisation %s)", verification_id, VENDOR, vendor_ref)
    notify("routing",
           f"{VENDOR} allocated a call whose digits are not the ones this gateway asked "
           f"for (authorisation {vendor_ref}). The verification was failed rather than "
           f"matched against digits the vendor never dialled — the call was paid for, and "
           f"if this repeats the rung is spending money it cannot complete",
           dedup_extra=f"flash_call:code-mismatch")
    return ladder.Attempt(
        outcome=ladder.FAILED, vendor_ref=vendor_ref, cost=cost,
        reason="the vendor allocated different digits from the ones requested")


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
