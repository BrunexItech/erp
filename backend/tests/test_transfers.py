from decimal import Decimal

import pytest

from app.modules.inventory.models import StockMovementType, ValuationMethod
from app.modules.inventory.schemas import ProductCreate, TransferCreate, TransferLineInput, WarehouseCreate
from app.modules.inventory.service import InventoryService


async def _setup_two_warehouses(session, workspace_id, method):
    svc = InventoryService(session, workspace_id)
    wh_a = await svc.create_warehouse(WarehouseCreate(name="Shop A", code="A"))
    wh_b = await svc.create_warehouse(WarehouseCreate(name="Shop B", code="B"))
    product = await svc.create_product(ProductCreate(sku="XFER-1", name="Widget", valuation_method=method))
    return svc, wh_a, wh_b, product


async def test_transfer_moves_stock_between_warehouses(session, workspace_id):
    svc, wh_a, wh_b, product = await _setup_two_warehouses(
        session, workspace_id, ValuationMethod.weighted_average
    )
    await svc.apply_movement(
        product_id=product.id, warehouse_id=wh_a.id, type=StockMovementType.receipt,
        qty_delta=Decimal("20"), unit_cost=Decimal("50"), ref_type="test", ref_id="r1",
    )

    transfer = await svc.transfer_stock(
        TransferCreate(
            from_warehouse_id=wh_a.id, to_warehouse_id=wh_b.id,
            lines=[TransferLineInput(product_id=product.id, qty=Decimal("8"))],
        )
    )
    assert transfer.from_warehouse_id == wh_a.id
    assert transfer.to_warehouse_id == wh_b.id

    stock = {row.warehouse_id: row.qty for row in await svc.warehouse_stock_for_product(product.id)}
    assert stock[wh_a.id] == Decimal("12")
    assert stock[wh_b.id] == Decimal("8")

    await session.refresh(product)
    assert product.stock_qty == Decimal("20"), "company-wide total must be unchanged by a transfer"


async def test_transfer_does_not_reprice_stock(session, workspace_id):
    svc, wh_a, wh_b, product = await _setup_two_warehouses(session, workspace_id, ValuationMethod.fifo)
    await svc.apply_movement(
        product_id=product.id, warehouse_id=wh_a.id, type=StockMovementType.receipt,
        qty_delta=Decimal("5"), unit_cost=Decimal("300"), ref_type="test", ref_id="r1",
    )

    await svc.transfer_stock(
        TransferCreate(
            from_warehouse_id=wh_a.id, to_warehouse_id=wh_b.id,
            lines=[TransferLineInput(product_id=product.id, qty=Decimal("5"))],
        )
    )

    # Selling from the destination warehouse must cost the original 300, not a
    # reset/blended value — a transfer relocates stock, it never reprices it.
    movement = await svc.apply_movement(
        product_id=product.id, warehouse_id=wh_b.id, type=StockMovementType.sale,
        qty_delta=Decimal("-5"), ref_type="test", ref_id="s1",
    )
    assert movement.unit_cost == Decimal("300")


async def test_transfer_rejects_insufficient_stock_at_source_even_if_other_warehouse_has_plenty(
    session, workspace_id
):
    """This is the bug the WarehouseStock table exists to close: before it,
    outflow validation checked Product.stock_qty (the company-wide total), so a
    warehouse with almost nothing could still "successfully" transfer out stock
    that actually lived in a different location."""
    svc, wh_a, wh_b, product = await _setup_two_warehouses(
        session, workspace_id, ValuationMethod.weighted_average
    )
    # All 50 units are in warehouse B; warehouse A has none.
    await svc.apply_movement(
        product_id=product.id, warehouse_id=wh_b.id, type=StockMovementType.receipt,
        qty_delta=Decimal("50"), unit_cost=Decimal("10"), ref_type="test", ref_id="r1",
    )

    with pytest.raises(Exception):
        await svc.transfer_stock(
            TransferCreate(
                from_warehouse_id=wh_a.id, to_warehouse_id=wh_b.id,
                lines=[TransferLineInput(product_id=product.id, qty=Decimal("10"))],
            )
        )

    stock = {row.warehouse_id: row.qty for row in await svc.warehouse_stock_for_product(product.id)}
    assert stock.get(wh_a.id, Decimal("0")) == Decimal("0")
    assert stock[wh_b.id] == Decimal("50")


async def test_transfer_rejects_same_warehouse(session, workspace_id):
    svc, wh_a, _wh_b, product = await _setup_two_warehouses(
        session, workspace_id, ValuationMethod.weighted_average
    )
    with pytest.raises(Exception):
        await svc.transfer_stock(
            TransferCreate(
                from_warehouse_id=wh_a.id, to_warehouse_id=wh_a.id,
                lines=[TransferLineInput(product_id=product.id, qty=Decimal("1"))],
            )
        )
