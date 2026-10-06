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
    # Every transaction runs as this restricted Postgres role (created by a
    # migration), so Row-Level Security really applies: the login role in
    # DATABASE_URL is typically the owner/superuser, and superusers bypass RLS.
    # Set to "" only if your login role is already a plain non-owner role.
    db_app_role: str = "erp_app"
    # Uploaded files (company logos). Mount a persistent volume here in production.
    media_root: str = "media"

    # Public address of the web app — used to build links in emails
    # (password reset, invitations).
    app_url: str = "http://localhost:3000"
    # Public address of this API — Safaricom calls it back with M-Pesa results,
    # so it must be reachable from the internet over HTTPS in production.
    api_public_url: str = "http://localhost:8000"
    # Key for encrypting stored third-party credentials (M-Pesa API keys).
    # Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # If unset, a key is derived from JWT_SECRET (fine for development).
    encryption_key: str = ""
    # Where the businesses trade. A sale's date is the calendar day at the
    # till, not the server's (or UTC's) — they differ around midnight.
    business_timezone: str = "Africa/Nairobi"

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
