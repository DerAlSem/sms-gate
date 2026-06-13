import pytest
from pydantic import ValidationError

from app.api.schemas import SmsSendRequest


def test_valid_ru_e164_accepted():
    req = SmsSendRequest(phone="+79991234567", text="hi")
    assert req.phone == "+79991234567"


def test_ru_national_normalized():
    req = SmsSendRequest(phone="89991234567", text="hi")
    assert req.phone == "+79991234567"


def test_invalid_phone_rejected():
    with pytest.raises(ValidationError):
        SmsSendRequest(phone="not-a-phone", text="hi")


def test_foreign_number_rejected_default_region_ru():
    with pytest.raises(ValidationError):
        SmsSendRequest(phone="+12025550173", text="hi")
