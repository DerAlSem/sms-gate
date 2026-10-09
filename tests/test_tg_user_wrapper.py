# tests/test_tg_user_wrapper.py
"""Task 3.2 — kurigram behind the route interface, and the three things the live capture
of 3.1 said the wrapper owes.

The capture (`openspec/changes/reach-people-in-messengers/captures/kurigram-2.2.26.json`)
bought three facts that no amount of reading the documentation would have given, and each
one is a test here rather than a comment:

1. **A severed transport gives up after 160 s** — `MAX_RETRIES(10) × (WAIT_TIMEOUT(15) +
   RETRY_DELAY(1))`, measured at `seconds_to_answer = 160.03`. The rung's deadline is 8 s,
   so the library's own answer arrives twenty times too late to be of any use. The wrapper
   therefore hands the library a retry budget that ends inside our window, and cancels the
   call outright when it does not.
2. **`sleep_threshold=0`** — `Session.invoke` swallows a `FloodWait` at or below the
   threshold (10 s by default), sleeps and retries, and our code never sees it. At the
   default the whole rung is spent inside the library reporting nothing.
3. **A miss is not "this person has no Telegram"** — `PhoneNotOccupied` arrives
   identically for a number with no account and for a number hidden from lookup. Nothing
   here pretends to tell them apart.

The vendor library is imported for real. The *client* is a fake, because a real one needs
an account and a phone that rings; the *queries* it is handed are built by the real TL
constructors of layer 229, so a version that renames a field fails these tests rather than
failing a send.
"""
from __future__ import annotations

import asyncio
import inspect

import pytest
from pyrogram import raw

from app.routing import tg_user as tg
from app.routing.route import Attempt, Outcome, Route
from app.routing.routes import TG_USER

ACCOUNT = "8788987307"
PHONE = "+79851600019"
TEXT = "SokolParking: 1234"


# --------------------------------------------------------------------------- the fake


class FakeUser:
    def __init__(self, user_id=368905113, access_hash=4242, username=None):
        self.id = user_id
        self.access_hash = access_hash
        self.username = username


def the_account() -> FakeUser:
    """Who the session file is signed in as. Not the recipient — the wrapper refuses to
    send when the two are confused, which is task 2.5 checked at the wire."""
    return FakeUser(user_id=int(ACCOUNT), username="gmplus_support")


class FakeResolved:
    def __init__(self, users):
        self.users = users
        self.peer = object()


class VendorError(Exception):
    """Stands in for any error the library may raise. Its identity must not escape."""


class FakeClient:
    """The small surface `TelegramUserRoute` is allowed to touch, and nothing else.

    Every call is recorded, so a test can assert what the wrapper asked the vendor rather
    than only what it concluded.
    """

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.invocations: list[tuple[object, dict]] = []
        self.connected = False
        self.disconnected = False
        self.signed_in = True
        self.me = the_account()
        #: (query type name) -> exception to raise, or a callable
        self.raises: dict[str, BaseException] = {}
        #: query type names that should hang until cancelled
        self.hangs: set[str] = set()
        self.cancelled: list[str] = []

    async def connect(self):
        self.connected = True
        return self.signed_in

    async def disconnect(self):
        self.disconnected = True

    async def get_me(self):
        return self.me

    async def invoke(self, query, **kwargs):
        name = type(query).__name__
        self.invocations.append((query, kwargs))
        if name in self.hangs:
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                self.cancelled.append(name)
                # A library that blocks while being cancelled must not hold the rung.
                # This one takes its time on purpose; the wrapper is not allowed to wait.
                await asyncio.sleep(3600)
            raise AssertionError("unreachable")
        failure = self.raises.get(name)
        if failure is not None:
            raise failure
        if name == "ResolvePhone":
            return FakeResolved([FakeUser()])
        return object()          # an `Updates` the wrapper does not look inside

    def invoked(self) -> list[str]:
        return [type(q).__name__ for q, _ in self.invocations]


