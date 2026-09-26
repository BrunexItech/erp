from __future__ import annotations

from datetime import datetime
from typing import AsyncIterator, Generic, Sequence, TypeVar
from uuid import uuid4

from sqlalchemy import ForeignKey, Select, func, select, text
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import NullPool

from app.core.config import settings

# NullPool in tests: pytest-asyncio's session-scoped event loop means every test
# shares one engine, and a pooled connection left mid-operation by one test's
# asyncio.gather (concurrency tests) or failure can poison the next test's session.
# A fresh physical connection per checkout avoids that; production keeps normal
# pooling.
engine = (
    create_async_engine(settings.database_url, poolclass=NullPool)
    if settings.testing
    else create_async_engine(settings.database_url, pool_pre_ping=True)
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Plain, unscoped session — only for platform-root tables (Workspace, User, Package)
    that are NOT tenant-owned. Every other module must use get_tenant_session (see actor.py)."""
    async with SessionLocal() as session:
        yield session


class Base(AsyncAttrs, DeclarativeBase):
    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: str(uuid4()))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )


class TenantMixin:
    """Mixed into every tenant-owned model. Injects workspace_id (FK'd to
    workspaces.id) with its own index.

    This alone is NOT the tenancy guarantee — see TenantRepository below and the
    Postgres Row-Level Security policy applied in Alembic migrations (core/rls.py).
    Those three layers together are what make cross-tenant leakage structurally hard,
    not just a matter of developer discipline.

    Note: subclasses that need their own __table_args__ (unique constraints etc.)
    must declare it as a @declared_attr too and include a workspace_id index/FK
    consideration only if they need composite constraints — the column-level
    index=True below already gives every tenant table a plain workspace_id index
    on its own.
    """

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), index=True, nullable=False
    )


class TenantModel(Base, TenantMixin):
    __abstract__ = True


ModelT = TypeVar("ModelT", bound=TenantModel)


class TenantRepository(Generic[ModelT]):
    """The only sanctioned way to query a TenantModel. No method here can return or
    persist a row without workspace_id scoping — services must not call
    `session.execute(select(Model))` directly against tenant tables (enforced by CI grep,
    see backend/scripts/check_tenant_queries.py).
    """

    model: type[ModelT]

    def __init__(self, session: AsyncSession, workspace_id: str, model: type[ModelT] | None = None):
        self.session = session
        self.workspace_id = workspace_id
        if model is not None:
            self.model = model

    def _base_stmt(self) -> Select:
        return select(self.model).where(self.model.workspace_id == self.workspace_id)

    async def get(self, id: str) -> ModelT | None:
        stmt = self._base_stmt().where(self.model.id == id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_for_update(self, id: str) -> ModelT | None:
        stmt = self._base_stmt().where(self.model.id == id).with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list(self, *filters) -> Sequence[ModelT]:
        stmt = self._base_stmt().where(*filters)
        return (await self.session.execute(stmt)).scalars().all()

    def query(self) -> Select:
        """Escape hatch for complex queries (joins, aggregates) — still pre-scoped
        to this repository's workspace_id."""
        return self._base_stmt()

    async def add(self, obj: ModelT) -> ModelT:
        obj.workspace_id = self.workspace_id
        self.session.add(obj)
        await self.session.flush()
        return obj


async def set_tenant_context(session: AsyncSession, workspace_id: str) -> None:
    """Sets the Postgres session variable read by each tenant table's RLS policy.
    Must be called within the same transaction as the queries it protects.

    Uses set_config(..., is_local=true) rather than `SET LOCAL app.workspace_id = $1`
    because Postgres's SET statement doesn't accept bind parameters at the protocol
    level (asyncpg prepares every statement) — set_config is a normal function call
    and does, while still being transaction-scoped like SET LOCAL."""
    await session.execute(
        text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
        {"workspace_id": workspace_id},
    )
