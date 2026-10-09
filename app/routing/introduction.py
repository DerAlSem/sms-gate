"""Task 5.3 — what a brand's account says the first time it writes to a number.

`messenger-delivery`: "the first message to a recipient SHALL identify who is writing and
why". The justification the specification gives is not manners — "A personal account
writing a payment link to a stranger who cannot verify it is us is correctly read as fraud
on the evidence available to them, and the only action the design otherwise leaves them is
the report that costs the brand its account permanently."

**What counts as the first time is the whole of the decision, and the two ledgers this
change already writes answer different questions.** `messenger_disclosures` records the
*offer* — a number is sent to the vendor before any verdict is reached, so a miss is a
disclosure too. Read as first contact it would call a person we have never written to
"already introduced", and every code they ever received would arrive bare. The rung
ledger's `accepted` rows are the messages a vendor actually took, and they are what a
recipient saw.

**And the recipient sees an account, not a brand.** The key is the pair (route, account)
against the number. Keyed on the brand, the account replaced the day one is banned would
open a conversation nobody has ever seen with a bare payment code; keyed on the route
alone, a second brand would inherit the first one's introduction.

`indeterminate` deliberately does **not** count as having written. It may have arrived, and
treating "may have" as "did" is the direction that never introduces; the other direction
introduces twice, which costs a person one redundant sentence.

The decision is pure and the lookup is not: `dispatch` is the seam that can reach the
database, the ladder is what calls a vendor, and this module is what they agree on.
"""
from __future__ import annotations

from dataclasses import dataclass

#: Between the introduction and the message itself. A blank line, because the two are not
#: one sentence: what follows has to stay copyable and readable as the code it is.
SEPARATOR = "\n\n"

#: The ceiling on a recorded introduction, refused at save time.
#:
#: Telegram's own ceiling for one message is 4096 and the message has to fit under it with
#: the code still in it. The bound is far below that on purpose — an introduction is two
#: or three sentences, and one long enough to push a verification code off a phone screen
#: defeats the thing it is prefixed to.
MAX_LENGTH = 500


@dataclass(frozen=True)
class Introduction:
    """Whether this rung owes this recipient an introduction, and what it would say.

    Two fields rather than one string, because "not needed" and "needed and we have none"
    are opposite states that a single empty string would merge — and merging them is how a
    stranger receives a bare code from a personal account.
    """

    #: True when this account has never had a message accepted to this number.
    required: bool
    #: What the brand records for this route, "" when it records nothing.
    text: str = ""

    @property
    def unrecorded(self) -> bool:
        """Owed an introduction, with none recorded. The rung must not be offered."""
        return self.required and not self.text


def decide(*, recorded: str, already_written: bool) -> Introduction:
    """The decision, over the two facts that settle it and nothing else."""
    return Introduction(required=not already_written, text=(recorded or "").strip())


def compose(intro: Introduction, text: str) -> str:
    """The text this rung is handed.

    Raises rather than returning the bare text when an introduction is owed and none is
    recorded. The ladder refuses such a rung before reaching here, so this is the second
    statement of that rule — and it is written as a raise precisely because a second
    statement that merely returns something plausible is how the first one stops being
    exercised without anybody noticing.
    """
    if intro.unrecorded:
        raise ValueError(
            "an introduction is owed to this recipient and none is recorded; the rung "
            "must not be offered at all, because resolving the number discloses it to "
            "the vendor before any send happens"
        )
    if not intro.required:
        return text
    return f"{intro.text}{SEPARATOR}{text}"
