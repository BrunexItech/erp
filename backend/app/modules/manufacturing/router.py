from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor, get_tenant_session, require_permission
from app.modules.manufacturing.models import BomLine, WorkOrderLine
from app.modules.manufacturing.schemas import (
    BomCreate,
    BomLineOut,
    BomOut,
    WorkOrderComplete,
    WorkOrderCreate,
    WorkOrderOut,
)
from app.modules.manufacturing.service import ManufacturingService

router = APIRouter(prefix="/api/v1/manufacturing", tags=["manufacturing"])

read = require_permission("manufacturing.read")
write = require_permission("manufacturing.write")


@router.get("/boms", response_model=list[BomOut])
async def list_boms(actor: Actor = Depends(read), session: AsyncSession = Depends(get_tenant_session)):
    return sorted(await ManufacturingService(session, actor.workspace_id).boms.list(), key=lambda b: b.name)


@router.post("/boms", response_model=BomOut)
async def create_bom(payload: BomCreate, actor: Actor = Depends(write), session: AsyncSession = Depends(get_tenant_session)):
    return await ManufacturingService(session, actor.workspace_id).create_bom(payload)


@router.get("/boms/{bom_id}")
async def bom_detail(
    bom_id: str,
    qty: Decimal | None = None,
    warehouse_id: str | None = None,
    actor: Actor = Depends(read),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await ManufacturingService(session, actor.workspace_id).bom_detail(bom_id, qty, warehouse_id)


@router.get("/boms/{bom_id}/lines", response_model=list[BomLineOut])
async def bom_lines(bom_id: str, actor: Actor = Depends(read), session: AsyncSession = Depends(get_tenant_session)):
    return await ManufacturingService(session, actor.workspace_id).bom_lines.list(BomLine.bom_id == bom_id)


@router.get("/work-orders", response_model=list[WorkOrderOut])
async def list_work_orders(actor: Actor = Depends(read), session: AsyncSession = Depends(get_tenant_session)):
    orders = await ManufacturingService(session, actor.workspace_id).work_orders.list()
    return sorted(orders, key=lambda o: o.created_at, reverse=True)


@router.post("/work-orders", response_model=WorkOrderOut)
async def create_work_order(
    payload: WorkOrderCreate, actor: Actor = Depends(write), session: AsyncSession = Depends(get_tenant_session)
):
    return await ManufacturingService(session, actor.workspace_id).create_work_order(payload)


@router.get("/work-orders/{work_order_id}/lines")
async def work_order_lines(work_order_id: str, actor: Actor = Depends(read), session: AsyncSession = Depends(get_tenant_session)):
    lines = await ManufacturingService(session, actor.workspace_id).work_order_lines.list(
        WorkOrderLine.work_order_id == work_order_id
    )
    return [{"component_id": l.component_id, "qty_consumed": l.qty_consumed, "cost": l.cost} for l in lines]


@router.post("/work-orders/{work_order_id}/complete", response_model=WorkOrderOut)
async def complete_work_order(
    work_order_id: str,
    payload: WorkOrderComplete,
    actor: Actor = Depends(write),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await ManufacturingService(session, actor.workspace_id).complete_work_order(work_order_id, payload)


@router.post("/work-orders/{work_order_id}/cancel", response_model=WorkOrderOut)
async def cancel_work_order(work_order_id: str, actor: Actor = Depends(write), session: AsyncSession = Depends(get_tenant_session)):
    return await ManufacturingService(session, actor.workspace_id).cancel_work_order(work_order_id)
