"""Task 3.4 — the durable, atomic claim that consumes a sender account's allowance.

The claim is taken **before** the vendor is touched and is never deleted afterwards: a
row here means "we addressed this account's rate budget for this send", and that is the
quantity the per-account bound exists to hold down. Deleting it on a miss would hand the
account an unbounded number of lookups inside the hour, which is the other half of what
gets an account limited.

What a miss *does* change is the person's side of the bound: nobody received anything, so
the claim is settled `may_have_reached = 0` and stops blocking another brand's account
from reaching that number inside the recipient window.
"""

import asyncio

from app.db import queries
from app.db.connection import close_db, get_db, init_db
from app.db.migrate import run_migrations

TG = "tg_user"
MAX = "max_user"
PHONE = "+79851600019"


def _with_db(coro):
    async def run():
        await init_db(":memory:")
        await run_migrations()
        return await coro()
    try:
        return asyncio.run(run())
    finally:
        asyncio.run(close_db())


async def _claim(message_id, *, account="sokol_tg", route=TG, phone=PHONE,
                 per_hour=2, per_day=5, window=600) -> bool:
    return await queries.claim_rate_allowance(
        message_id=message_id, route=route, account=account, phone=phone,
        per_hour=per_hour, per_day=per_day, recipient_window_seconds=window,
    )


async def _age(message_id: int, seconds: int) -> None:
    """Age a claim, so the rolling windows can be exercised without sleeping."""
    db = await get_db()
    await db.execute(
        "UPDATE messenger_rate_claims "
        "SET claimed_at = datetime(claimed_at, ? || ' seconds') WHERE message_id = ?",
        (f"-{seconds}", message_id),
    )
    await db.commit()


def test_an_account_under_its_hourly_bound_is_granted_the_claim():
    assert _with_db(lambda: _claim(1)) is True


def test_the_hourly_maximum_refuses_the_next_send():
    async def body():
        return [await _claim(i, per_hour=2, per_day=5) for i in (1, 2, 3)]

    assert _with_db(body) == [True, True, False]


def test_a_claim_older_than_the_hour_no_longer_counts():
    async def body():
        first = await _claim(1, per_hour=1)
        await _age(1, 3601)
        return first, await _claim(2, per_hour=1)

    assert _with_db(body) == (True, True)


def test_the_daily_maximum_refuses_even_when_the_hour_is_clear():
    """The two windows are separate bounds, and the day is the one that survives a lull."""
    async def body():
        granted = []
        for i in (1, 2):
            granted.append(await _claim(i, per_hour=1, per_day=2))
            await _age(i, 3601)          # out of the hour, still inside the day
        granted.append(await _claim(3, per_hour=1, per_day=2))
        return granted

    assert _with_db(body) == [True, True, False]


def test_two_sends_racing_on_the_last_slot_grant_exactly_one():
    """The spec scenario, and the reason the count and the insert are one statement.

    A count read in one await and an insert written in the next hands the last slot to
    both: the second coroutine reads the allowance the first has not yet consumed.
    """
    async def body():
        return await asyncio.gather(
            _claim(1, per_hour=1, phone="+79851600019"),
            _claim(2, per_hour=1, phone="+79035011303"),
        )

    assert sorted(_with_db(body)) == [False, True]


def test_a_claim_cannot_be_granted_twice_for_the_same_send():
    async def body():
        return await _claim(1), await _claim(1)

    assert _with_db(body) == (True, False)


def test_one_person_is_not_addressed_by_a_second_account_inside_the_window():
    async def body():
        first = await _claim(1, account="sokol_tg", route=TG)
        second = await _claim(2, account="gmplus_max", route=MAX)
        return first, second

    assert _with_db(body) == (True, False)


def test_the_recipient_window_rolls():
    async def body():
        await _claim(1, account="sokol_tg", window=600)
        await _age(1, 601)
        return await _claim(2, account="gmplus_max", window=600)

    assert _with_db(body) is True


def test_a_claim_that_reached_nobody_stops_blocking_the_other_account():
    """A miss is not a message received, and the window guards receiving.

    Without this a number nobody in Telegram answers for would cost the person their MAX
    route as well, for the length of the window, having been sent nothing at all.
    """
    async def body():
        await _claim(1, account="sokol_tg", route=TG)
        await queries.settle_rate_claim(message_id=1, route=TG, may_have_reached=False)
        return await _claim(2, account="gmplus_max", route=MAX)

    assert _with_db(body) is True


def test_a_settled_claim_still_counts_against_the_account():
    """Settling says what the person received. The account's budget was spent either way —
    the vendor was asked, and an unbounded number of asks is what limits an account."""
    async def body():
        await _claim(1, per_hour=1)
        await queries.settle_rate_claim(message_id=1, route=TG, may_have_reached=False)
        return await _claim(2, per_hour=1, phone="+79035011303")

    assert _with_db(body) is False


def test_an_unsettled_claim_blocks_the_other_account():
    """The default is the conservative one: a send whose outcome we never learned may have
    arrived, and a process that died between the claim and the answer leaves exactly that."""
    async def body():
        await _claim(1, account="sokol_tg", route=TG)
        return await _claim(2, account="gmplus_max", route=MAX)

    assert _with_db(body) is False


def test_a_window_of_zero_seconds_puts_no_bound_on_the_recipient():
    async def body():
        await _claim(1, account="sokol_tg", route=TG, window=0)
        return await _claim(2, account="gmplus_max", route=MAX, window=0)

    assert _with_db(body) is True


def test_the_same_account_is_not_blocked_by_its_own_earlier_claim():
    """The window is about a person hearing from two strangers at once. One account
    writing twice is one conversation, and the account's own bound already holds it."""
    async def body():
        await _claim(1, account="sokol_tg", route=TG)
        return await _claim(2, account="sokol_tg", route=TG)

    assert _with_db(body) is True


def test_settling_a_claim_that_was_never_granted_is_not_an_error():
    """The ladder settles what it claimed; a route that refused the claim has nothing to
    settle, and an exception on that path would fail a message over bookkeeping."""
    async def body():
        await queries.settle_rate_claim(message_id=99, route=TG, may_have_reached=True)
        return True

    assert _with_db(body) is True
