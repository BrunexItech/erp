from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://erp:erp@localhost:5432/erp"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 30
    testing: bool = False
    # Uploaded files (company logos). Mount a persistent volume here in production.
    media_root: str = "media"

    # Public address of the web app — used to build links in emails
    # (password reset, invitations).
    app_url: str = "http://localhost:3000"

    # Outgoing email. With no SMTP host set, messages are written to
    # <media_root>/outbox as .eml files instead of being sent, so development
    # and demos work without a mail account and nothing is silently dropped.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True
    mail_from: str = "no-reply@localhost"
    mail_from_name: str = "Business Suite"


settings = Settings()
