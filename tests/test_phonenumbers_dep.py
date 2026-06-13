# tests/test_phonenumbers_dep.py
def test_phonenumbers_importable():
    import phonenumbers  # noqa: F401
    assert "RU" in phonenumbers.SUPPORTED_REGIONS
    assert "US" in phonenumbers.SUPPORTED_REGIONS
