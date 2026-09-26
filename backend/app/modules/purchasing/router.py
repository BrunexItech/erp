from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor, get_actor, get_tenant_session
from app.modules.purchasing.models import PurchaseOrderLine
from app.modules.purchasing.schemas import (
    GoodsReceiptCreate,
    PurchaseOrderCreate,
    PurchaseOrderLineOut,
    PurchaseOrderOut,
    VendorBillCreate,
    VendorBillOut,
    VendorPaymentCreate,
)
from app.modules.purchasing.service import PurchasingService

router = APIRouter(prefix="/api/v1/purchasing", tags=["purchasing"])


@router.post("/purchase-orders", response_model=PurchaseOrderOut)
async def create_purchase_order(
    payload: PurchaseOrderCreate,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await PurchasingService(session, actor.workspace_id).create_purchase_order(payload)


@router.get("/purchase-orders", response_model=list[PurchaseOrderOut])
async def list_purchase_orders(
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await PurchasingService(session, actor.workspace_id).orders.list()


@router.get("/purchase-orders/{po_id}/lines", response_model=list[PurchaseOrderLineOut])
async def list_purchase_order_lines(
    po_id: str,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    service = PurchasingService(session, actor.workspace_id)
    return await service.order_lines.list(PurchaseOrderLine.po_id == po_id)


@router.post("/purchase-orders/{po_id}/confirm", response_model=PurchaseOrderOut)
async def confirm_purchase_order(
    po_id: str,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await PurchasingService(session, actor.workspace_id).confirm_purchase_order(po_id)


@router.post("/goods-receipts")
async def receive_goods(
    payload: GoodsReceiptCreate,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    receipt = await PurchasingService(session, actor.workspace_id).receive_goods(payload)
    return {"id": receipt.id, "po_id": receipt.po_id, "warehouse_id": receipt.warehouse_id}


@router.post("/vendor-bills", response_model=VendorBillOut)
async def create_vendor_bill(
    payload: VendorBillCreate,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await PurchasingService(session, actor.workspace_id).create_vendor_bill(payload)


@router.get("/vendor-bills", response_model=list[VendorBillOut])
async def list_vendor_bills(
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await PurchasingService(session, actor.workspace_id).bills.list()


@router.post("/vendor-bills/payments")
async def record_payment(
    payload: VendorPaymentCreate,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    entry = await PurchasingService(session, actor.workspace_id).record_payment(
        payload.vendor_bill_id, payload.amount, payload.method, payload.payment_date
    )
    return {"id": entry.id, "amount": str(entry.amount)}


@router.get("/vendors/{party_id}/balance")
async def vendor_balance(
    party_id: str,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    balance = await PurchasingService(session, actor.workspace_id).vendor_balance(party_id)
    return {"party_id": party_id, "balance": str(balance)}


@router.get("/reports/ap-aging")
async def ap_aging(
    as_of: date | None = None,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await PurchasingService(session, actor.workspace_id).ap_aging(as_of)
