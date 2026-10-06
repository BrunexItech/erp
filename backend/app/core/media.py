"""Uploaded company logos.

Every upload is decoded and re-encoded as PNG with Pillow rather than stored
as sent: that proves it's really an image (not a script with a .png name),
strips metadata, caps the dimensions, and gives the PDF engine one format to
deal with. SVG is deliberately not accepted — it can carry scripts.
"""

from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

from fastapi import HTTPException, status
from PIL import Image, UnidentifiedImageError

from app.core.config import settings

LOGO_URL_PREFIX = "/api/v1/media/logos/"
MAX_UPLOAD_BYTES = 3 * 1024 * 1024
MAX_SIDE = 1000


def logo_dir() -> Path:
    path = Path(settings.media_root) / "logos"
    path.mkdir(parents=True, exist_ok=True)
    return path


def local_logo_path(logo_url: str | None) -> Path | None:
    """Filesystem path for a logo we host, or None for external URLs."""
    if not logo_url or not logo_url.startswith(LOGO_URL_PREFIX):
        return None
    name = Path(logo_url[len(LOGO_URL_PREFIX):]).name  # no path traversal
    path = logo_dir() / name
    return path if path.is_file() else None


def save_logo(workspace_id: str, data: bytes) -> str:
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "logo must be 3 MB or smaller")
    try:
        image = Image.open(BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "that file isn't a readable image — upload a PNG or JPG")
    if image.format not in ("PNG", "JPEG", "WEBP"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "upload a PNG, JPG or WebP image")

    image = image.convert("RGBA")
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    out = BytesIO()
    image.save(out, format="PNG", optimize=True)
    png = out.getvalue()

    # Content hash in the name: a new logo gets a new URL, so browsers and
    # CDNs never show a stale one.
    name = f"{workspace_id}-{hashlib.sha256(png).hexdigest()[:12]}.png"
    for old in logo_dir().glob(f"{workspace_id}-*.png"):
        if old.name != name:
            old.unlink(missing_ok=True)
    (logo_dir() / name).write_bytes(png)
    return LOGO_URL_PREFIX + name


def delete_logos(workspace_id: str) -> None:
    for old in logo_dir().glob(f"{workspace_id}-*.png"):
        old.unlink(missing_ok=True)
