"""Stock valuation engine — the piece Stoka never had. Two methods, chosen per
product (Product.valuation_method):

- weighted_average: Product.avg_cost is recomputed on every receipt; COGS on issue
  is qty * avg_cost (cost doesn't change on an outflow).
- fifo: each receipt opens a StockLayer; an issue consumes layers oldest-first and
  its cost is the blended cost of whatever layers it drew from (a single issue can
  straddle several layers at different unit costs).

Both are called only from inventory.service.apply_movement(), never directly, so the
product row is always already locked (SELECT ... FOR UPDATE) by the time these run.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.inventory.models import Product, StockLayer, ValuationMethod


class InsufficientStockError(Exception):
    def __init__(self, product_id: str, short_by: Decimal):
        self.product_id = product_id
        self.short_by = short_by
        super().__init__(f"insufficient stock for product {product_id}: short by {short_by}")


async def receive(
    session: AsyncSession,
    workspace_id: str,
    product: Product,
    warehouse_id: str,
    qty: Decimal,
    unit_cost: Decimal,
    movement_id: str,
    old_qty: Decimal,
) -> Decimal:
    """Records an inflow. Returns the cost to record on the StockMovement (the
    received unit_cost itself).

    Called AFTER the StockMovement row has already been flushed (its id is
    movement_id) — the FIFO branch's StockLayer.source_movement_id is a real FK
    and needs the parent row to exist first. By that point product.stock_qty has
    already been incremented by the caller, so old_qty (the pre-receipt quantity)
    is passed in explicitly rather than read off product.stock_qty.
    """
    if product.valuation_method == ValuationMethod.weighted_average:
        old_avg = product.avg_cost
        new_qty = old_qty + qty
        product.avg_cost = unit_cost if old_qty <= 0 else (
            (old_qty * old_avg + qty * unit_cost) / new_qty
        )
    else:  # FIFO
        session.add(
            StockLayer(
                workspace_id=workspace_id,
                product_id=product.id,
                warehouse_id=warehouse_id,
                qty_received=qty,
                qty_remaining=qty,
                unit_cost=unit_cost,
                source_movement_id=movement_id,
            )
        )
        await session.flush()
    return unit_cost


async def consume(
    session: AsyncSession,
    workspace_id: str,
    product: Product,
    warehouse_id: str,
    qty: Decimal,
) -> Decimal:
    """Records an outflow. Returns the blended unit cost to record as COGS for
    this movement. Raises InsufficientStockError without mutating anything if
    there isn't enough stock/layer quantity to cover it."""
    if product.valuation_method == ValuationMethod.weighted_average:
        if product.stock_qty < qty:
            raise InsufficientStockError(product.id, qty - product.stock_qty)
        return product.avg_cost

    # FIFO: walk layers oldest-first, locking them so concurrent issues can't
    # double-spend the same layer quantity.
    stmt = (
        select(StockLayer)
        .where(
            StockLayer.workspace_id == workspace_id,
            StockLayer.product_id == product.id,
            StockLayer.warehouse_id == warehouse_id,
            StockLayer.qty_remaining > 0,
        )
        .order_by(StockLayer.seq)
        .with_for_update()
    )
    layers = (await session.execute(stmt)).scalars().all()

    remaining = qty
    total_cost = Decimal("0")
    for layer in layers:
        if remaining <= 0:
            break
        take = min(layer.qty_remaining, remaining)
        layer.qty_remaining -= take
        total_cost += take * layer.unit_cost
        remaining -= take

    if remaining > 0:
        raise InsufficientStockError(product.id, remaining)

    return total_cost / qty


async def current_value(
    session: AsyncSession, workspace_id: str, product: Product, warehouse_id: str
) -> Decimal:
    """Total inventory value on hand for this product — what the accounting
    module's Inventory GL account balance must reconcile against."""
    if product.valuation_method == ValuationMethod.weighted_average:
        return product.stock_qty * product.avg_cost

    stmt = select(func.coalesce(func.sum(StockLayer.qty_remaining * StockLayer.unit_cost), 0)).where(
        StockLayer.workspace_id == workspace_id,
        StockLayer.product_id == product.id,
        StockLayer.warehouse_id == warehouse_id,
    )
    result = (await session.execute(stmt)).scalar_one()
    return Decimal(result)
