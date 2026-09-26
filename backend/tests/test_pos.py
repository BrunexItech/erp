from decimal import Decimal

import pytest

from app.modules.accounting.service import AccountingService
from app.modules.inventory.models import StockMovementType, ValuationMethod
from app.modules.inventory.schemas import ProductCreate, WarehouseCreate
from app.modules.inventory.service import InventoryService
from app.modules.sales.models import InvoiceStatus
from app.modules.sales.schemas import PosCheckoutLine, PosCheckoutRequest
from app.modules.sales.service import SalesService


async def test_pos_checkout_is_instant_and_fully_paid(session, workspace_id):
    await AccountingService(session, workspace_id).seed_default_accounts()

    inventory = InventoryService(session, workspace_id)
    warehouse = await inventory.create_warehouse(WarehouseCreate(name="Till 1", code="T1"))
    product = await inventory.create_product(
        ProductCreate(sku="POS-1", name="Widget", valuation_method=ValuationMethod.weighted_average)
    )
    await inventory.apply_movement(
        product_id=product.id, warehouse_id=warehouse.id, type=StockMovementType.receipt,
        qty_delta=Decimal("10"), unit_cost=Decimal("50"), ref_type="test", ref_id="r1",
    )

    sales = SalesService(session, workspace_id)
    invoice, total_cogs, _ = await sales.pos_checkout(
        PosCheckoutRequest(
            warehouse_id=warehouse.id,
            lines=[PosCheckoutLine(product_id=product.id, qty=Decimal("3"), unit_price=Decimal("100"))],
        )
    )

    assert invoice.status == InvoiceStatus.paid, "a POS sale must be paid in full immediately, not left as a draft"
    assert invoice.total == Decimal("300")
    assert total_cogs == Decimal("150")  # 3 * 50

    await session.refresh(product)
    assert product.stock_qty == Decimal("7")

    balance = await sales.customer_balance(invoice.party_id)
    assert balance == Decimal("0"), "walk-in customer must have zero outstanding balance after a paid POS sale"


async def test_pos_checkout_reuses_the_same_walk_in_customer(session, workspace_id):
    await AccountingService(session, workspace_id).seed_default_accounts()

    inventory = InventoryService(session, workspace_id)
    warehouse = await inventory.create_warehouse(WarehouseCreate(name="Till 1", code="T1"))
    product = await inventory.create_product(
        ProductCreate(sku="POS-2", name="Widget", valuation_method=ValuationMethod.weighted_average)
    )
    await inventory.apply_movement(
        product_id=product.id, warehouse_id=warehouse.id, type=StockMovementType.receipt,
        qty_delta=Decimal("10"), unit_cost=Decimal("20"), ref_type="test", ref_id="r1",
    )

    sales = SalesService(session, workspace_id)
    invoice_a, _, _ = await sales.pos_checkout(
        PosCheckoutRequest(
            warehouse_id=warehouse.id,
            lines=[PosCheckoutLine(product_id=product.id, qty=Decimal("1"), unit_price=Decimal("50"))],
        )
    )
    invoice_b, _, _ = await sales.pos_checkout(
        PosCheckoutRequest(
            warehouse_id=warehouse.id,
            lines=[PosCheckoutLine(product_id=product.id, qty=Decimal("1"), unit_price=Decimal("50"))],
        )
    )

    assert invoice_a.party_id == invoice_b.party_id, "two walk-in sales must bill the same reused party"


async def test_pos_checkout_rolls_back_atomically_on_insufficient_stock(session, workspace_id):
    await AccountingService(session, workspace_id).seed_default_accounts()

    inventory = InventoryService(session, workspace_id)
    warehouse = await inventory.create_warehouse(WarehouseCreate(name="Till 1", code="T1"))
    product = await inventory.create_product(
        ProductCreate(sku="POS-3", name="Widget", valuation_method=ValuationMethod.weighted_average)
    )
    await inventory.apply_movement(
        product_id=product.id, warehouse_id=warehouse.id, type=StockMovementType.receipt,
        qty_delta=Decimal("2"), unit_cost=Decimal("20"), ref_type="test", ref_id="r1",
    )

    sales = SalesService(session, workspace_id)
    with pytest.raises(Exception):
        await sales.pos_checkout(
            PosCheckoutRequest(
                warehouse_id=warehouse.id,
                lines=[PosCheckoutLine(product_id=product.id, qty=Decimal("999"), unit_price=Decimal("50"))],
            )
        )

    # In production, an unhandled exception ends the request and the session's
    # context manager rolls back on close() — simulate that same boundary here,
    # since pos_checkout never got to its own commit().
    await session.rollback()

    orders = await sales.orders.list()
    assert orders == [], "a failed POS checkout must not leave a half-created order behind"
