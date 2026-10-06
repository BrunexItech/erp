"""Time-based one-time passwords (RFC 6238) — what Google Authenticator,
Microsoft Authenticator and Authy implement. Small enough to own rather than
add a dependency for: HMAC-SHA1 over a 30-second counter, 6 digits.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

PERIOD = 30
DIGITS = 6


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _code(secret: str, counter: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10**DIGITS).zfill(DIGITS)


def code_at(secret: str, at: float | None = None) -> str:
    return _code(secret, int((time.time() if at is None else at) // PERIOD))


def verify(secret: str, code: str, at: float | None = None, window: int = 1) -> bool:
    """Accepts the current code and one step either side, to tolerate a phone
    clock that is a little off."""
    code = code.replace(" ", "")
    if not (code.isdigit() and len(code) == DIGITS):
        return False
    counter = int((time.time() if at is None else at) // PERIOD)
    return any(hmac.compare_digest(_code(secret, counter + step), code) for step in range(-window, window + 1))


def provisioning_uri(secret: str, account: str, issuer: str) -> str:
    return f"otpauth://totp/{quote(issuer)}:{quote(account)}?secret={secret}&issuer={quote(issuer)}&digits={DIGITS}&period={PERIOD}"


def qr_svg(data: str, size: int = 200) -> str:
    """The provisioning URI as an inline SVG QR code for the setup screen."""
    from reportlab.graphics import renderSVG
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics.shapes import Drawing

    widget = QrCodeWidget(data, barLevel="M")
    x0, y0, x1, y1 = widget.getBounds()
    drawing = Drawing(size, size, transform=[size / (x1 - x0), 0, 0, size / (y1 - y0), 0, 0])
    drawing.add(widget)
    svg = renderSVG.drawToString(drawing)
    return svg[svg.index("<svg"):]


def new_recovery_codes(count: int = 8) -> list[str]:
    return [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}-{secrets.token_hex(2)}" for _ in range(count)]


def hash_recovery(code: str) -> str:
    return hashlib.sha256(code.strip().lower().encode()).hexdigest()