def make_route(tmp_path, *, factory=None, clients=None, margin=None):
    """A route whose session file exists and whose client is ours.

    The session file is created because the wrapper refuses a path that does not exist —
    `SQLiteStorage` would otherwise mint a fresh unauthorised session beside a typo and
    then report "not signed in", which is a lie about the file the operator believes in.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / f"{ACCOUNT}.session").write_bytes(b"")
    made: list[FakeClient] = clients if clients is not None else []

    def default_factory(**kwargs):
        client = FakeClient(**kwargs)
        made.append(client)
        return client

    route = tg.TelegramUserRoute(
        api_id=12345,
        api_hash="deadbeef",
        session_dir=str(tmp_path),
        client_factory=factory or default_factory,
        **({"margin_seconds": margin} if margin is not None else {}),
    )
    return route, made


async def offer(route, **over):
    kwargs = dict(message_id=7, phone=PHONE, text=TEXT, message_class="code_long",
                  brand="gmplus", account=ACCOUNT)
    kwargs.update(over)
    return await route.offer(**kwargs)


# ------------------------------------------------------------------ the interface itself


def test_the_wrapper_is_a_route(tmp_path):
    route, _ = make_route(tmp_path)
    assert isinstance(route, Route)
    assert route.name == TG_USER


def test_the_route_does_not_restate_the_class_policy(tmp_path):
    """Which classes go to Telegram is `route_order`, and it is said once.

    A second statement here would be the weaker of the two — the ladder never asks a
    route it was not configured to offer — and two statements of one invariant mean
    nobody can tell which is load-bearing.
    """
    route, _ = make_route(tmp_path)
    assert route.carries("code_long")
    assert route.carries("free_text")
    assert route.carries("code4")


# ------------------------------------------------------------------------ the happy path


def test_a_resolved_number_is_sent_to_and_accepted(tmp_path):
    route, made = make_route(tmp_path)
    attempt = asyncio.run(offer(route))

    assert attempt.outcome is Outcome.ACCEPTED
    assert made[0].invoked() == ["ResolvePhone", "SendMessage"]

    resolve, _ = made[0].invocations[0]
    assert resolve.phone == PHONE

    send, _ = made[0].invocations[1]
    assert send.message == TEXT
    assert isinstance(send.peer, raw.types.InputPeerUser)
    assert send.peer.user_id == 368905113
    assert send.peer.access_hash == 4242


def test_no_contact_is_ever_imported(tmp_path):
    """The undo of task 3.2 is discharged by never creating the thing.

    `messenger-delivery` allows a contact only "where resolution is impossible without
    it", and the capture showed `ResolvePhone` resolves without one — while
    `ImportContacts` answers an absent number and a hidden one with the same empty
    `users`, so it buys nothing and leaves an entry on the account to be removed.
    """
    route, made = make_route(tmp_path)
    asyncio.run(offer(route))
    assert "ImportContacts" not in made[0].invoked()
    assert "DeleteContacts" not in made[0].invoked()


def test_the_same_message_cannot_be_delivered_twice_by_the_same_account(tmp_path):
    """`random_id` is derived from the message and the account, not drawn at random.

    Telegram deduplicates on it. Nothing in this gateway resends a message a messenger
    rung may already have carried — that is what `indeterminate` is for — but a door that
    costs five lines to close is closed.
    """
    route, made = make_route(tmp_path)
    asyncio.run(offer(route))
    asyncio.run(offer(route))

    first = [q for q in (q for q, _ in made[0].invocations)
             if type(q).__name__ == "SendMessage"]
    assert len(first) == 2
    assert first[0].random_id == first[1].random_id

    asyncio.run(offer(route, message_id=8))
    another = [q for q, _ in made[0].invocations
               if type(q).__name__ == "SendMessage"][2]
    assert another.random_id != first[0].random_id


# --------------------------------------------------------- the three facts the capture bought


def test_every_flood_wait_reaches_us(tmp_path):
    """`sleep_threshold=0`, or the rung is spent inside the library saying nothing."""
    route, made = make_route(tmp_path)
    asyncio.run(offer(route))
    assert made[0].kwargs["sleep_threshold"] == 0


def test_the_vendor_is_given_a_budget_that_ends_inside_the_rungs_deadline(tmp_path):
    """The library's own give-up is 160 s. Ours has to be shorter than 8 s to exist."""
    route, made = make_route(tmp_path)
    asyncio.run(offer(route))

    for _, kwargs in made[0].invocations:
        assert kwargs["retries"] == 1, "a retry the ladder cannot see is a retry we cannot afford"
        assert 0 < kwargs["timeout"] < tg.DEFAULT_DEADLINE_SECONDS
        assert kwargs["retry_delay"] == 0


def test_a_call_that_does_not_answer_is_cancelled_and_not_waited_for(tmp_path):
    """The one that a plain `await asyncio.wait_for(...)` fails.

    `wait_for` cancels the call and then *awaits* the cancellation. A library that takes
    its time dying therefore holds the rung past its own deadline, and past the ladder's.
    The wrapper cancels explicitly and walks away; the task is logged, not waited on.
    """
    route, made = make_route(tmp_path, margin=7.6)      # budget 0.4s of an 8s deadline

    async def run():
        client_box: list[FakeClient] = []

        def factory(**kwargs):
            client = FakeClient(**kwargs)
            client.hangs.add("ResolvePhone")
            client_box.append(client)
            return client

        route._factory = factory
        started = asyncio.get_running_loop().time()
        # Bounded from out here too, so a regression fails in seconds instead of hanging
        # the run for the hour the fake sleeps. The hang IS the defect; it just must not
        # be reported by a stopped clock.
        try:
            attempt = await asyncio.wait_for(offer(route), 5)
        except TimeoutError:
            pytest.fail("the wrapper never returned — it waited on a cancelled call")
        return attempt, asyncio.get_running_loop().time() - started, client_box[0]

    attempt, elapsed, client = asyncio.run(run())

    assert elapsed < 3, f"the wrapper waited {elapsed:.1f}s on a call it had cancelled"
    assert client.cancelled == ["ResolvePhone"], "the vendor call was never cancelled"
    assert attempt.outcome is Outcome.UNAVAILABLE


