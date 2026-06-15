from app.modem.parser import describe_tp_status


def test_known_temporary_service_rejected():
    assert describe_tp_status(99) == "service rejected (temporary, st=99)"


def test_known_permanent_incompatible_destination():
    assert describe_tp_status(0x41) == "incompatible destination (permanent, st=65)"


def test_known_permanent_validity_expired():
    assert describe_tp_status(0x46) == "message validity period expired (permanent, st=70)"


def test_temporary_range_congestion():
    assert describe_tp_status(0x20) == "congestion (temporary, st=32)"


def test_unknown_code_falls_back_with_class():
    assert describe_tp_status(88) == "delivery failed (permanent, st=88)"


def test_unknown_temporary_high_range():
    assert describe_tp_status(0x70) == "delivery failed (temporary, st=112)"
