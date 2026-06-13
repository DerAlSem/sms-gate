from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.phone import validate_and_normalize
from app.settings_store import store

StatusType = Literal['pending', 'sent', 'delivered', 'failed', 'expired']


class SmsSendRequest(BaseModel):
    phone: str
    text: str = Field(min_length=1, max_length=160)

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
