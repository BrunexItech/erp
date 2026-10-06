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
# Images served without sign-in: they appear on documents sent to customers
# and in <img> tags. Nothing sensitive may be stored in these.
PUBLIC_IMAGE_FOLDERS = ("logos", "products")


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
    return save_image("logos", workspace_id, data)


def image_dir(folder: str) -> Path:
    path = Path(settings.media_root) / folder
    path.mkdir(parents=True, exist_ok=True)
    return path


def local_image_path(url: str | None) -> Path | None:
    """Filesystem path for any image we host (/api/v1/media/<folder>/<name>)."""
    prefix = "/api/v1/media/"
    if not url or not url.startswith(prefix):
        return None
    folder, _, name = url[len(prefix):].partition("/")
    if folder not in PUBLIC_IMAGE_FOLDERS:
        return None
    path = image_dir(folder) / Path(name).name
    return path if path.is_file() else None


def save_image(folder: str, key: str, data: bytes, max_side: int = MAX_SIDE) -> str:
    """Validate, normalise to PNG and store under <media>/<folder>, replacing
    any earlier image for the same key. Returns its public URL path."""
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
    image.thumbnail((max_side, max_side))
    out = BytesIO()
    image.save(out, format="PNG", optimize=True)
    png = out.getvalue()

    # Content hash in the name: a new logo gets a new URL, so browsers and
    # CDNs never show a stale one.
    name = f"{key}-{hashlib.sha256(png).hexdigest()[:12]}.png"
    directory = image_dir(folder)
    for old in directory.glob(f"{key}-*.png"):
        if old.name != name:
            old.unlink(missing_ok=True)
    (directory / name).write_bytes(png)
    return f"/api/v1/media/{folder}/{name}"


def delete_logos(workspace_id: str) -> None:
    for old in logo_dir().glob(f"{workspace_id}-*.png"):
        old.unlink(missing_ok=True)