def test_a_miss_does_not_claim_the_person_has_no_telegram(tmp_path):
    """`PhoneNotOccupied` arrives identically for absent and for hidden — 3.1 proved it.

    The reason a rung records is read by an operator answering "why did this not go by
    Telegram", so it may not assert the half of the disjunction we cannot see.
    """
    route, made = make_route(tmp_path)
    clients: list[FakeClient] = []

    def factory(**kwargs):
        client = FakeClient(**kwargs)
        client.invoke_returns_no_users = True
        clients.append(client)

        async def invoke(query, **kw):
            client.invocations.append((query, kw))
            if type(query).__name__ == "ResolvePhone":
                return FakeResolved([])
            raise AssertionError("nothing may be sent to a number that did not resolve")

        client.invoke = invoke
        return client

    route._factory = factory
    attempt = asyncio.run(offer(route))

    assert attempt.outcome is Outcome.MISS
    lowered = attempt.reason.lower()
    assert "no telegram" not in lowered and "has no account" not in lowered
    assert "did not resolve" in lowered


# ------------------------------------------------------------- which failures stop the ladder


def test_a_failure_while_resolving_lets_the_ladder_reach_the_modem(tmp_path):
    """Nothing can have been delivered by a lookup, so this is not indeterminate.

    The difference is the whole product: `indeterminate` stops the ladder dead, so a
    Telegram outage classified that way would strand every code instead of dropping it to
    the modem. We know structurally that no send was attempted — a stronger statement than
    the "positive statement that nothing was sent" the delta asks the library for.
    """
    route, made = make_route(tmp_path)
    clients: list[FakeClient] = []

    def factory(**kwargs):
        client = FakeClient(**kwargs)
        client.raises["ResolvePhone"] = VendorError("the transport died")
        clients.append(client)
        return client

    route._factory = factory
    attempt = asyncio.run(offer(route))

    assert attempt.outcome is Outcome.UNAVAILABLE
    assert "SendMessage" not in clients[0].invoked()


def test_a_failure_while_sending_stops_the_ladder(tmp_path):
    """The expensive one: the frame may have left, and a second code is worse than none."""
    route, _ = make_route(tmp_path)
    clients: list[FakeClient] = []

    def factory(**kwargs):
        client = FakeClient(**kwargs)
        client.raises["SendMessage"] = VendorError("connection reset")
        clients.append(client)
        return client

    route._factory = factory
    attempt = asyncio.run(offer(route))

    assert attempt.outcome is Outcome.INDETERMINATE


def test_no_vendor_type_or_exception_crosses_the_interface(tmp_path):
    """The containment that makes a change of client one module.

    The vendor's failure may be *described* in the reason — it is evidence an operator
    reads — but the object itself never leaves.
    """
    route, _ = make_route(tmp_path)

    def factory(**kwargs):
        client = FakeClient(**kwargs)
        client.raises["SendMessage"] = VendorError("boom")
        return client

    route._factory = factory
    attempt = asyncio.run(offer(route))

    assert isinstance(attempt, Attempt)
    assert isinstance(attempt.reason, str)
    assert all(isinstance(getattr(attempt, f), (str, Outcome))
               for f in ("outcome", "reason"))


# --------------------------------------------------------------- the account is not a guess


def test_a_session_belonging_to_another_account_never_sends(tmp_path):
    """Task 2.5 made mechanical at the wire, not only in the configuration.

    The brand-to-account map already keeps a rung from being handed another brand's
    account. This catches the other direction — a session *file* holding a different
    account than the one the ladder named, which no amount of configuration can see.
    """
    route, _ = make_route(tmp_path)
    clients: list[FakeClient] = []

    def factory(**kwargs):
        client = FakeClient(**kwargs)
        client.me = FakeUser(user_id=999, username="somebody_else")
        clients.append(client)
        return client

    route._factory = factory
    attempt = asyncio.run(offer(route))

    assert attempt.outcome is Outcome.UNAVAILABLE
    assert clients[0].invocations == []
    assert ACCOUNT in attempt.reason and "999" in attempt.reason


