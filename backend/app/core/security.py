from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)


def create_access_token(user_id: str, token_version: int = 0, impersonator: str | None = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    claims = {"sub": user_id, "type": "access", "exp": expire, "tv": token_version}
    if impersonator:
        claims["imp"] = impersonator  # a platform admin signed in as this user
    return jwt.encode(
        claims,
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def create_refresh_token(user_id: str, token_version: int = 0) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.refresh_token_expire_days
    )
    return jwt.encode(
        {"sub": user_id, "type": "refresh", "exp": expire, "tv": token_version},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def decode_claims(token: str, expected_type: str = "access") -> dict:
    """Returns the token's claims if valid, raises JWTError otherwise."""
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    if payload.get("type") != expected_type:
        raise JWTError(f"expected {expected_type} token")
    return payload


def decode_token(token: str, expected_type: str = "access") -> str:
    """Returns the user_id (sub) if valid, raises JWTError otherwise."""
    return decode_claims(token, expected_type)["sub"]
