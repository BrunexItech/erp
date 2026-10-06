"""Encryption for secrets we must be able to read back (a business's M-Pesa
API keys) — unlike passwords, which are hashed and never recoverable.

Fernet (AES-128-CBC + HMAC): a stolen database dump alone is not enough to
use the keys; the attacker would also need ENCRYPTION_KEY from the server's
environment.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _fernet() -> Fernet:
    if settings.encryption_key:
        return Fernet(settings.encryption_key.encode())
    derived = base64.urlsafe_b64encode(hashlib.sha256(f"erp-secrets:{settings.jwt_secret}".encode()).digest())
    return Fernet(derived)


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode() if value else ""


def decrypt(value: str) -> str:
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        # The encryption key changed since this was stored.
        return ""


def mask(value: str) -> str:
    """For showing that a secret is set without revealing it."""
    return f"••••{value[-4:]}" if len(value) >= 8 else ("••••" if value else "")
