from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.modules.accounting.service import AccountingService
from app.modules.inventory import valuation
from app.modules.inventory.schemas import ProductCreate, WarehouseCreate
from app.modules.inventory.service import InventoryService
from app.modules.manufacturing.models import WorkOrderStatus
from app.modules.manufacturing.schemas import BomCreate, BomLineInput, WorkOrderComplete, WorkOrderCreate
from app.modules.manufacturing.service import ManufacturingService


async def _bakery(session, workspace_id):
    """A bakery: 1 batch of 10 loaves = 5kg flour (10% scrap) + 0.1kg yeast."""
    await AccountingService(session, workspace_id).seed_default_accounts()
    inventory = InventoryService(session, workspace_id)
    kitchen = await inventory.create_warehouse(WarehouseCreate(name="Kitchen", code="KIT"))
    flour = await inventory.create_product(ProductCreate(sku="FLOUR", name="Flour (kg)"))
    yeast = await inventory.create_product(ProductCreate(sku="YEAST", name="Yeast (kg)"))
    loaf = await inventory.create_product(ProductCreate(sku="LOAF", name="Bread loaf"))
    for product, qty, cost in ((flour, "100", "80"), (yeast, "2", "900")):
        await inventory.record_adjustment(
            product_id=product.id, warehouse_id=kitchen.id, qty_delta=Decimal(qty),
            unit_cost=Decimal(cost), reason="opening", is_opening=True,
        )
    mfg = ManufacturingService(session, workspace_id)
    bom = await mfg.create_bom(
        BomCreate(
            product_id=loaf.id, output_qty=Decimal("10"),
            lines=[
                BomLineInput(component_id=flour.id, qty=Decimal("5"), scrap_pct=Decimal("10")),
                BomLineInput(component_id=yeast.id, qty=Decimal("0.1")),
            ],
        )
    )
    return mfg, inventory, kitchen, flour, yeast, loaf, bom


async def test_bom_rollup_and_buildable(session, workspace_id):
    mfg, _, kitchen, *_rest, bom = await _bakery(session, workspace_id)
    detail = await mfg.bom_detail(bom.id, Decimal("40"), kitchen.id)
    # per loaf: 0.55kg flour x 80 + 0.01kg yeast x 900 = 44 + 9
    assert detail["unit_material_cost"] == Decimal("53.0000")
    flour_row = next(r for r in detail["lines"] if r["sku"] == "FLOUR")
    assert flour_row["required"] == Decimal("22.0000")
    # flour limits to floor(100 / 0.55) = 181; yeast to 2 / 0.01 = 200
    assert detail["max_buildable"] == Decimal("181")


async def test_work_order_consumes_components_and_costs_finished_goods(session, workspace_id):
    mfg, inventory, kitchen, flour, yeast, loaf, bom = await _bakery(session, workspace_id)
    accounting = AccountingService(session, workspace_id)

    order = await mfg.create_work_order(WorkOrderCreate(bom_id=bom.id, warehouse_id=kitchen.id, qty_planned=Decimal("40")))
    assert order.wo_no.startswith("WO-")
    done = await mfg.complete_work_order(order.id, WorkOrderComplete(conversion_cost=Decimal("400")))

    assert done.status == WorkOrderStatus.completed
    assert done.material_cost == Decimal("2120.00")  # 40 x 53
    assert done.unit_cost == Decimal("63.000000")  # (2,120 + 400) / 40

    for product, expected in ((flour, "78"), (yeast, "1.6"), (loaf, "40")):
        await session.refresh(product)
        assert product.stock_qty == Decimal(expected)

    # Only the capitalised labour/overhead hits the GL; materials just move within Inventory.
    inventory_value = sum(
        [await valuation.current_value(session, workspace_id, p, kitchen.id) for p in (flour, yeast, loaf)],
        Decimal("0"),
    )
    assert await accounting.balance_for_key("INVENTORY") == inventory_value == Decimal("10200")  # 9,800 + 400

    with pytest.raises(HTTPException):
        await mfg.complete_work_order(order.id, WorkOrderComplete())


async def test_shortage_rolls_back_the_whole_build(session, workspace_id):
    mfg, _, kitchen, flour, yeast, loaf, bom = await _bakery(session, workspace_id)
    order = await mfg.create_work_order(WorkOrderCreate(bom_id=bom.id, warehouse_id=kitchen.id, qty_planned=Decimal("500")))
    with pytest.raises(HTTPException):
        await mfg.complete_work_order(order.id, WorkOrderComplete())
    await mfg.session.rollback()
    await session.refresh(flour)
    assert flour.stock_qty == Decimal("100")
