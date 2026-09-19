from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.phone import validate_and_normalize
from app.settings_store import store

StatusType = Literal['pending', 'sent', 'delivered', 'failed', 'expired']


class SmsSendRequest(BaseModel):
    phone: str
    # Multipart is supported (PDU + UDH concatenation). This is a coarse sanity
    # bound; the precise per-message part limit is enforced server-side by the
    # max_sms_parts setting, which fails over-long messages with a clear error.
    text: str = Field(min_length=1, max_length=1000)

    @field_validator('phone')
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return validate_and_normalize(v, store.phone_region)


class SmsSendResponse(BaseModel):
    id: int
    status: StatusType


class SmsStatusResponse(BaseModel):
    id: int
    phone: str
    text: str
    status: StatusType
    created_at: datetime
    sent_at: datetime | None
    delivered_at: datetime | None
    error: str | None
    # Additive: how many transmission attempts this message has taken. A consumer that
    # ignores unknown fields is unaffected; one that wants retry visibility has it
    # without the webhook vocabulary growing a status.
    attempts: int = 0


class VerificationCreateRequest(BaseModel):
    """The number, and nothing else that decides how.

    `extra="forbid"` is the norm made mechanical: a request naming a route, a vendor or an
    operator is refused rather than partly honoured, and so is one supplying its own code.
    `code` is declared explicitly only so that the one case the spec calls out answers with
    its own name instead of a generic "unexpected field" — the party that answers "is this
    code correct" must be the party that knows what to compare against, and splitting the
    secret from its matcher is what makes short codes unsafe.
    """

    model_config = ConfigDict(extra="forbid")

    phone: str
    code: str | None = Field(default=None, exclude=True)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return validate_and_normalize(v, store.phone_region)

    @field_validator("code")
    @classmethod
    def refuse_a_supplied_code(cls, v: str | None) -> None:
        if v is not None:
            raise ValueError("the gateway generates the code; it is not accepted here")
        return None


class RouteOffer(BaseModel):
    route: str
    # What the person must do, in words they can act on. An address, never an identity:
    # which SIM answers the number is none of the application's business.
    instruction: str


class VerificationCreateResponse(BaseModel):
    id: int
    status: str
    # Ordered by cost, cheapest first. The consumer may take the first silently or show
    # the list to the person; both are served by the same answer.
    routes: list[RouteOffer]


class RouteSelectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route: str


class RouteSelectResponse(BaseModel):
    id: int
    route: str
    status: str
    # There is exactly one exception to the code never leaving the matcher, and it is a
    # **route**, not an application. On `sms_in` the person is the sender: they read the
    # code from the screen in front of them and text it to the gateway from the number
    # being verified, so the owning application has to be able to display it. On every
    # rung the gateway itself carries, this stays None — a code returned there would let
    # the application confirm without the person ever being reached.
    #
    # Handed over here rather than at creation because at creation no rung is chosen yet.
    code: str | None = None


class VerificationStatusResponse(BaseModel):
    id: int
    phone: str
    status: str
    route: str | None
    # The method that actually proved it, which is not always the route it was carried by.
    # The methods are not equally strong: a caller number is asserted by the network and
    # can be forged, a code typed back from the number being verified adds an event the
    # attacker must also originate. An application whose stakes do not tolerate the
    # weakest must be able to see what it got rather than assume the strongest.
    method: str | None = None
    reason: str | None = None
    # What is left to try, and only on a verification that ended in failure. Moving on is
    # the consumer's act, and an act needs something to act on — the reason alone tells it
    # that the rung died without telling it what remains.
    #
    # Empty while the verification is still being carried, because a ladder handed over
    # under a live rung reads as a licence to hop, and empty on a confirmation, because
    # nothing is left to do. Computed on the read rather than stored at the ending: a
    # rung's precondition decays, and a list baked in at failure time would be exactly the
    # stale evidence this change refuses everywhere else.
    routes: list[RouteOffer] = []
    attempts: int = 0
    created_at: datetime
    expires_at: datetime
    confirmed_at: datetime | None = None


class VerificationCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str


class VerificationCheckResponse(BaseModel):
    id: int
    status: str
    # One of: confirmed, wrong_code, already_confirmed, expired, no_attempts_left. A bare
    # no is not an answer — the caller is a barrier with a person standing at it, and
    # "expired" and "wrong" mean different things to them.
    outcome: str
