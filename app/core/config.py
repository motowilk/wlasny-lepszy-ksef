from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = Field(default="KSeF ERP App", alias="APP_NAME")
    app_env: str = Field(default="dev", alias="APP_ENV")
    app_host: str = Field(default="127.0.0.1", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    app_debug: bool = Field(default=False, alias="APP_DEBUG")
    base_url: str = Field(default="http://127.0.0.1:8000", alias="BASE_URL")

    db_host: str = Field(default="127.0.0.1", alias="DB_HOST")
    db_port: int = Field(default=3306, alias="DB_PORT")
    db_name: str = Field(default="ksef_erp", alias="DB_NAME")
    db_user: str = Field(default="", alias="DB_USER")
    db_password: str = Field(default="", alias="DB_PASSWORD")

    basic_auth_realm: str = Field(default="KSeF ERP", alias="BASIC_AUTH_REALM")
    secret_key: str = Field(default="change_me", alias="SECRET_KEY")
    ksef_mode: str = Field(default="mock", alias="KSEF_MODE")

    smtp_host: str = Field(default="", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_user: str = Field(default="", alias="SMTP_USER")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
    smtp_from: str = Field(default="noreply@example.com", alias="SMTP_FROM")
    default_notification_email: str = Field(
        default="accountant@example.com",
        alias="DEFAULT_NOTIFICATION_EMAIL",
    )

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_dir: str = Field(default="logs", alias="LOG_DIR")

    # Worker tuning
    worker_poll_interval: int = Field(default=5, alias="WORKER_POLL_INTERVAL")
    scheduler_interval: int = Field(default=10, alias="SCHEDULER_INTERVAL")

    admin_default_password: str = Field(default="", alias="ADMIN_DEFAULT_PASSWORD")

    ksef_api_url: str = Field(
        default="https://api.ksef.mf.gov.pl/v2",
        alias="KSEF_API_URL",
    )
    ksef_token: str = Field(default="", alias="KSEF_TOKEN")
    ksef_nip: str = Field(default="", alias="KSEF_NIP")

    @field_validator("secret_key")
    @classmethod
    def secret_key_not_default(cls, v: str) -> str:
        if v == "change_me":
            raise ValueError(
                "SECRET_KEY is set to the insecure default 'change_me'. "
                "Generate a strong key with: "
                "python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        return v

    @property
    def sqlalchemy_database_uri(self) -> str:
        return (
            f"mysql+pymysql://{quote_plus(self.db_user)}:{quote_plus(self.db_password)}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}?charset=utf8mb4"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
