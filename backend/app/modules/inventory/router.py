from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor, get_actor, get_tenant_session
from app.modules.inventory.models import WarehouseStock
from app.modules.inventory.schemas import (
    ProductCreate,
    ProductOut,
    StockAdjustmentRequest,
    StockMovementOut,
    StockTransferOut,
    TransferCreate,
    WarehouseCreate,
    WarehouseOut,
    WarehouseStockOut,
)
from app.modules.inventory.service import InventoryService

router = APIRouter(prefix="/api/v1/inventory", tags=["inventory"])


@router.post("/products", response_model=ProductOut)
async def create_product(
    payload: ProductCreate,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await InventoryService(session, actor.workspace_id).create_product(payload)


@router.get("/products", response_model=list[ProductOut])
async def list_products(
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await InventoryService(session, actor.workspace_id).products.list()


@router.get("/products/low-stock", response_model=list[ProductOut])
async def low_stock(
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await InventoryService(session, actor.workspace_id).list_low_stock()


@router.post("/warehouses", response_model=WarehouseOut)
async def create_warehouse(
    payload: WarehouseCreate,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await InventoryService(session, actor.workspace_id).create_warehouse(payload)


@router.get("/warehouses", response_model=list[WarehouseOut])
async def list_warehouses(
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await InventoryService(session, actor.workspace_id).warehouses.list()


@router.post("/stock/adjustments", response_model=StockMovementOut)
async def adjust_stock(
    payload: StockAdjustmentRequest,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await InventoryService(session, actor.workspace_id).record_adjustment(
        product_id=payload.product_id,
        warehouse_id=payload.warehouse_id,
        qty_delta=payload.qty_delta,
        unit_cost=payload.unit_cost,
        reason=payload.reason,
        is_opening=payload.is_opening,
    )


@router.get("/products/{product_id}/movements", response_model=list[StockMovementOut])
async def list_movements(
    product_id: str,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    from app.modules.inventory.models import StockMovement

    service = InventoryService(session, actor.workspace_id)
    return await service.movements.list(StockMovement.product_id == product_id)


@router.get("/products/{product_id}/stock-by-warehouse", response_model=list[WarehouseStockOut])
async def stock_by_warehouse(
    product_id: str,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    service = InventoryService(session, actor.workspace_id)
    return await service.warehouse_stock_for_product(product_id)


@router.get("/warehouse-stock", response_model=list[WarehouseStockOut])
async def list_warehouse_stock(
    warehouse_id: str | None = None,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    """Per-shop stock levels — what a shop's till/manager needs to see, and what
    the transfer form uses to show how much is available to move out."""
    service = InventoryService(session, actor.workspace_id)
    if warehouse_id:
        return await service.warehouse_stock.list(WarehouseStock.warehouse_id == warehouse_id)
    return await service.warehouse_stock.list()


@router.post("/transfers", response_model=StockTransferOut)
async def create_transfer(
    payload: TransferCreate,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await InventoryService(session, actor.workspace_id).transfer_stock(payload)
