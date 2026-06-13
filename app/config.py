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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
