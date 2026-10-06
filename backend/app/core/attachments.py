"""Files attached to records — the supplier's invoice scanned against a bill,
a signed delivery note against an invoice, a contract against an employee.

Unlike logos these are private: stored outside the public media folders,
listed and downloaded only through authenticated, tenant-scoped endpoints.
"""

from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import String
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import settings
from app.core.db import TenantModel, TenantRepository

MAX_BYTES = 10 * 1024 * 1024
# Extension -> the content type we will serve it as (never trust the upload's own).
ALLOWED = {
    ".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
    ".csv": "text/csv", ".txt": "text/plain",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
ENTITY_TYPES = {"invoice", "quote", "vendor_bill", "purchase_order", "party", "employee", "asset", "product", "journal_entry"}


class Attachment(TenantModel):
    __tablename__ = "attachments"

    entity_type: Mapped[str] = mapped_column(String(32), index=True)
    entity_id: Mapped[str] = mapped_column(String(36), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size: Mapped[int]
    stored_name: Mapped[str] = mapped_column(String(80))
    uploaded_by: Mapped[str] = mapped_column(String(36), default="")


def _dir(workspace_id: str) -> Path:
    path = Path(settings.media_root) / "attachments" / workspace_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_name(name: str) -> str:
    name = Path(name or "file").name
    return re.sub(r"[^A-Za-z0-9._ -]", "_", name)[:200] or "file"


class AttachmentService:
    def __init__(self, session: AsyncSession, workspace_id: str):
        self.session = session
        self.workspace_id = workspace_id
        self.repo = TenantRepository(session, workspace_id, Attachment)

    async def add(self, entity_type: str, entity_id: str, file: UploadFile, user_id: str) -> Attachment:
        if entity_type not in ENTITY_TYPES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "files can't be attached to that kind of record")
        filename = _safe_name(file.filename or "")
        extension = Path(filename).suffix.lower()
        if extension not in ALLOWED:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "allowed files: PDF, images, Excel, Word, CSV and text")
        data = await file.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "file is larger than 10 MB")
        if not data:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "that file is empty")
        stored = f"{uuid4().hex}{extension}"  # never the user's filename on disk
        (_dir(self.workspace_id) / stored).write_bytes(data)
        attachment = Attachment(
            entity_type=entity_type, entity_id=entity_id, filename=filename, content_type=ALLOWED[extension],
            size=len(data), stored_name=stored, uploaded_by=user_id,
        )
        await self.repo.add(attachment)
        await self.session.commit()
        await self.session.refresh(attachment)
        return attachment

    async def list(self, entity_type: str, entity_id: str) -> list[Attachment]:
        rows = await self.repo.list(Attachment.entity_type == entity_type, Attachment.entity_id == entity_id)
        return sorted(rows, key=lambda a: a.created_at, reverse=True)

    async def path(self, attachment_id: str) -> tuple[Attachment, Path]:
        attachment = await self.repo.get(attachment_id)
        if attachment is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "file not found")
        path = _dir(self.workspace_id) / Path(attachment.stored_name).name
        if not path.is_file():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "file is missing from storage")
        return attachment, path

    async def delete(self, attachment_id: str) -> None:
        attachment, path = await self.path(attachment_id)
        await self.session.delete(attachment)
        await self.session.commit()
        path.unlink(missing_ok=True)
