from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import TenantModel


class BillOfMaterials(TenantModel):
    """Recipe for making `output_qty` units of a finished product."""

    __tablename__ = "boms"

    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    output_qty: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=1)
    notes: Mapped[str] = mapped_column(String(1000), default="")
    is_active: Mapped[bool] = mapped_column(default=True)


class BomLine(TenantModel):
    __tablename__ = "bom_lines"

    bom_id: Mapped[str] = mapped_column(ForeignKey("boms.id"), index=True)
    component_id: Mapped[str] = mapped_column(ForeignKey("products.id"))
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 4))  # per bom.output_qty
    scrap_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=0)


class WorkOrderStatus(str, enum.Enum):
    planned = "planned"
    completed = "completed"
    cancelled = "cancelled"


class WorkOrder(TenantModel):
    __tablename__ = "work_orders"

    wo_no: Mapped[str] = mapped_column(String(32), index=True)
    bom_id: Mapped[str] = mapped_column(ForeignKey("boms.id"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    warehouse_id: Mapped[str] = mapped_column(ForeignKey("warehouses.id"))
    qty_planned: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    qty_produced: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    status: Mapped[WorkOrderStatus] = mapped_column(default=WorkOrderStatus.planned)
    planned_date: Mapped[date | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    material_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    conversion_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)  # labour + overhead
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=0)
    notes: Mapped[str] = mapped_column(String(1000), default="")


class WorkOrderLine(TenantModel):
    """Component actually consumed, snapshotted at completion."""

    __tablename__ = "work_order_lines"

    work_order_id: Mapped[str] = mapped_column(ForeignKey("work_orders.id"), index=True)
    component_id: Mapped[str] = mapped_column(ForeignKey("products.id"))
    qty_consumed: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    cost: Mapped[Decimal] = mapped_column(Numeric(18, 6))
