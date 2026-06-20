from app.modem.parser import describe_at_error


def test_known_cms_code():
    assert describe_at_error("\r\n+CMS ERROR: 305\r\n") == \
        "+CMS ERROR 305 (invalid text mode parameter)"


def test_cms_350_is_named():
    out = describe_at_error("+CMS ERROR: 350")
    assert out.startswith("+CMS ERROR 350 (")
    assert "network" in out.lower()


def test_unknown_cms_3xx_gets_generic_description():
    out = describe_at_error("+CMS ERROR: 388")
    assert out.startswith("+CMS ERROR 388 (")          # no longer bare
    assert "rejection" in out.lower() or "network" in out.lower()


def test_unknown_low_cms_code_stays_bare():
    # outside the 300-511 operator-error range and not in the table
    assert describe_at_error("+CMS ERROR: 7") == "+CMS ERROR 7"


def test_plain_error():
    assert describe_at_error("\r\nERROR\r\n") == "modem returned ERROR"
