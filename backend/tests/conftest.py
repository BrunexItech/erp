import os
import uuid

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://erp:erp@localhost:5435/erp_test"
)
os.environ.setdefault("TESTING", "true")

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.db import set_tenant_context
from app.modules.accounting.posting import register_subscribers
from app.modules.platform.models import Package, Workspace

register_subscribers()


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Builds a fresh engine (and therefore a fresh physical connection) inside
    THIS test's event loop, rather than reusing the app's module-level engine —
    pytest-asyncio gives each test function its own event loop by default, and an
    engine created in one loop can't safely serve queries from another. NullPool
    means no pooled connection outlives the engine.dispose() below either."""
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    session_local = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with session_local() as s:
        yield s
        await s.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def workspace_id(session: AsyncSession) -> str:
    """Creates a fresh Package + Workspace and sets the RLS tenant context for the
    rest of the test — mirrors what get_actor/get_tenant_session do per-request."""
    package = Package(
        key=f"test-{uuid.uuid4().hex[:8]}",
        name="Test Package",
        modules=["*"],
        limits={},
        is_default=False,
        is_active=True,
    )
    session.add(package)
    await session.flush()

    workspace = Workspace(name="Test Workspace", package_id=package.id)
    session.add(workspace)
    await session.flush()

    await set_tenant_context(session, workspace.id)
    return workspace.id
