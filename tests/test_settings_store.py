# tests/test_settings_store.py
import json

import pytest

from app.settings_store import SETTINGS_SPEC, cast_value, normalize_raw, validate_raw


def test_spec_has_all_soft_keys():
    keys = {s.key for s in SETTINGS_SPEC}
    assert keys == {
        "voxlink_enabled", "voxlink_url", "voxlink_timeout", "voxlink_cache_ttl_days",
        "alert_bot_token", "alert_chat_id", "alert_dedup_window", "alert_relay_base",
        "instance_name",
        "notify_system_errors", "notify_send_errors",
        "notify_delivery_errors", "notify_inbound", "notify_dispatch_errors",
        "telegram_replies_enabled",
        "inbound_dispatch", "delivery_dispatch",
        "inbound_dispatch_retries", "inbound_dispatch_timeout",
        "blacklist_threshold", "delivery_timeout_seconds",
        "phone_region", "max_sms_parts", "modem_watchdog_enabled",
        "send_retry_backoff", "send_stall_recovery_enabled",
    }


def test_modem_watchdog_default_is_true():
    from app.settings_store import store
    assert store.modem_watchdog_enabled is True


def test_instance_name_default_is_blank():
    from app.settings_store import store
    assert store.instance_name == ""


def test_delivery_timeout_default_is_300():
    spec = {s.key: s for s in SETTINGS_SPEC}["delivery_timeout_seconds"]
    assert spec.type == "int"
    assert spec.default == 300


def test_cast_bool_int_float():
    assert cast_value("bool", "true") is True
    assert cast_value("bool", "0") is False
    assert cast_value("int", "7") == 7
    assert cast_value("float", "5.0") == 5.0
    assert cast_value("str", "x") == "x"


def test_validate_rejects_bad_int():
    with pytest.raises(ValueError):
        validate_raw("int", "not-a-number")


def test_validate_routes_requires_json_list():
    validate_raw("routes", "", "prefix")
    validate_raw("routes", '[{"prefix":"X","webhook_url":"https://x.test/hook"}]', "prefix")
    with pytest.raises(ValueError):
        validate_raw("routes", "{not json", "prefix")
    with pytest.raises(ValueError):
        validate_raw("routes", '{"a":1}', "prefix")


def test_validate_routes_requires_absolute_url():
    """A url without a scheme never leaves httpx — reject it at save time."""
    with pytest.raises(ValueError):
        validate_raw("routes", '[{"prefix":"X","webhook_url":"x.test/hook"}]', "prefix")
    with pytest.raises(ValueError):
        validate_raw("routes", '[{"prefix":"X","webhook_url":""}]', "prefix")
    with pytest.raises(ValueError):
        validate_raw("routes", '[{"prefix":"","webhook_url":"https://x.test/hook"}]', "prefix")
    with pytest.raises(ValueError):
        validate_raw("routes", '["not-an-object"]', "prefix")


def test_validate_routes_checks_the_key_field_of_that_setting():
    """A delivery route pasted into the inbound setting must not validate."""
    delivery = '[{"app_id":"app1","webhook_url":"https://x.test/hook"}]'
    validate_raw("routes", delivery, "app_id")
    with pytest.raises(ValueError):
        validate_raw("routes", delivery, "prefix")
    with pytest.raises(ValueError):
        validate_raw("routes", '[{"prefix":"X","webhook_url":"https://x.test/h"}]', "app_id")


def test_validate_routes_needs_a_route_key():
    with pytest.raises(ValueError):
        validate_raw("routes", '[{"prefix":"X","webhook_url":"https://x.test/h"}]')


def test_validate_routes_tolerates_pasted_whitespace():
    """Surrounding whitespace is normalized away, not an error."""
    validate_raw("routes", '[{"prefix":" X ","webhook_url":" https://x.test/hook "}]', "prefix")
    validate_raw("routes", '[{"app_id":" app1 ","webhook_url":" https://x.test/h "}]', "app_id")


def test_normalize_inbound_dispatch_strips_route_fields():
    raw = '[{"prefix":" gmp ","webhook_url":" https://x.test/hook\\n","bearer":" tok "}]'
    assert json.loads(normalize_raw("routes", raw)) == [
        {"prefix": "gmp", "webhook_url": "https://x.test/hook", "bearer": "tok"}
    ]


def test_normalize_leaves_other_types_alone():
    assert normalize_raw("int", " 7 ") == " 7 "
    assert normalize_raw("routes", "") == ""


