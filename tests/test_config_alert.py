from app.config import Settings


def test_settings_keeps_bootstrap_fields():
    s = Settings(_env_file=None)
    assert s.serial_send_port == "/dev/ttyUSB2"
    assert s.db_path == "data/sms.db"
    assert s.admin_user == "admin"


def test_soft_fields_are_no_longer_on_settings():
    # voxlink / alert / inbound_dispatch moved to SettingsStore (DB-backed).
    s = Settings(_env_file=None)
    for gone in ("alert_bot_token", "voxlink_url", "inbound_dispatch",
                 "blacklist_threshold", "delivery_timeout_seconds"):
        assert not hasattr(s, gone), f"{gone} should have moved to SettingsStore"
