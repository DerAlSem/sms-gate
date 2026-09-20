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

# What the person is told to do, per rung. Addresses, never identities: "call this number"
# is the address, and which SIM answers it is the identity.
_INSTRUCTIONS = {
    CALL_IN: "Call {number} from the number being verified. The call is not answered "
             "and costs you nothing; hang-up is ours.",
    SMS_IN: "Text the code you were shown to {number} from the number being verified.",
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
                offers.append(Offer(route=name, instruction=self._instruction(name)))
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
