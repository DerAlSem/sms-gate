"""Which routes can carry a verification for this number, right now.

The registry exists because of one property of the routes this change adds: they fail
**silently**. An incoming call reaches this modem only while IMS is registered, and when
IMS goes off `RING` simply stops arriving — no error, no rejected request, no log line.
A rung offered on that basis does not fail; it hangs, expires, and reports "expired",
which is indistinguishable to everybody from "the person never called".

The remedy is not a better handler but an earlier question. A rung is offered only where
the gateway holds current evidence that it works; where it does not, the ladder starts one
rung lower and the person verifies another way without ever learning there was a problem.

Three properties of the asking matter as much as the asking:

- **Being configured is not evidence.** Neither is having worked before. A configured rung
  with no probe registered is unavailable, not assumed.
- **The set of probes is bounded as a whole**, not probe by probe. Otherwise a slow day at
  one vendor spends the budget the whole answer was promised in, and the answer arrives
  after the person has given up. A probe that has not answered when the bound is reached
  counts as unproven — the failing direction, deliberately, because a bound that expired
  is the commonest way for a precondition to go unread.
- **Evidence carries the time it was obtained** and is refused once older than a configured
  maximum. Without that, "current evidence" is undefined and the norm decides nothing: a
  reading taken once at boot would satisfy it for ever.

Placing nothing is also part of the contract. Asking a rung whether it *could* carry a
verification must not carry one: no vendor is called to send, no call is placed and no
message is composed until the consumer has selected a route.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

# The rungs, as values. Named here so that the reader, the chooser and the store cannot
# disagree by a spelling. `call` is deliberately absent and retired: it named the
# subscriber calling our SIM in one change and the vendor's flash call in another, and two
# mechanisms under one name is how an implementer builds the wrong one.
CALL_IN = "call_in"
SMS_IN = "sms_in"
SMS_OUT = "sms_out"
FLASH_CALL = "flash_call"
TG_GATEWAY = "tg_gateway"

# The three messenger ways out named by the same decision of 18.09.2026 and carried by no
# adapter yet. They are listed here rather than invented later because the vocabulary is
# required to be one: a second list, written when the first messenger lands, is how two
# words for one choice get back in. A route named in the rule with nothing to carry it is
# not attempted, is alerted about, and the ladder advances past it.
TG_USER = "tg_user"
MAX_USER = "max_user"
APP_BOT = "app_bot"

# Every way out this gateway knows. The rule validates against exactly this set.
ALL_ROUTES = frozenset({
    CALL_IN, SMS_IN, SMS_OUT, FLASH_CALL, TG_GATEWAY, TG_USER, MAX_USER, APP_BOT,
})

# The rungs this gateway pays a vendor for, named once so that the per-number limits, the
# spend ceiling and the balance floor cannot disagree about which they are. A second list
# written when a third paid vendor lands is how one of the three quietly stops counting a
# rung — and the symptom of that is only ever the bill.
#
# `sms_in` is not here: the subscriber pays for it at their own tariff, and what these
# three bound is this gateway's spending.
PAID_ROUTES = frozenset({FLASH_CALL, TG_GATEWAY})

# The two kinds of item this gateway hands to a route, and what each route is capable of
# carrying. Declared here, beside the names, because it is a property of the route rather
# than a branch inside whoever happens to be sending: a sender deciding it for itself
# would decide it differently from the ladder, and the difference would show up as free
# text going out over a route the rule did not name.
#
# `sms_out` carries words, a link, a second sentence — and a code, which is only text with
# a shape. The two paid rungs carry a code and nothing else, for two different reasons
# that arrive at the same place: a flash call's whole payload is the last four digits of
# the calling number, and `sendVerificationMessage` accepts a `code` and a `code_length`
# with no message body at all. `call_in` and `sms_in` are the subscriber reaching us,
# which is a code by construction.
#
# 🔴 **The three messenger routes are absent deliberately, and absent means "cannot".**
# No adapter carries them yet, and what a messenger user account may put in front of a
# person is a wire contract nobody here has read. Guessing them into this map would be
# guessing in the one direction that cannot be taken back: an item let out over a route
# on a supposition is an item delivered.
ARBITRARY_TEXT = "arbitrary text"
VERIFICATION_CODE = "a verification code"

_CARRIES: dict[str, frozenset[str]] = {
    CALL_IN: frozenset({VERIFICATION_CODE}),
    SMS_IN: frozenset({VERIFICATION_CODE}),
    SMS_OUT: frozenset({ARBITRARY_TEXT, VERIFICATION_CODE}),
    FLASH_CALL: frozenset({VERIFICATION_CODE}),
    TG_GATEWAY: frozenset({VERIFICATION_CODE}),
}


# The rungs that carry a code only inside wording of **ours**. One today, and it is here
# beside `_CARRIES` for the same reason that map is: it is a property of the route rather
# than a branch inside whoever happens to be asking, and the two questions it answers —
# may this application be offered this rung, and may this verification be accepted at all
# — must not be able to disagree.
#
# The two paid rungs are absent because there is nowhere in them to put words:
# `sendVerificationMessage` takes a `code` and a `code_length` and no message body, and a
# flash call's whole payload is the last four digits of the calling number. `call_in` and
# `sms_in` are absent because the subscriber is the one who sends.
_NEEDS_OUR_WORDS = frozenset({SMS_OUT})


def needs_our_words(route: str) -> bool:
    """Whether carrying a code by this route requires text this gateway composes.

    An unknown route answers **no**, and that is the safe direction here rather than the
    failing one: this answer is only ever read together with `carries`, which answers no
    for an unknown route, so a route nothing knows can neither carry a code nor be the
    reason a verification is refused for want of a template.
    """
    return route in _NEEDS_OUR_WORDS


def carries_a_code_without_our_words(route: str) -> bool:
    """The question the accept door actually asks, in one place so it cannot drift.

    "Can this rung carry a code for an application that has configured no wording?" —
    and it is the conjunction, because either half alone is wrong: a route that needs
    our words is not an answer, and neither is one that cannot carry a code at all.
    """
    return carries(route, VERIFICATION_CODE) and not needs_our_words(route)


def carries(route: str, item: str) -> bool:
    """Whether this route is capable of carrying this kind of item at all.

    An unknown route answers no. That is the failing direction and it is the wanted one:
    the rule is configuration, a route may be named in it before anything can carry it,
    and the cost of answering yes by default is a message sent somewhere nobody chose.
    """
    return item in _CARRIES.get(route, frozenset())


# What the person is told to do, per rung. Addresses, never identities: "call this number"
# is the address, and which SIM answers it is the identity.
_INSTRUCTIONS = {
    CALL_IN: "Call {number} from the number being verified. The call is not answered "
             "and costs you nothing; hang-up is ours.",
    SMS_IN: "Text the code you were shown to {number} from the number being verified.",
    # No address to give and none needed: the message comes to the number being verified,
    # which the person already gave. Present all the same, because a rung with no entry
    # is an offer that names a route and tells the person nothing — the defect the
    # Telegram rung shipped with.
    SMS_OUT: "Wait for an SMS to the number being verified and read the code from it.",
    # The address is Telegram itself, and that is all the person needs: the message
    # arrives in the account registered to the number being verified. Which Gateway
    # account paid for it is the identity, and stays unsaid. This rung shipped with no
    # entry at all, which made it an offer that named a route and told the person
    # nothing — and the capability requires the answer to say what they must do.
    TG_GATEWAY: "Open Telegram on the number being verified and read the code from the "
                "message that arrives there.",
    # No address to give: the call comes **to** the number being verified, and the whole
    # payload is the last four digits of the number it comes from. Said as "do not answer"
    # because a person who answers pays nothing and learns nothing, and because a call
    # that is answered is a call the vendor may bill differently.
    FLASH_CALL: "Wait for a call to the number being verified and read the code off the "
                "calling number: it is the last four digits. Do not answer the call.",
}

# Rungs whose instruction has to name a number the subscriber calls or texts. A rung whose
# instruction would read "reach us, we cannot say where" is not an offer.
_NEEDS_GATEWAY_NUMBER = frozenset({CALL_IN, SMS_IN})


@dataclass(frozen=True)
class Proof:
    """What a probe answers: whether the rung can work, and when that was established.

    `measured_at` is unix time and may be None, meaning "established by this probe, now".
    It exists for evidence the gateway did not gather itself — the voice route's IMS
    reading is taken by a sweep on its own schedule, and how stale such a reading may be
    before a person is sent down a route that no longer works is a decision, not a detail.
    """

    holds: bool
    reason: str = ""
    measured_at: float | None = None


@dataclass(frozen=True)
class Offer:
    """One rung the gateway is prepared to carry this verification by."""

    route: str
    instruction: str
    # The number the subscriber must dial or text, as **data** rather than only inside the
    # sentence. `None` on every rung where there is nothing for them to reach: the gateway
    # acts, and a number there would be an address to somewhere they must not go.
    #
    # 🔴 The owner's decision of 22.09.2026, and the reason is that `instruction` is English
    # and not ours to translate: `docs/i18n.md` covers the admin console and nothing else,
    # and there is no gettext anywhere in this package. An application whose person reads
    # Russian therefore had two options and both were bad — show them English, or recover
    # the digits with a regular expression over our prose, which would make our wording an
    # unwritten contract that breaks the day somebody improves a sentence.
    #
    # The remedy is a field rather than a translation. The estate holds the number as
    # configuration and can hand it over as data, leaving the wording to the application
    # that owns the screen.
    number: str | None = None


Probe = Callable[[str], Awaitable[Proof]]


def unavailable(offers: list[Offer]) -> bool:
    """Whether this is the refusal case rather than merely a short ladder.

    Said as its own word because the answer "no routes" must not be served as an opened
    verification with an empty list: a verification whose only possible outcome is to
    expire should never have been opened.
    """
    return not offers


class Registry:
    """The ladder: which rungs exist, in what order, and whether each can prove itself."""

    def __init__(
        self,
        *,
        probes: dict[str, Probe],
        order: list[str],
        probe_timeout: float = 5.0,
        max_proof_age: float = 300.0,
        gateway_number: str = "",
    ) -> None:
        self._probes = dict(probes)
        self._order = list(order)
        self._probe_timeout = probe_timeout
        self._max_proof_age = max_proof_age
        self._gateway_number = gateway_number
        # Abandoned probes are counted rather than shrugged at. A gateway that answers
        # slowly instead of refusing turns the cheap rung off silently: every verification
        # still completes, by a dearer route, and the only visible symptom is the bill.
        self.abandoned_probes = 0

    async def offer(
        self, phone: str, *, without: frozenset[str] | set[str] = frozenset(),
    ) -> list[Offer]:
        """The rungs that can carry a verification for `phone`, in configured order.

        Places nothing. Every probe runs concurrently under one bound; whatever has not
        answered by then is unproven and its rung is absent.

        `without` drops rungs before anything is asked, and it is a parameter rather than
        a filter over the result because the ladder's own rules read the membership: the
        paid rung is dropped when *anything cheaper proved itself*, and a caller that
        removed the cheap rung afterwards would be told there is nothing left when in
        fact the dear rung is exactly what remains. Dropping first also spends no budget
        probing a rung whose answer is not wanted.
        """
        candidates = [name for name in self._order
                      if name not in without and self._is_offerable(name)]
        if not candidates:
            return []

        tasks = {
            name: asyncio.ensure_future(self._probes[name](phone))
            for name in candidates
        }
        await asyncio.wait(tasks.values(), timeout=self._probe_timeout)

        offers = []
        for name in candidates:
            task = tasks[name]
            if not task.done():
                task.cancel()
                self.abandoned_probes += 1
                logger.info("Route %s: precondition probe did not answer within %.1fs",
                            name, self._probe_timeout)
                continue
            if self._proven(name, task):
                offers.append(Offer(route=name, instruction=self._instruction(name),
                                    number=self._number_for(name)))
        return self._drop_paid_rung_if_anything_cheaper_proved_itself(offers)

    def _drop_paid_rung_if_anything_cheaper_proved_itself(
        self, offers: list[Offer],
    ) -> list[Offer]:
        """`sms_in` exists to be reached when everything cheaper failed.

        It is the only route on which **the subscriber** pays — one message at their
        tariff — and the weakest of them on evidence, and both facts point the same way.
        Cheaper means earlier in the configured order and nothing else: the ladder is the
        one statement of price, and a second opinion held here would be able to disagree
        with it.
        """
        if len(offers) < 2 or SMS_IN not in {o.route for o in offers}:
            return offers
        position = self._order.index(SMS_IN)
        if any(self._order.index(o.route) < position for o in offers):
            return [o for o in offers if o.route != SMS_IN]
        return offers

    def _is_offerable(self, name: str) -> bool:
        """Whether this rung may even be asked. Configuration is not evidence."""
        if name not in self._probes:
            logger.info("Route %s is configured but nothing can prove it", name)
            return False
        if name in _NEEDS_GATEWAY_NUMBER and not self._gateway_number:
            logger.info("Route %s needs a number for the subscriber to reach, and the "
                        "gateway holds none", name)
            return False
        return True

    def _proven(self, name: str, task: asyncio.Future) -> bool:
        """Whether the probe's answer is evidence this rung works now."""
        try:
            proof = task.result()
        except Exception as e:
            # A precondition that cannot be read is not a satisfied one. This is the whole
            # failing direction, and it is where the first rung would otherwise die quietly.
            logger.warning("Route %s: precondition could not be read: %s", name, e)
            return False
        if not proof.holds:
            logger.info("Route %s: precondition does not hold (%s)", name,
                        proof.reason or "no reason given")
            return False
        if proof.measured_at is not None:
            age = time.time() - proof.measured_at
            if age > self._max_proof_age:
                logger.info("Route %s: the proof is %.0fs old, past the %.0fs maximum",
                            name, age, self._max_proof_age)
                return False
        return True

    def _instruction(self, name: str) -> str:
        template = _INSTRUCTIONS.get(name, "")
        return template.format(number=self._gateway_number)

    def _number_for(self, name: str) -> str | None:
        """The number this rung asks the subscriber to reach, or `None`.

        Keyed on the same set the instruction's own precondition is keyed on, so the field
        and the sentence cannot disagree: a rung that is offered at all has passed
        `_can_instruct`, which is what guarantees the number is held. Anywhere else the
        answer is `None` rather than the gateway's number — on those rungs the gateway is
        the one that acts, and handing back an address would invite an application to tell
        somebody to call it.
        """
        if name not in _NEEDS_GATEWAY_NUMBER:
            return None
        return self._gateway_number or None
