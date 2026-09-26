"""Gap-free, human-readable document numbers (INV-000123, PO-000045, ...).

Sage-style ERPs print sequential numbers on every document — an invoice ID of
"3f9a2c1e" is not something an SME can put on a tax invoice or quote over the
phone. One DocumentSequence row per (workspace, key) is row-locked while the
next value is taken, so two concurrent invoices can never get the same number,
and because it's taken inside the caller's transaction a rolled-back document
also rolls back its number (no gaps from failed saves).
"""

from __future__ import annotations

from sqlalchemy import String, UniqueConstraint, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import TenantModel

# key -> default prefix. Workspaces can't rename these yet; the prefix is stored
# on the row so that becomes a settings change later, not a migration.
DEFAULT_PREFIXES: dict[str, str] = {
    "invoice": "INV",
    "credit_note": "CN",
    "quote": "QT",
    "sales_order": "SO",
    "purchase_order": "PO",
    "vendor_bill": "BILL",
    "journal": "JE",
    "payroll_run": "PR",
    "employee": "EMP",
    "asset": "FA",
    "work_order": "WO",
    "receipt": "RCT",
}


class DocumentSequence(TenantModel):
    __tablename__ = "document_sequences"

    key: Mapped[str] = mapped_column(String(32))
    prefix: Mapped[str] = mapped_column(String(16))
    next_value: Mapped[int] = mapped_column(default=1)
    padding: Mapped[int] = mapped_column(default=6)

    __table_args__ = (UniqueConstraint("workspace_id", "key", name="uq_document_sequence_key"),)


async def next_number(session: AsyncSession, workspace_id: str, key: str) -> str:
    stmt = (
        select(DocumentSequence)
        .where(DocumentSequence.workspace_id == workspace_id, DocumentSequence.key == key)
        .with_for_update()
    )
    seq = (await session.execute(stmt)).scalar_one_or_none()
    if seq is None:
        seq = DocumentSequence(
            workspace_id=workspace_id,
            key=key,
            prefix=DEFAULT_PREFIXES.get(key, key.upper()[:6]),
            next_value=1,
        )
        try:
            async with session.begin_nested():
                session.add(seq)
                await session.flush()
        except IntegrityError:
            # Lost a first-use race — the row exists now; lock it and continue.
            seq = (await session.execute(stmt)).scalar_one()

    value = seq.next_value
    seq.next_value = value + 1
    await session.flush()
    return f"{seq.prefix}-{value:0{seq.padding}d}"
