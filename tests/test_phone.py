# tests/test_phone.py
import pytest

from app.phone import validate_and_normalize


def test_ru_e164_unchanged():
    assert validate_and_normalize("+79991234567", "RU") == "+79991234567"


def test_ru_national_normalized_to_e164():
    assert validate_and_normalize("89991234567", "RU") == "+79991234567"
    assert validate_and_normalize("9991234567", "RU") == "+79991234567"


def test_junk_raises():
    with pytest.raises(ValueError):
        validate_and_normalize("not-a-number", "RU")
    with pytest.raises(ValueError):
        validate_and_normalize("", "RU")


def test_us_number_valid_under_us():
    assert validate_and_normalize("+1 202 555 0173", "US") == "+12025550173"


def test_foreign_number_rejected_under_strict_region():
    with pytest.raises(ValueError):
        validate_and_normalize("+12025550173", "RU")


def test_foreign_number_allowed_in_lenient_mode():
    assert validate_and_normalize("+12025550173", "RU", restrict_region=False) == "+12025550173"


def test_region_case_insensitive():
    assert validate_and_normalize("+79991234567", "ru") == "+79991234567"
