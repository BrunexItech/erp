from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.db import TenantRepository
from app.modules.inventory import valuation
from app.modules.inventory.models import (
    Product,
    StockMovement,
    StockLayer,
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

    async def _check_sku_limit(self, adding: int = 1) -> None:
        from app.modules.platform.accounts import workspace_limit

        limit = await workspace_limit(self.session, self.workspace_id, "max_sku")
        if limit is None:
            return
        count = (
            await self.session.execute(
                select(func.count(Product.id)).where(Product.workspace_id == self.workspace_id)
            )
        ).scalar_one()
        if count + adding > limit:
            raise HTTPException(
                status.HTTP_402_PAYMENT_REQUIRED,
                f"your package allows {limit:,} products and you have {count:,} — upgrade to add more",
            )

    async def create_product(self, payload: ProductCreate) -> Product:
        await self._check_sku_limit()
        if await self.products.list(Product.sku == payload.sku):
            raise HTTPException(status.HTTP_409_CONFLICT, f"a product with SKU {payload.sku} already exists")
        product = Product(**payload.model_dump())
        await self.products.add(product)
        await self.session.commit()
        await self.session.refresh(product)
        return product

    async def update_product(self, product_id: str, changes: dict) -> Product:
        product = await self.products.get(product_id)
        if product is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "product not found")
        for key, value in changes.items():
            setattr(product, key, value)
        await self.session.commit()
        await self.session.refresh(product)
        return product

    async def valuation_report(self) -> dict:
        """Stock on hand and what it's worth, per product and per location —
        the figure that must agree with the Inventory account in the ledger."""
        products = sorted(await self.products.list(), key=lambda p: p.sku)
        warehouses = {w.id: w for w in await self.warehouses.list()}
        stock = await self.warehouse_stock.list()
        by_product: dict[str, list[WarehouseStock]] = {}
        for row in stock:
            by_product.setdefault(row.product_id, []).append(row)

        # FIFO products are valued from their remaining cost layers.
        layer_rows = (
            await self.session.execute(
                select(
                    StockLayer.product_id,
                    func.coalesce(func.sum(StockLayer.qty_remaining * StockLayer.unit_cost), 0),
                )
                .where(StockLayer.workspace_id == self.workspace_id)
                .group_by(StockLayer.product_id)
            )
        ).all()
        fifo_value = {pid: Decimal(v) for pid, v in layer_rows}

        rows = []
        total_value = Decimal("0")
        for p in products:
            if p.valuation_method == ValuationMethod.fifo:
                value = fifo_value.get(p.id, Decimal("0"))
            else:
                value = p.stock_qty * p.avg_cost
            total_value += value
            unit_cost = value / p.stock_qty if p.stock_qty else p.avg_cost
            status_label = "out" if p.stock_qty <= 0 else "low" if p.stock_qty <= p.low_stock_threshold else "ok"
            rows.append(
                {
                    "product_id": p.id, "sku": p.sku, "name": p.name, "category": p.category, "unit": p.unit,
                    "is_active": p.is_active, "qty": p.stock_qty, "unit_cost": unit_cost, "value": value,
                    "sale_price": p.sale_price, "retail_value": p.stock_qty * p.sale_price,
                    "low_stock_threshold": p.low_stock_threshold, "status": status_label,
                    "image_url": p.image_url,
                    "locations": [
                        {"warehouse_id": s.warehouse_id, "warehouse": warehouses[s.warehouse_id].name if s.warehouse_id in warehouses else "", "qty": s.qty}
                        for s in by_product.get(p.id, []) if s.qty
                    ],
                }
            )
        active = [r for r in rows if r["is_active"]]
        return {
            "rows": rows,
            "totals": {
                "products": len(active),
                "value": total_value,
                "retail_value": sum((r["retail_value"] for r in active), Decimal("0")),
                "low": sum(1 for r in active if r["status"] == "low"),
                "out": sum(1 for r in active if r["status"] == "out"),
            },
            "categories": sorted({r["category"] for r in rows if r["category"]}),
        }

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

    # ------------------------------------------------------------ stock take

    async def start_count(self, warehouse_id: str, category: str | None, note: str):
        from app.core.numbering import next_number
        from app.modules.inventory.models import StockCount, StockCountLine

        if await self.warehouses.get(warehouse_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "warehouse not found")
        products = [p for p in await self.products.list(Product.is_active.is_(True)) if not category or p.category == category]
        if not products:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "no active products to count")
        on_hand = {s.product_id: s.qty for s in await self.warehouse_stock.list(WarehouseStock.warehouse_id == warehouse_id)}

        count = StockCount(
            workspace_id=self.workspace_id,
            count_no=await next_number(self.session, self.workspace_id, "stock_count"),
            warehouse_id=warehouse_id,
            note=note,
        )
        self.session.add(count)
        await self.session.flush()
        for product in sorted(products, key=lambda p: (p.category, p.name)):
            self.session.add(
                StockCountLine(workspace_id=self.workspace_id, count_id=count.id, product_id=product.id, system_qty=on_hand.get(product.id, Decimal("0")))
            )
        await self.session.commit()
        await self.session.refresh(count)
        return count

    async def _count(self, count_id: str, *, lock: bool = False):
        from app.modules.inventory.models import StockCount

        repo = TenantRepository(self.session, self.workspace_id, StockCount)
        count = await (repo.get_for_update(count_id) if lock else repo.get(count_id))
        if count is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "stock count not found")
        return count

    async def count_detail(self, count_id: str) -> dict:
        from app.modules.inventory.models import StockCountLine

        count = await self._count(count_id)
        lines = await TenantRepository(self.session, self.workspace_id, StockCountLine).list(StockCountLine.count_id == count.id)
        products = {p.id: p for p in await self.products.list()}
        rows = []
        for line in lines:
            product = products.get(line.product_id)
            variance = (line.counted_qty - line.system_qty) if line.counted_qty is not None else None
            rows.append(
                {
                    "id": line.id, "product_id": line.product_id, "sku": product.sku if product else "", "name": product.name if product else "",
                    "category": product.category if product else "", "unit": product.unit if product else "",
                    "system_qty": line.system_qty, "counted_qty": line.counted_qty, "variance": variance,
                    "variance_value": (variance * product.avg_cost) if variance is not None and product else None,
                }
            )
        rows.sort(key=lambda r: (r["category"], r["name"]))
        return {
            "id": count.id, "count_no": count.count_no, "warehouse_id": count.warehouse_id, "status": count.status.value,
            "note": count.note, "created_at": count.created_at, "posted_at": count.posted_at, "variance_value": count.variance_value,
            "counted": sum(1 for r in rows if r["counted_qty"] is not None), "total": len(rows), "lines": rows,
        }

    async def save_count(self, count_id: str, entries: list) -> None:
        from app.modules.inventory.models import StockCountLine, StockCountStatus

        count = await self._count(count_id, lock=True)
        if count.status != StockCountStatus.draft:
            raise HTTPException(status.HTTP_409_CONFLICT, f"this count is {count.status.value}")
        lines = {l.id: l for l in await TenantRepository(self.session, self.workspace_id, StockCountLine).list(StockCountLine.count_id == count.id)}
        for entry in entries:
            line = lines.get(entry.line_id)
            if line is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "count line not found")
            line.counted_qty = entry.counted_qty
        await self.session.commit()

    async def post_count(self, count_id: str) -> dict:
        """Adjusts stock to what was counted. The difference is measured
        against stock *now*, not the snapshot on the sheet, so sales made
        between printing the sheet and posting it aren't mistaken for losses."""
        from datetime import datetime, timezone

        from app.modules.inventory.models import StockCountLine, StockCountStatus

        count = await self._count(count_id, lock=True)
        if count.status != StockCountStatus.draft:
            raise HTTPException(status.HTTP_409_CONFLICT, f"this count is {count.status.value}")
        lines = await TenantRepository(self.session, self.workspace_id, StockCountLine).list(StockCountLine.count_id == count.id)
        counted = [l for l in lines if l.counted_qty is not None]
        if not counted:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "enter at least one counted quantity first")

        variance_value = Decimal("0")
        adjusted = 0
        for line in sorted(counted, key=lambda l: l.product_id):
            stock = await self._get_or_create_warehouse_stock_locked(line.product_id, count.warehouse_id)
            delta = line.counted_qty - stock.qty
            if delta == 0:
                continue
            product = await self.products.get(line.product_id)
            movement = await self.apply_movement(
                product_id=line.product_id,
                warehouse_id=count.warehouse_id,
                type=StockMovementType.adjustment,
                qty_delta=delta,
                unit_cost=product.avg_cost if delta > 0 else None,
                ref_type="stock_count",
                ref_id=count.id,
            )
            line.adjusted_qty = delta
            variance_value += delta * movement.unit_cost
            adjusted += 1
        count.status = StockCountStatus.posted
        count.posted_at = datetime.now(timezone.utc).replace(tzinfo=None)
        count.variance_value = variance_value
        await self.session.commit()
        return {"adjusted_lines": adjusted, "variance_value": variance_value}

    async def cancel_count(self, count_id: str) -> None:
        from app.modules.inventory.models import StockCountStatus

        count = await self._count(count_id, lock=True)
        if count.status != StockCountStatus.draft:
            raise HTTPException(status.HTTP_409_CONFLICT, f"this count is {count.status.value}")
        count.status = StockCountStatus.cancelled
        await self.session.commit()

    async def reorder_report(self) -> list[dict]:
        """Products at or below their reorder level, with a suggested quantity
        that brings stock back to twice that level."""
        rows = []
        for p in await self.products.list(Product.is_active.is_(True)):
            if p.low_stock_threshold <= 0 or p.stock_qty > p.low_stock_threshold:
                continue
            rows.append(
                {
                    "product_id": p.id, "sku": p.sku, "name": p.name, "category": p.category, "unit": p.unit,
                    "on_hand": p.stock_qty, "reorder_level": p.low_stock_threshold,
                    "suggested_qty": max(p.low_stock_threshold * 2 - p.stock_qty, p.low_stock_threshold),
                    "last_cost": p.avg_cost,
                }
            )
        return sorted(rows, key=lambda r: (r["on_hand"] > 0, r["name"]))