def test_inbound_dispatch_parsed_strips_stored_whitespace():
    """Rows written before validation existed must still route (leading-space url bug)."""
    store = SettingsStore()
    store._cache["inbound_dispatch"] = (
        '[{"prefix":"GMP","webhook_url":" https://x.test/hook ","bearer":" tok "}]'
    )
    assert store.inbound_dispatch_parsed == [
        {"prefix": "GMP", "webhook_url": "https://x.test/hook", "bearer": "tok"}
    ]

import asyncio

from app.db.connection import init_db, close_db
from app.db.migrate import run_migrations
from app.settings_store import SettingsStore


def _with_db(coro):
    async def run():
        await init_db(":memory:")
        await run_migrations()
        return await coro()
    try:
        return asyncio.run(run())
    finally:
        asyncio.run(close_db())


def test_getter_returns_default_when_unset():
    store = SettingsStore()
    assert store.voxlink_enabled is True
    assert store.delivery_timeout_seconds == 300
    assert store.alert_bot_token == ""


def test_set_many_then_get_roundtrip():
    async def body():
        store = SettingsStore()
        await store.load()
        await store.set_many({"voxlink_timeout": "9.5", "voxlink_enabled": "false"})
        assert store.voxlink_timeout == 9.5
        assert store.voxlink_enabled is False
        store2 = SettingsStore()
        await store2.load()
        assert store2.voxlink_timeout == 9.5
    _with_db(body)


def test_set_many_validates_before_writing_anything():
    async def body():
        store = SettingsStore()
        await store.load()
        await store.set_many({"voxlink_timeout": "9.9"})   # non-default baseline
        import pytest
        with pytest.raises(ValueError):
            await store.set_many({"voxlink_timeout": "1.0", "blacklist_threshold": "abc"})
        assert store.voxlink_timeout == 9.9                # neither change applied
    _with_db(body)


def test_change_hooks_fire_on_relevant_group():
    async def body():
        store = SettingsStore()
        await store.load()
        seen = []
        store.on_change("Alerting", lambda: seen.append(1))
        await store.set_many({"voxlink_timeout": "1.0"})
        assert seen == []
        await store.set_many({"alert_chat_id": "42"})
        assert seen == [1]
    _with_db(body)


def test_phone_region_default_is_ru():
    spec = {s.key: s for s in SETTINGS_SPEC}["phone_region"]
    assert spec.type == "region"
    assert spec.default == "RU"


def test_cast_region_uppercases():
    from app.settings_store import cast_value
    assert cast_value("region", "us") == "US"


def test_validate_region_accepts_supported_rejects_unknown():
    from app.settings_store import validate_raw
    validate_raw("region", "US")
    validate_raw("region", "ru")          # case-insensitive
    import pytest
    with pytest.raises(ValueError):
        validate_raw("region", "ZZ")
    with pytest.raises(ValueError):
        validate_raw("region", "")


def test_inbound_dispatch_parsed_filters_invalid_rows():
    store = SettingsStore()
    store._cache["inbound_dispatch"] = '[{"prefix":"X","webhook_url":"u"},{"prefix":"Y"}]'
    parsed = store.inbound_dispatch_parsed
    assert parsed == [{"prefix": "X", "webhook_url": "u"}]


def test_delivery_dispatch_parsed_keys_on_app_id():
    store = SettingsStore()
    store._cache["delivery_dispatch"] = (
        '[{"app_id":" app1 ","webhook_url":" https://x.test/d ","bearer":" t "},'
        ' {"app_id":"","webhook_url":"https://x.test/d"},'
        ' {"app_id":"turbo"}]'
    )
    assert store.delivery_dispatch_parsed == [
        {"app_id": "app1", "webhook_url": "https://x.test/d", "bearer": "t"}
    ]


def test_delivery_dispatch_defaults_to_no_routes():
    assert SettingsStore().delivery_dispatch_parsed == []


def test_max_sms_parts_default_is_6():
    from app.settings_store import SPEC_BY_KEY, store
    assert "max_sms_parts" in SPEC_BY_KEY
    assert store.max_sms_parts == 6


def test_notification_toggle_defaults():
    from app.settings_store import store
    assert store.notify_system_errors is True
    assert store.notify_send_errors is False
    assert store.notify_delivery_errors is False
    assert store.notify_inbound is False


def test_telegram_replies_default_is_false():
    from app.settings_store import store
    assert store.telegram_replies_enabled is False
