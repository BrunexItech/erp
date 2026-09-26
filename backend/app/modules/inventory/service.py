from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.db import TenantRepository
from app.modules.inventory import valuation
from app.modules.inventory.models import (
    Product,
    StockMovement,
    StockMovementType,
    StockTransfer,
    StockTransferLine,
    ValuationMethod,
    Warehouse,
    WarehouseStock,
)
from app.modules.inventory.schemas import ProductCreate, TransferCreate, WarehouseCreate
from app.modules.inventory.valuation import InsufficientStockError


class InventoryService:
    def __init__(self, session: AsyncSession, workspace_id: str):
        self.session = session
        self.workspace_id = workspace_id
        self.products = TenantRepository(session, workspace_id, Product)
        self.warehouses = TenantRepository(session, workspace_id, Warehouse)
        self.movements = TenantRepository(session, workspace_id, StockMovement)
        self.warehouse_stock = TenantRepository(session, workspace_id, WarehouseStock)
        self.transfers = TenantRepository(session, workspace_id, StockTransfer)
        self.transfer_lines = TenantRepository(session, workspace_id, StockTransferLine)

    async def _get_or_create_warehouse_stock_locked(
        self, product_id: str, warehouse_id: str
    ) -> WarehouseStock:
        """Row-locks the (product, warehouse) stock counter, creating it at qty=0
        if this is the first movement ever for that combination."""
        stmt = (
            select(WarehouseStock)
            .where(
                WarehouseStock.workspace_id == self.workspace_id,
                WarehouseStock.product_id == product_id,
                WarehouseStock.warehouse_id == warehouse_id,
            )
            .with_for_update()
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is not None:
            return row

        row = WarehouseStock(product_id=product_id, warehouse_id=warehouse_id, qty=Decimal("0"))
        try:
            async with self.session.begin_nested():
                await self.warehouse_stock.add(row)
        except IntegrityError:
            # Lost a race with a concurrent first-movement insert — the row now
            # exists, just lock and return it.
            row = (await self.session.execute(stmt)).scalar_one()
        return row

    async def warehouse_stock_for_product(self, product_id: str) -> list[WarehouseStock]:
        return list(await self.warehouse_stock.list(WarehouseStock.product_id == product_id))

    async def create_product(self, payload: ProductCreate) -> Product:
        product = Product(**payload.model_dump())
        await self.products.add(product)
        await self.session.commit()
        await self.session.refresh(product)
        return product

    async def create_warehouse(self, payload: WarehouseCreate) -> Warehouse:
        warehouse = Warehouse(**payload.model_dump())
        await self.warehouses.add(warehouse)
        await self.session.commit()
        await self.session.refresh(warehouse)
        return warehouse

    async def apply_movement(
        self,
        *,
        product_id: str,
        warehouse_id: str,
        type: StockMovementType,
        qty_delta: Decimal,
        ref_type: str,
        ref_id: str,
        unit_cost: Decimal | None = None,
    ) -> StockMovement:
        """The single mutation point for stock quantity and cost. Row-locks the
        product, updates qty/cost via the valuation engine, writes one append-only
        ledger row, and publishes StockMovementApplied — all in one transaction.
        Never call anything else to change Product.stock_qty/avg_cost or
        StockLayer.qty_remaining.
        """
        product = await self.products.get_for_update(product_id)
        if product is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "product not found")

        warehouse_stock = await self._get_or_create_warehouse_stock_locked(product_id, warehouse_id)

        movement_id = str(uuid4())
        old_qty = product.stock_qty

        if qty_delta < 0:
            if warehouse_stock.qty < -qty_delta:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"insufficient stock at this location: have {warehouse_stock.qty}, "
                    f"need {-qty_delta}",
                )
            try:
                cost = await valuation.consume(
                    self.session, self.workspace_id, product, warehouse_id, -qty_delta
                )
            except InsufficientStockError as exc:
                raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        elif qty_delta > 0:
            if unit_cost is None:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST, "unit_cost required for inbound movement"
                )
            cost = unit_cost
        else:
            cost = Decimal("0")

        product.stock_qty += qty_delta
        warehouse_stock.qty += qty_delta

        # Insert the movement row now (value_after is a placeholder, patched below)
        # so that if this is a FIFO receipt, the StockLayer we're about to create
        # has a real StockMovement row to satisfy its source_movement_id FK.
        movement = StockMovement(
            id=movement_id,
            workspace_id=self.workspace_id,
            product_id=product_id,
            warehouse_id=warehouse_id,
            type=type,
            qty_delta=qty_delta,
            unit_cost=cost,
            balance_after=warehouse_stock.qty,
            value_after=Decimal("0"),
            ref_type=ref_type,
            ref_id=ref_id,
        )
        self.session.add(movement)
        await self.session.flush()

        if qty_delta > 0:
            await valuation.receive(
                self.session,
                self.workspace_id,
                product,
                warehouse_id,
                qty_delta,
                unit_cost,
                movement_id,
                old_qty,
            )

        movement.value_after = await valuation.current_value(
            self.session, self.workspace_id, product, warehouse_id
        )
        await self.session.flush()

        await events.publish(
            events.StockMovementApplied(
                workspace_id=self.workspace_id,
                movement_id=movement.id,
                product_id=product_id,
                type=type.value,
                qty_delta=float(qty_delta),
                unit_cost=float(cost),
            ),
            self.session,
        )
        return movement

    async def record_adjustment(
        self,
        *,
        product_id: str,
        warehouse_id: str,
        qty_delta: Decimal,
        unit_cost: Decimal | None,
        reason: str,
        is_opening: bool = False,
    ) -> StockMovement:
        """Standalone manual correction (stock count variance, damage, etc.) — the
        only caller of apply_movement that commits on its own, since it isn't part
        of a larger multi-step transaction like a sale or goods receipt."""
        movement = await self.apply_movement(
            product_id=product_id,
            warehouse_id=warehouse_id,
            # Opening stock is capital brought into the business (posts against
            # Opening Balance Equity); an adjustment is a count variance (posts
            # to Inventory Adjustments & Shrinkage).
            type=StockMovementType.opening if is_opening else StockMovementType.adjustment,
            qty_delta=qty_delta,
            unit_cost=unit_cost,
            ref_type="manual_adjustment",
            ref_id=(reason or "unspecified")[:36],
        )
        await self.session.commit()
        await self.session.refresh(movement)
        return movement

    async def list_low_stock(self) -> list[Product]:
        return list(
            await self.products.list(Product.stock_qty <= Product.low_stock_threshold)
        )

    async def transfer_stock(self, payload: TransferCreate) -> StockTransfer:
        """Moves stock from one shop/warehouse to another. Each line becomes a
        paired 'transfer out' / 'transfer in' StockMovement at the SAME cost (a
        transfer relocates stock, it never reprices it) — both tagged with this
        StockTransfer's id, so the whole movement is auditable end to end from
        either warehouse's movement history.

        Lines are processed sorted by product_id (deterministic order), same
        deadlock-avoidance pattern as sales/purchasing.
        """
        if payload.from_warehouse_id == payload.to_warehouse_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "source and destination warehouse must differ"
            )

        transfer = StockTransfer(
            from_warehouse_id=payload.from_warehouse_id,
            to_warehouse_id=payload.to_warehouse_id,
            note=payload.note,
        )
        await self.transfers.add(transfer)
        await self.session.flush()

        for line in sorted(payload.lines, key=lambda l: l.product_id):
            out_movement = await self.apply_movement(
                product_id=line.product_id,
                warehouse_id=payload.from_warehouse_id,
                type=StockMovementType.transfer,
                qty_delta=-line.qty,
                ref_type="stock_transfer",
                ref_id=transfer.id,
            )
            await self.apply_movement(
                product_id=line.product_id,
                warehouse_id=payload.to_warehouse_id,
                type=StockMovementType.transfer,
                qty_delta=line.qty,
                unit_cost=out_movement.unit_cost,
                ref_type="stock_transfer",
                ref_id=transfer.id,
            )
            await self.transfer_lines.add(
                StockTransferLine(
                    transfer_id=transfer.id,
                    product_id=line.product_id,
                    qty=line.qty,
                    unit_cost=out_movement.unit_cost,
                )
            )

        await self.session.commit()
        await self.session.refresh(transfer)
        return transfer
