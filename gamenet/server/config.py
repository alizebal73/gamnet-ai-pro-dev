from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    server_host: str = "127.0.0.1"
    server_port: int = 8765
    database_path: Path = PROJECT_ROOT / "data" / "gamenet.db"
    migrations_dir: Path = PROJECT_ROOT / "database" / "migrations"

    heartbeat_interval_sec: int = 1
    connection_timeout_sec: int = 5
    reconnect_interval_sec: int = 2
    auto_resume: bool = False
    one_active_session_per_customer: bool = True
    payment_provider: str = "mock"

    auth_token_ttl_hours: int = 12
    login_max_attempts: int = 5
    login_lockout_minutes: int = 15


settings = Settings()
