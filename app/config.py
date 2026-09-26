from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- Modem / serial ---
    serial_send_port: str = "/dev/ttyUSB2"
    serial_read_port: str = "/dev/ttyUSB3"
    serial_baudrate: int = 115200

    # --- Storage ---
    db_path: str = "data/sms.db"

    # --- Server ---
    host: str = "0.0.0.0"
    port: int = 80

    # --- Admin UI (HTTP Basic). Kept in env to avoid a lockout. ---
    admin_user: str = "admin"
    admin_password: str = "change-me"

    # --- Telegram user account (the `tg_user` rung). ---
    #
    # Here and not in the settings store, and that is the decision of task 3.5 rather
    # than a convention: the store is readable through the admin console, is dumped by
    # any backup of this gateway, and this material is a credential — `api_id`/`api_hash`
    # are issued to a person at my.telegram.org and cannot be rotated per host, and the
    # session files under `tg_session_dir` are each equal to the account itself.
    #
    # All three empty is the shipped state: the rung is then not wired at all, the
    # ladder records `route is configured but not wired`, and every message goes to the
    # modem exactly as before. Set all three, in the file named by `EnvironmentFile=` in
    # `deploy/sms-gate.service`, to turn the rung on. `tg_session_dir` must be an
    # absolute path — systemd expands no `~` — and hold one `<account>.session` file per
    # sender account, signed in by hand with `deploy/tg-sign-in.py`.
    tg_api_id: int = 0
    tg_api_hash: str = ""
    tg_session_dir: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
