from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.modules.manufacturing.models import WorkOrderStatus


class BomLineInput(BaseModel):
    component_id: str
    qty: Decimal = Field(gt=0)
    scrap_pct: Decimal = Field(default=Decimal("0"), ge=0, lt=100)


class BomCreate(BaseModel):
    product_id: str
    name: str = ""
    output_qty: Decimal = Field(default=Decimal("1"), gt=0)
    notes: str = ""
    lines: list[BomLineInput] = Field(min_length=1)


class BomLineOut(BaseModel):
    id: str
    component_id: str
    qty: Decimal
    scrap_pct: Decimal

    class Config:
        from_attributes = True


class BomOut(BaseModel):
    id: str
    product_id: str
    name: str
    output_qty: Decimal
    notes: str
    is_active: bool

    class Config:
        from_attributes = True


class WorkOrderCreate(BaseModel):
    bom_id: str
    warehouse_id: str
    qty_planned: Decimal = Field(gt=0)
    planned_date: date | None = None
    notes: str = ""


class WorkOrderComplete(BaseModel):
    qty_produced: Decimal | None = Field(default=None, gt=0)  # defaults to qty_planned
    conversion_cost: Decimal = Field(default=Decimal("0"), ge=0)  # labour + overhead to capitalise


class WorkOrderOut(BaseModel):
    id: str
    wo_no: str
    bom_id: str
    product_id: str
    warehouse_id: str
    qty_planned: Decimal
    qty_produced: Decimal
    status: WorkOrderStatus
    planned_date: date | None
    completed_at: datetime | None
    material_cost: Decimal
    conversion_cost: Decimal
    unit_cost: Decimal
    notes: str

    class Config:
        from_attributes = True
