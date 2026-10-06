import uuid

from app.core.db import set_tenant_context
from app.modules.inventory.schemas import ProductCreate
from app.modules.inventory.service import InventoryService
from app.modules.platform.models import Package, Workspace


async def test_repository_never_returns_another_workspaces_rows(session, workspace_id):
    inventory_a = InventoryService(session, workspace_id)
    await inventory_a.create_product(ProductCreate(sku="A-1", name="Only in workspace A"))

    # Second workspace, different tenant context in the SAME session/transaction.
    package_b = Package(key=f"b-{uuid.uuid4().hex[:8]}", name="B", modules=["*"], limits={})
    session.add(package_b)
    await session.flush()
    workspace_b = Workspace(name="Workspace B", package_id=package_b.id)
    session.add(workspace_b)
    await session.flush()
    await set_tenant_context(session, workspace_b.id)

    inventory_b = InventoryService(session, workspace_b.id)
    products_in_b = await inventory_b.products.list()

    assert products_in_b == [], (
        "workspace B must not see workspace A's products — RLS + TenantRepository "
        "scoping failed"
    )


async def test_get_for_id_from_another_workspace_returns_none(session, workspace_id):
    inventory_a = InventoryService(session, workspace_id)
    product = await inventory_a.create_product(ProductCreate(sku="A-2", name="A only"))

    package_b = Package(key=f"c-{uuid.uuid4().hex[:8]}", name="C", modules=["*"], limits={})
    session.add(package_b)
    await session.flush()
    workspace_b = Workspace(name="Workspace C", package_id=package_b.id)
    session.add(workspace_b)
    await session.flush()
    await set_tenant_context(session, workspace_b.id)

    inventory_b = InventoryService(session, workspace_b.id)
    fetched = await inventory_b.products.get(product.id)

    assert fetched is None, "fetching workspace A's product id from workspace B must return None"


async def test_database_itself_enforces_isolation_without_the_repository(session, workspace_id):
    """The real second line of defence: a raw query that forgets to filter by
    workspace must STILL see only its own tenant's rows, be unable to write
    into another tenant, and see nothing at all with no tenant set — because
    Postgres Row-Level Security enforces it, not our Python."""
    import pytest
    from sqlalchemy import select, text
    from sqlalchemy.exc import DBAPIError

    from app.modules.inventory.models import Product

    assert (await session.execute(text("SELECT current_user"))).scalar_one() == "erp_app"

    await InventoryService(session, workspace_id).create_product(ProductCreate(sku="RLS-A", name="Tenant A product"))

    package = Package(key=f"rls-{uuid.uuid4().hex[:8]}", name="RLS", modules=["*"], limits={})
    session.add(package)
    await session.flush()
    other = Workspace(name="Tenant B", package_id=package.id)
    session.add(other)
    await session.commit()
    other_id = other.id

    # Unfiltered on purpose — no TenantRepository, no WHERE workspace_id.
    await set_tenant_context(session, workspace_id)
    assert [p.sku for p in (await session.execute(select(Product))).scalars()] == ["RLS-A"]

    await set_tenant_context(session, other_id)
    assert (await session.execute(select(Product))).scalars().all() == []
    # ...and the scoping survives a commit (it is re-applied per transaction).
    await session.commit()
    assert (await session.execute(select(Product))).scalars().all() == []

    # Tenant B cannot plant a row in tenant A.
    session.add(Product(workspace_id=workspace_id, sku="SMUGGLED", name="x"))
    with pytest.raises(DBAPIError):
        await session.flush()
    await session.rollback()

    # No tenant at all: fail closed.
    session.info.pop("workspace_id")
    await session.commit()
    assert (await session.execute(select(Product))).scalars().all() == []
