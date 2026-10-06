from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor, get_actor, get_tenant_session, require_permission
from app.modules.inventory import importer
from app.modules.inventory.models import WarehouseStock
from app.modules.inventory.schemas import (
    ProductCreate,
    ProductOut,
    ProductUpdate,
    StockAdjustmentRequest,
    StockCountCreate,
    StockCountSave,
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


@router.get("/products/import-template")
async def product_import_template(actor: Actor = Depends(get_actor)):
    return importer.template()


@router.get("/products/export")
async def export_products(actor: Actor = Depends(get_actor), session: AsyncSession = Depends(get_tenant_session)):
    return await importer.export_products(InventoryService(session, actor.workspace_id))


@router.post("/products/import")
async def import_products(
    file: UploadFile,
    actor: Actor = Depends(require_permission("inventory.write")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await importer.import_products(InventoryService(session, actor.workspace_id), file)


@router.get("/reports/valuation")
async def valuation_report(actor: Actor = Depends(get_actor), session: AsyncSession = Depends(get_tenant_session)):
    return await InventoryService(session, actor.workspace_id).valuation_report()


@router.patch("/products/{product_id}", response_model=ProductOut)
async def update_product(
    product_id: str,
    payload: ProductUpdate,
    actor: Actor = Depends(require_permission("inventory.write")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await InventoryService(session, actor.workspace_id).update_product(
        product_id, payload.model_dump(exclude_unset=True)
    )


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
    movements = await service.movements.list(StockMovement.product_id == product_id)
    return sorted(movements, key=lambda m: m.created_at, reverse=True)[:200]


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


@router.get("/transfers")
async def list_transfers(actor: Actor = Depends(get_actor), session: AsyncSession = Depends(get_tenant_session)):
    """Recent stock transfers with their lines."""
    from app.modules.inventory.models import StockTransferLine

    service = InventoryService(session, actor.workspace_id)
    transfers = sorted(await service.transfers.list(), key=lambda t: t.created_at, reverse=True)[:100]
    lines = await service.transfer_lines.list(StockTransferLine.transfer_id.in_([t.id for t in transfers])) if transfers else []
    by_transfer: dict[str, list] = {}
    for line in lines:
        by_transfer.setdefault(line.transfer_id, []).append(
            {"product_id": line.product_id, "qty": line.qty, "unit_cost": line.unit_cost}
        )
    return [
        {
            "id": t.id, "created_at": t.created_at, "from_warehouse_id": t.from_warehouse_id,
            "to_warehouse_id": t.to_warehouse_id, "note": t.note, "lines": by_transfer.get(t.id, []),
        }
        for t in transfers
    ]


# ------------------------------------------------------------- stock take


@router.get("/stock-counts")
async def list_stock_counts(actor: Actor = Depends(get_actor), session: AsyncSession = Depends(get_tenant_session)):
    from app.core.db import TenantRepository
    from app.modules.inventory.models import StockCount

    counts = await TenantRepository(session, actor.workspace_id, StockCount).list()
    return [
        {"id": c.id, "count_no": c.count_no, "warehouse_id": c.warehouse_id, "status": c.status.value, "note": c.note,
         "created_at": c.created_at, "posted_at": c.posted_at, "variance_value": c.variance_value}
        for c in sorted(counts, key=lambda c: c.created_at, reverse=True)
    ]


@router.post("/stock-counts")
async def start_stock_count(payload: StockCountCreate, actor: Actor = Depends(get_actor), session: AsyncSession = Depends(get_tenant_session)):
    count = await InventoryService(session, actor.workspace_id).start_count(payload.warehouse_id, payload.category, payload.note)
    return {"id": count.id, "count_no": count.count_no}


@router.get("/stock-counts/{count_id}")
async def stock_count_detail(count_id: str, actor: Actor = Depends(get_actor), session: AsyncSession = Depends(get_tenant_session)):
    return await InventoryService(session, actor.workspace_id).count_detail(count_id)


@router.put("/stock-counts/{count_id}")
async def save_stock_count(
    count_id: str, payload: StockCountSave, actor: Actor = Depends(get_actor), session: AsyncSession = Depends(get_tenant_session)
):
    await InventoryService(session, actor.workspace_id).save_count(count_id, payload.lines)
    return {"ok": True}


@router.post("/stock-counts/{count_id}/post")
async def post_stock_count(count_id: str, actor: Actor = Depends(get_actor), session: AsyncSession = Depends(get_tenant_session)):
    return await InventoryService(session, actor.workspace_id).post_count(count_id)


@router.post("/stock-counts/{count_id}/cancel")
async def cancel_stock_count(count_id: str, actor: Actor = Depends(get_actor), session: AsyncSession = Depends(get_tenant_session)):
    await InventoryService(session, actor.workspace_id).cancel_count(count_id)
    return {"ok": True}


@router.get("/reports/reorder")
async def reorder_report(actor: Actor = Depends(get_actor), session: AsyncSession = Depends(get_tenant_session)):
    return await InventoryService(session, actor.workspace_id).reorder_report()


@router.post("/products/{product_id}/image", response_model=ProductOut)
async def upload_product_image(
    product_id: str, file: UploadFile, actor: Actor = Depends(get_actor), session: AsyncSession = Depends(get_tenant_session)
):
    from app.core import media

    data = await file.read(media.MAX_UPLOAD_BYTES + 1)
    url = media.save_image("products", product_id, data, max_side=600)
    return await InventoryService(session, actor.workspace_id).update_product(product_id, {"image_url": url})
