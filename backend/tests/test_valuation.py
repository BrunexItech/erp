import asyncio
import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.db import set_tenant_context
from app.modules.inventory.models import StockMovementType, ValuationMethod
from app.modules.inventory.schemas import ProductCreate, WarehouseCreate
from app.modules.inventory.service import InventoryService
from app.modules.inventory.valuation import InsufficientStockError
from app.modules.platform.models import Package, Workspace


async def _setup(session: AsyncSession, workspace_id: str, method: ValuationMethod):
    svc = InventoryService(session, workspace_id)
    warehouse = await svc.create_warehouse(WarehouseCreate(name="Main", code="MAIN"))
    product = await svc.create_product(
        ProductCreate(sku="SKU-1", name="Widget", valuation_method=method)
    )
    return svc, warehouse, product


async def test_weighted_average_recomputes_on_each_receipt(session, workspace_id):
    svc, warehouse, product = await _setup(
        session, workspace_id, ValuationMethod.weighted_average
    )

    await svc.apply_movement(
        product_id=product.id, warehouse_id=warehouse.id,
        type=StockMovementType.receipt, qty_delta=Decimal("10"),
        unit_cost=Decimal("100"), ref_type="test", ref_id="r1",
    )
    await session.refresh(product)
    assert product.avg_cost == Decimal("100")

    # Second receipt at a different cost: avg = (10*100 + 10*200) / 20 = 150
    await svc.apply_movement(
        product_id=product.id, warehouse_id=warehouse.id,
        type=StockMovementType.receipt, qty_delta=Decimal("10"),
        unit_cost=Decimal("200"), ref_type="test", ref_id="r2",
    )
    await session.refresh(product)
    assert product.avg_cost == Decimal("150")
    assert product.stock_qty == Decimal("20")

    # Issuing stock does NOT change avg_cost, only quantity
    movement = await svc.apply_movement(
        product_id=product.id, warehouse_id=warehouse.id,
        type=StockMovementType.sale, qty_delta=Decimal("-5"),
        ref_type="test", ref_id="s1",
    )
    await session.refresh(product)
    assert product.avg_cost == Decimal("150")
    assert product.stock_qty == Decimal("15")
    assert movement.unit_cost == Decimal("150")


async def test_fifo_consumes_oldest_layer_first_and_can_straddle_layers(session, workspace_id):
    svc, warehouse, product = await _setup(session, workspace_id, ValuationMethod.fifo)

    # Layer 1: 5 units @ 100. Layer 2: 5 units @ 200.
    await svc.apply_movement(
        product_id=product.id, warehouse_id=warehouse.id,
        type=StockMovementType.receipt, qty_delta=Decimal("5"),
        unit_cost=Decimal("100"), ref_type="test", ref_id="r1",
    )
    await svc.apply_movement(
        product_id=product.id, warehouse_id=warehouse.id,
        type=StockMovementType.receipt, qty_delta=Decimal("5"),
        unit_cost=Decimal("200"), ref_type="test", ref_id="r2",
    )

    # Issue 3 units: should draw entirely from layer 1 (cheapest/oldest) at cost 100.
    m1 = await svc.apply_movement(
        product_id=product.id, warehouse_id=warehouse.id,
        type=StockMovementType.sale, qty_delta=Decimal("-3"),
        ref_type="test", ref_id="s1",
    )
    assert m1.unit_cost == Decimal("100")

    # Issue 4 units: 2 remaining from layer 1 @ 100 + 2 from layer 2 @ 200
    # blended cost = (2*100 + 2*200) / 4 = 150
    m2 = await svc.apply_movement(
        product_id=product.id, warehouse_id=warehouse.id,
        type=StockMovementType.sale, qty_delta=Decimal("-4"),
        ref_type="test", ref_id="s2",
    )
    assert m2.unit_cost == Decimal("150")

    await session.refresh(product)
    assert product.stock_qty == Decimal("3")  # 10 received - 3 - 4


async def test_insufficient_stock_raises_and_does_not_mutate(session, workspace_id):
    svc, warehouse, product = await _setup(
        session, workspace_id, ValuationMethod.weighted_average
    )
    await svc.apply_movement(
        product_id=product.id, warehouse_id=warehouse.id,
        type=StockMovementType.receipt, qty_delta=Decimal("5"),
        unit_cost=Decimal("50"), ref_type="test", ref_id="r1",
    )

    with pytest.raises(Exception):
        await svc.apply_movement(
            product_id=product.id, warehouse_id=warehouse.id,
            type=StockMovementType.sale, qty_delta=Decimal("-100"),
            ref_type="test", ref_id="s1",
        )

    await session.refresh(product)
    assert product.stock_qty == Decimal("5")  # unchanged


async def test_concurrent_apply_movement_serializes_via_row_lock():
    """Two overlapping transactions both try to consume from a stock of 10 units,
    one asking for 6 and the other for 6 (total 12 > 10 available). The row lock
    in apply_movement (get_for_update) must serialize them so the second one sees
    the first one's committed decrement and fails with InsufficientStockError —
    never both succeeding and over-selling.
    """
    # A local engine, scoped to this test's event loop (see the `session` fixture
    # in conftest.py for why we don't reuse the app's module-level engine here).
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    session_local = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

    async with session_local() as setup_session:
        package = Package(
            key=f"conc-test-{uuid.uuid4().hex[:8]}", name="Concurrency Test", modules=["*"], limits={}
        )
        setup_session.add(package)
        await setup_session.flush()
        workspace = Workspace(name="Concurrency WS", package_id=package.id)
        setup_session.add(workspace)
        await setup_session.flush()

        await set_tenant_context(setup_session, workspace.id)
        svc = InventoryService(setup_session, workspace.id)
        warehouse = await svc.create_warehouse(WarehouseCreate(name="Main", code="MAIN"))
        product = await svc.create_product(
            ProductCreate(sku="CONC-1", name="Widget", valuation_method=ValuationMethod.weighted_average)
        )
        await svc.apply_movement(
            product_id=product.id, warehouse_id=warehouse.id,
            type=StockMovementType.receipt, qty_delta=Decimal("10"),
            unit_cost=Decimal("10"), ref_type="test", ref_id="r1",
        )
        await setup_session.commit()

        workspace_id = workspace.id
        product_id = product.id
        warehouse_id = warehouse.id

    async def sell(qty: Decimal):
        async with session_local() as s:
            await set_tenant_context(s, workspace_id)
            svc = InventoryService(s, workspace_id)
            try:
                await svc.apply_movement(
                    product_id=product_id, warehouse_id=warehouse_id,
                    type=StockMovementType.sale, qty_delta=-qty,
                    ref_type="test", ref_id="concurrent",
                )
                await s.commit()
                return "ok"
            except (InsufficientStockError, Exception):
                await s.rollback()
                return "failed"

    try:
        results = await asyncio.gather(sell(Decimal("6")), sell(Decimal("6")))
        assert sorted(results) == ["failed", "ok"], (
            "exactly one of the two overlapping 6-unit sales against 10 in stock must fail"
        )
    finally:
        await engine.dispose()
