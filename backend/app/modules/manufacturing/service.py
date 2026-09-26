from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.db import TenantRepository
from app.core.numbering import next_number
from app.modules.inventory.models import Product, StockMovementType, WarehouseStock
from app.modules.inventory.service import InventoryService
from app.modules.manufacturing.models import (
    BillOfMaterials,
    BomLine,
    WorkOrder,
    WorkOrderLine,
    WorkOrderStatus,
)
from app.modules.manufacturing.schemas import BomCreate, WorkOrderComplete, WorkOrderCreate

ZERO = Decimal("0")


def component_requirement(line: BomLine, bom: BillOfMaterials, qty: Decimal) -> Decimal:
    """Component qty needed to make `qty` finished units, scrap included."""
    per_unit = line.qty / bom.output_qty
    return (per_unit * qty * (1 + line.scrap_pct / 100)).quantize(Decimal("0.0001"))


class ManufacturingService:
    def __init__(self, session: AsyncSession, workspace_id: str):
        self.session = session
        self.workspace_id = workspace_id
        self.boms = TenantRepository(session, workspace_id, BillOfMaterials)
        self.bom_lines = TenantRepository(session, workspace_id, BomLine)
        self.work_orders = TenantRepository(session, workspace_id, WorkOrder)
        self.work_order_lines = TenantRepository(session, workspace_id, WorkOrderLine)
        self.inventory = InventoryService(session, workspace_id)

    async def _product(self, product_id: str) -> Product:
        product = await self.inventory.products.get(product_id)
        if product is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"product not found: {product_id}")
        return product

    async def get_bom(self, bom_id: str) -> BillOfMaterials:
        bom = await self.boms.get(bom_id)
        if bom is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "bill of materials not found")
        return bom

    async def create_bom(self, payload: BomCreate) -> BillOfMaterials:
        product = await self._product(payload.product_id)
        component_ids = [l.component_id for l in payload.lines]
        if payload.product_id in component_ids:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "a product can't be a component of itself")
        if len(set(component_ids)) != len(component_ids):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "each component should appear once")
        for component_id in component_ids:
            await self._product(component_id)

        bom = BillOfMaterials(
            product_id=product.id,
            name=payload.name or f"{product.name} BOM",
            output_qty=payload.output_qty,
            notes=payload.notes,
        )
        await self.boms.add(bom)
        for line in payload.lines:
            await self.bom_lines.add(
                BomLine(bom_id=bom.id, component_id=line.component_id, qty=line.qty, scrap_pct=line.scrap_pct)
            )
        await self.session.commit()
        await self.session.refresh(bom)
        return bom

    async def bom_detail(self, bom_id: str, qty: Decimal | None = None, warehouse_id: str | None = None) -> dict:
        """Lines with current cost roll-up, and — for a given build qty and
        warehouse — what's on hand vs required and how many can be built now."""
        bom = await self.get_bom(bom_id)
        product = await self._product(bom.product_id)
        qty = qty or bom.output_qty
        lines = await self.bom_lines.list(BomLine.bom_id == bom.id)
        rows = []
        unit_material_cost = ZERO
        max_buildable: Decimal | None = None
        for line in lines:
            component = await self._product(line.component_id)
            required = component_requirement(line, bom, qty)
            per_unit_required = component_requirement(line, bom, Decimal("1"))
            unit_material_cost += per_unit_required * component.avg_cost
            on_hand = component.stock_qty
            if warehouse_id:
                stock = await self.inventory.warehouse_stock.list(
                    WarehouseStock.product_id == component.id, WarehouseStock.warehouse_id == warehouse_id
                )
                on_hand = stock[0].qty if stock else ZERO
            buildable = (on_hand / per_unit_required).quantize(Decimal("1"), rounding="ROUND_FLOOR") if per_unit_required else ZERO
            max_buildable = buildable if max_buildable is None else min(max_buildable, buildable)
            rows.append(
                {
                    "id": line.id,
                    "component_id": component.id,
                    "sku": component.sku,
                    "name": component.name,
                    "qty": line.qty,
                    "scrap_pct": line.scrap_pct,
                    "required": required,
                    "on_hand": on_hand,
                    "shortfall": max(required - on_hand, ZERO),
                    "unit_cost": component.avg_cost,
                    "extended_cost": (required * component.avg_cost).quantize(Decimal("0.01")),
                }
            )
        return {
            "id": bom.id,
            "product_id": product.id,
            "product_name": product.name,
            "name": bom.name,
            "output_qty": bom.output_qty,
            "build_qty": qty,
            "lines": rows,
            "unit_material_cost": unit_material_cost.quantize(Decimal("0.0001")),
            "max_buildable": max_buildable or ZERO,
        }

    async def create_work_order(self, payload: WorkOrderCreate) -> WorkOrder:
        bom = await self.get_bom(payload.bom_id)
        if not bom.is_active:
            raise HTTPException(status.HTTP_409_CONFLICT, "bill of materials is inactive")
        if await self.inventory.warehouses.get(payload.warehouse_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "warehouse not found")
        order = WorkOrder(
            wo_no=await next_number(self.session, self.workspace_id, "work_order"),
            bom_id=bom.id,
            product_id=bom.product_id,
            warehouse_id=payload.warehouse_id,
            qty_planned=payload.qty_planned,
            planned_date=payload.planned_date,
            notes=payload.notes,
        )
        await self.work_orders.add(order)
        await self.session.commit()
        await self.session.refresh(order)
        return order

    async def complete_work_order(self, work_order_id: str, payload: WorkOrderComplete) -> WorkOrder:
        """Issues every component from stock at its current cost and receives
        the finished goods at (materials + labour/overhead) / qty — one
        transaction, so a component shortage rolls back the whole build."""
        order = await self.work_orders.get_for_update(work_order_id)
        if order is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "work order not found")
        if order.status != WorkOrderStatus.planned:
            raise HTTPException(status.HTTP_409_CONFLICT, f"work order is {order.status.value}")
        bom = await self.get_bom(order.bom_id)
        qty = payload.qty_produced or order.qty_planned

        material_cost = ZERO
        lines = await self.bom_lines.list(BomLine.bom_id == bom.id)
        for line in sorted(lines, key=lambda l: l.component_id):
            required = component_requirement(line, bom, qty)
            movement = await self.inventory.apply_movement(
                product_id=line.component_id,
                warehouse_id=order.warehouse_id,
                type=StockMovementType.production_issue,
                qty_delta=-required,
                ref_type="work_order",
                ref_id=order.id,
            )
            cost = movement.unit_cost * required
            material_cost += cost
            await self.work_order_lines.add(
                WorkOrderLine(work_order_id=order.id, component_id=line.component_id, qty_consumed=required, cost=cost)
            )

        total = material_cost + payload.conversion_cost
        unit_cost = total / qty
        await self.inventory.apply_movement(
            product_id=order.product_id,
            warehouse_id=order.warehouse_id,
            type=StockMovementType.production_receipt,
            qty_delta=qty,
            unit_cost=unit_cost,
            ref_type="work_order",
            ref_id=order.id,
        )

        order.qty_produced = qty
        order.material_cost = material_cost
        order.conversion_cost = payload.conversion_cost
        order.unit_cost = unit_cost
        order.status = WorkOrderStatus.completed
        order.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)

        await events.publish(
            events.ProductionCompleted(
                workspace_id=self.workspace_id,
                work_order_id=order.id,
                conversion_cost=float(payload.conversion_cost),
                entry_date=date.today(),
            ),
            self.session,
        )
        await self.session.commit()
        await self.session.refresh(order)
        return order

    async def cancel_work_order(self, work_order_id: str) -> WorkOrder:
        order = await self.work_orders.get_for_update(work_order_id)
        if order is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "work order not found")
        if order.status != WorkOrderStatus.planned:
            raise HTTPException(status.HTTP_409_CONFLICT, f"work order is {order.status.value}")
        order.status = WorkOrderStatus.cancelled
        await self.session.commit()
        await self.session.refresh(order)
        return order