def test_an_account_named_by_its_username_is_accepted(tmp_path):
    """Operators write `@gmplus_support` as readily as `8788987307`."""
    (tmp_path / "gmplus_support.session").write_bytes(b"")
    clients: list[FakeClient] = []

    def factory(**kwargs):
        client = FakeClient(**kwargs)
        clients.append(client)
        return client

    route = tg.TelegramUserRoute(api_id=1, api_hash="h", session_dir=str(tmp_path),
                                 client_factory=factory)
    attempt = asyncio.run(offer(route, account="@gmplus_support"))
    assert attempt.outcome is Outcome.ACCEPTED


def test_a_session_that_is_not_signed_in_is_unavailable_and_asks_nothing(tmp_path):
    route, _ = make_route(tmp_path)
    clients: list[FakeClient] = []

    def factory(**kwargs):
        client = FakeClient(**kwargs)
        client.signed_in = False
        clients.append(client)
        return client

    route._factory = factory
    attempt = asyncio.run(offer(route))

    assert attempt.outcome is Outcome.UNAVAILABLE
    assert "signed in" in attempt.reason
    assert clients[0].invocations == []


def test_a_missing_session_file_is_refused_rather_than_created(tmp_path):
    """The lesson of 3.1, kept: `SQLiteStorage` creates the database when the file is
    absent, so a mistyped path would report "not signed in" about a session it had just
    minted — a lie about the file the operator believes in.

    The assertion is that no client was *built*, not merely that the outcome was
    unavailable: with the check removed the account guard downstream refuses the minted
    session too, and a test that only read the outcome would stay green over the defect.
    """
    route, made = make_route(tmp_path)
    attempt = asyncio.run(offer(route, account="typo"))

    assert attempt.outcome is Outcome.UNAVAILABLE
    assert made == [], "a client was built for a session file that does not exist"
    assert "typo.session" in attempt.reason and "no session file" in attempt.reason


def test_the_client_is_built_once_and_reused(tmp_path):
    route, made = make_route(tmp_path)
    asyncio.run(offer(route))
    asyncio.run(offer(route))
    assert len(made) == 1


def test_an_unconfigured_route_is_unavailable_and_reaches_no_vendor(tmp_path):
    """The session directory is real here on purpose.

    With an empty one the missing-file check refuses first, and this test would stay
    green with the credential check deleted — passing on a guard it is not about.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / f"{ACCOUNT}.session").write_bytes(b"")
    called = []
    route = tg.TelegramUserRoute(api_id=0, api_hash="", session_dir=str(tmp_path),
                                 client_factory=lambda **kw: called.append(kw))
    attempt = asyncio.run(offer(route))
    assert attempt.outcome is Outcome.UNAVAILABLE
    assert "not configured" in attempt.reason
    assert called == []


def test_a_text_longer_than_telegram_accepts_is_refused_before_the_number_is_disclosed(tmp_path):
    """Resolution *is* the disclosure, so a send that cannot succeed must not make one."""
    route, made = make_route(tmp_path)
    attempt = asyncio.run(offer(route, text="x" * (tg.MAX_TEXT_LENGTH + 1)))
    assert attempt.outcome is Outcome.UNAVAILABLE
    assert made == []


# ------------------------------------------------------- the vendor contract, checked by name


def test_the_library_still_has_the_knobs_this_wrapper_turns():
    """A version bump that renames one of these must fail here, not in production.

    Every name below is one the wrapper passes by keyword; the capture's
    `library_contract` was read off these same objects.
    """
    from pyrogram import Client
    from pyrogram.session.session import Session

    init = inspect.signature(Client.__init__).parameters
    for name in ("name", "api_id", "api_hash", "workdir", "sleep_threshold"):
        assert name in init, f"Client.__init__ no longer takes {name}"

    invoke = inspect.signature(Client.invoke).parameters
    for name in ("retries", "timeout", "retry_delay", "sleep_threshold"):
        assert name in invoke, f"Client.invoke no longer takes {name}"

    # The measured 160 s, derived rather than remembered.
    assert Session.MAX_RETRIES * (Session.WAIT_TIMEOUT + Session.RETRY_DELAY) > 100

    assert set(raw.functions.contacts.ResolvePhone.__slots__) == {"phone"}
    assert {"peer", "message", "random_id"}.issubset(
        set(raw.functions.messages.SendMessage.__slots__))
    assert set(raw.types.InputPeerUser.__slots__) == {"user_id", "access_hash"}


@pytest.mark.parametrize("name", ["ImportContacts", "DeleteContacts"])
def test_the_import_fallback_exists_in_the_library_and_is_deliberately_unused(name):
    """Said out loud rather than left as an absence: the call MAX needs is here too, and
    Telegram does not use it because the capture showed it answers an absent number and a
    hidden one identically while leaving an entry behind."""
    assert hasattr(raw.functions.contacts, name)
