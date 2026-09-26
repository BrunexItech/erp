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
