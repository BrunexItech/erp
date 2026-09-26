from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.aging import bucket_for, empty_buckets
from app.core.db import TenantRepository
from app.core.numbering import next_number
from app.modules.inventory.models import StockMovementType
from app.modules.inventory.service import InventoryService
from app.modules.purchasing.models import (
    ApPaymentEntry,
    ApPaymentEntryType,
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    VendorBill,
    VendorBillStatus,
)
from app.modules.purchasing.schemas import (
    GoodsReceiptCreate,
    PurchaseOrderCreate,
    VendorBillCreate,
)


class PurchasingService:
    def __init__(self, session: AsyncSession, workspace_id: str):
        self.session = session
        self.workspace_id = workspace_id
        self.orders = TenantRepository(session, workspace_id, PurchaseOrder)
        self.order_lines = TenantRepository(session, workspace_id, PurchaseOrderLine)
        self.receipts = TenantRepository(session, workspace_id, GoodsReceipt)
        self.receipt_lines = TenantRepository(session, workspace_id, GoodsReceiptLine)
        self.bills = TenantRepository(session, workspace_id, VendorBill)
        self.ap_entries = TenantRepository(session, workspace_id, ApPaymentEntry)
        self.inventory = InventoryService(session, workspace_id)

    async def create_purchase_order(self, payload: PurchaseOrderCreate) -> PurchaseOrder:
        subtotal = sum((l.qty_ordered * l.unit_cost for l in payload.lines), Decimal("0"))
        order = PurchaseOrder(
            po_no=await next_number(self.session, self.workspace_id, "purchase_order"),
            party_id=payload.party_id,
            expected_date=payload.expected_date,
            subtotal=subtotal,
            tax_total=Decimal("0"),
            total=subtotal,
            status=PurchaseOrderStatus.draft,
        )
        await self.orders.add(order)
        await self.session.flush()

        for line in payload.lines:
            await self.order_lines.add(
                PurchaseOrderLine(
                    po_id=order.id,
                    product_id=line.product_id,
                    qty_ordered=line.qty_ordered,
                    unit_cost=line.unit_cost,
                )
            )
        await self.session.commit()
        await self.session.refresh(order)
        return order

    async def confirm_purchase_order(self, po_id: str) -> PurchaseOrder:
        order = await self.orders.get(po_id)
        if order is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "purchase order not found")
        order.status = PurchaseOrderStatus.confirmed
        await self.session.commit()
        await self.session.refresh(order)
        return order

    async def receive_goods(self, payload: GoodsReceiptCreate) -> GoodsReceipt:
        """Goods receipt: increases stock at the ACTUAL received cost (fixing
        Stoka's gap of never recalculating cost on restock), then posts the
        Inventory/AP journal entry via the GoodsReceiptPosted event — all in one
        transaction/commit."""
        order = await self.orders.get(payload.po_id)
        if order is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "purchase order not found")

        receipt = GoodsReceipt(po_id=payload.po_id, warehouse_id=payload.warehouse_id)
        await self.receipts.add(receipt)
        await self.session.flush()

        total_cost = Decimal("0")
        for line in payload.lines:
            landed_per_unit = (
                line.landed_cost_amount / line.qty_received if line.qty_received else Decimal("0")
            )
            effective_unit_cost = line.actual_unit_cost + landed_per_unit

            po_line = await self.order_lines.get(line.po_line_id)
            if po_line is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "purchase order line not found")

            await self.receipt_lines.add(
                GoodsReceiptLine(
                    receipt_id=receipt.id,
                    po_line_id=line.po_line_id,
                    product_id=line.product_id,
                    qty_received=line.qty_received,
                    actual_unit_cost=line.actual_unit_cost,
                    landed_cost_amount=line.landed_cost_amount,
                )
            )

            po_line.qty_received += line.qty_received

            await self.inventory.apply_movement(
                product_id=line.product_id,
                warehouse_id=payload.warehouse_id,
                type=StockMovementType.receipt,
                qty_delta=line.qty_received,
                unit_cost=effective_unit_cost,
                ref_type="goods_receipt",
                ref_id=receipt.id,
            )
            total_cost += line.qty_received * effective_unit_cost

        fully_received = all(
            pl.qty_received >= pl.qty_ordered
            for pl in await self.order_lines.list(PurchaseOrderLine.po_id == order.id)
        )
        order.status = (
            PurchaseOrderStatus.received if fully_received else PurchaseOrderStatus.partially_received
        )

        await events.publish(
            events.GoodsReceiptPosted(
                workspace_id=self.workspace_id,
                receipt_id=receipt.id,
                purchase_order_id=order.id,
                total_cost=float(total_cost),
            ),
            self.session,
        )

        await self.session.commit()
        await self.session.refresh(receipt)
        return receipt

    async def create_vendor_bill(self, payload: VendorBillCreate) -> VendorBill:
        """Posts the bill to the AP sub-ledger AND the GL (via VendorBillPosted),
        so the two can never disagree. A direct bill (no PO) books its cost to
        the chosen expense account; a PO bill only posts VAT plus any difference
        between what was billed and what the goods were received at."""
        total = payload.subtotal + payload.tax_total
        bill_date = payload.bill_date or date.today()
        due_date = payload.due_date
        if due_date is None:
            terms = await self._vendor_terms_days(payload.party_id)
            due_date = bill_date + timedelta(days=terms)

        price_variance = Decimal("0")
        if payload.po_id is not None:
            if await self.orders.get(payload.po_id) is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "purchase order not found")
            unbilled = await self._received_value(payload.po_id) - await self._billed_subtotal(payload.po_id)
            price_variance = payload.subtotal - unbilled

        bill = VendorBill(
            bill_no=await next_number(self.session, self.workspace_id, "vendor_bill"),
            party_id=payload.party_id,
            po_id=payload.po_id,
            bill_date=bill_date,
            due_date=due_date,
            vendor_reference=payload.vendor_reference,
            memo=payload.memo,
            expense_account_id=payload.expense_account_id if payload.po_id is None else None,
            subtotal=payload.subtotal,
            tax_total=payload.tax_total,
            total=total,
            status=VendorBillStatus.posted,
        )
        await self.bills.add(bill)
        await self.session.flush()

        await self.ap_entries.add(
            ApPaymentEntry(
                party_id=payload.party_id,
                vendor_bill_id=bill.id,
                type=ApPaymentEntryType.bill_charge,
                amount=total,
            )
        )

        await events.publish(
            events.VendorBillPosted(
                workspace_id=self.workspace_id,
                vendor_bill_id=bill.id,
                po_id=payload.po_id,
                subtotal=float(payload.subtotal),
                tax_total=float(payload.tax_total),
                total=float(total),
                expense_account_id=bill.expense_account_id,
                price_variance=float(price_variance),
                entry_date=bill_date,
            ),
            self.session,
        )
        await self.session.commit()
        await self.session.refresh(bill)
        return bill

    async def _vendor_terms_days(self, party_id: str) -> int:
        from app.modules.crm.models import VendorProfile

        profiles = await TenantRepository(self.session, self.workspace_id, VendorProfile).list(
            VendorProfile.party_id == party_id
        )
        return profiles[0].payment_terms_days if profiles else 30

    async def _received_value(self, po_id: str) -> Decimal:
        stmt = (
            select(
                func.coalesce(
                    func.sum(
                        GoodsReceiptLine.qty_received * GoodsReceiptLine.actual_unit_cost
                        + GoodsReceiptLine.landed_cost_amount
                    ),
                    0,
                )
            )
            .join(GoodsReceipt, GoodsReceipt.id == GoodsReceiptLine.receipt_id)
            .where(GoodsReceiptLine.workspace_id == self.workspace_id, GoodsReceipt.po_id == po_id)
        )
        return Decimal((await self.session.execute(stmt)).scalar_one())

    async def _billed_subtotal(self, po_id: str) -> Decimal:
        stmt = select(func.coalesce(func.sum(VendorBill.subtotal), 0)).where(
            VendorBill.workspace_id == self.workspace_id,
            VendorBill.po_id == po_id,
            VendorBill.status != VendorBillStatus.void,
        )
        return Decimal((await self.session.execute(stmt)).scalar_one())

    async def record_payment(
        self, vendor_bill_id: str, amount: Decimal, method: str, payment_date: date | None = None
    ) -> ApPaymentEntry:
        bill = await self.bills.get_for_update(vendor_bill_id)
        if bill is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "vendor bill not found")
        if amount <= 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "payment amount must be positive")
        outstanding = bill.total - await self._bill_paid_total(bill.id)
        if amount > outstanding:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"payment {amount} exceeds the bill's outstanding balance {outstanding}",
            )

        entry = ApPaymentEntry(
            party_id=bill.party_id,
            vendor_bill_id=bill.id,
            type=ApPaymentEntryType.payment,
            amount=amount,
            method=method,
        )
        await self.ap_entries.add(entry)
        await self.session.flush()

        paid_so_far = await self._bill_paid_total(bill.id)
        bill.status = (
            VendorBillStatus.paid if paid_so_far >= bill.total else VendorBillStatus.partially_paid
        )

        await events.publish(
            events.PaymentMade(
                workspace_id=self.workspace_id,
                payment_id=entry.id,
                vendor_bill_id=bill.id,
                amount=float(amount),
                entry_date=payment_date,
            ),
            self.session,
        )

        await self.session.commit()
        await self.session.refresh(entry)
        return entry

    async def _bill_paid_total(self, vendor_bill_id: str) -> Decimal:
        stmt = select(func.coalesce(func.sum(ApPaymentEntry.amount), 0)).where(
            ApPaymentEntry.workspace_id == self.workspace_id,
            ApPaymentEntry.vendor_bill_id == vendor_bill_id,
            ApPaymentEntry.type == ApPaymentEntryType.payment,
        )
        return Decimal((await self.session.execute(stmt)).scalar_one())

    async def vendor_balance(self, party_id: str) -> Decimal:
        charges = select(func.coalesce(func.sum(ApPaymentEntry.amount), 0)).where(
            ApPaymentEntry.workspace_id == self.workspace_id,
            ApPaymentEntry.party_id == party_id,
            ApPaymentEntry.type == ApPaymentEntryType.bill_charge,
        )
        # A debit note reduces what we owe the vendor, same as a payment.
        payments = select(func.coalesce(func.sum(ApPaymentEntry.amount), 0)).where(
            ApPaymentEntry.workspace_id == self.workspace_id,
            ApPaymentEntry.party_id == party_id,
            ApPaymentEntry.type.in_([ApPaymentEntryType.payment, ApPaymentEntryType.debit_note]),
        )
        charge_total = Decimal((await self.session.execute(charges)).scalar_one())
        payment_total = Decimal((await self.session.execute(payments)).scalar_one())
        return charge_total - payment_total

    async def ap_aging(self, as_of: date | None = None) -> dict:
        """Outstanding vendor bills bucketed by days past due, per vendor."""
        as_of = as_of or date.today()
        bills = await self.bills.list(
            VendorBill.status.in_([VendorBillStatus.posted, VendorBillStatus.partially_paid])
        )
        paid = await self._paid_by_bill()
        from app.modules.crm.models import Party

        parties = {p.id: p for p in await TenantRepository(self.session, self.workspace_id, Party).list()}
        rows: dict[str, dict] = defaultdict(lambda: {"buckets": empty_buckets(), "total": Decimal("0")})
        totals = empty_buckets()
        for bill in bills:
            outstanding = bill.total - paid.get(bill.id, Decimal("0"))
            if outstanding <= 0:
                continue
            bucket = bucket_for(bill.due_date, as_of)
            row = rows[bill.party_id]
            row["buckets"][bucket] += outstanding
            row["total"] += outstanding
            totals[bucket] += outstanding
        return {
            "as_of": as_of,
            "rows": [
                {
                    "party_id": party_id,
                    "party_name": parties[party_id].name if party_id in parties else party_id,
                    **row["buckets"],
                    "total": row["total"],
                }
                for party_id, row in sorted(rows.items(), key=lambda kv: -kv[1]["total"])
            ],
            "totals": {**totals, "total": sum(totals.values(), Decimal("0"))},
        }

    async def _paid_by_bill(self) -> dict[str, Decimal]:
        stmt = (
            select(ApPaymentEntry.vendor_bill_id, func.coalesce(func.sum(ApPaymentEntry.amount), 0))
            .where(
                ApPaymentEntry.workspace_id == self.workspace_id,
                ApPaymentEntry.type == ApPaymentEntryType.payment,
            )
            .group_by(ApPaymentEntry.vendor_bill_id)
        )
        return {bill_id: Decimal(total) for bill_id, total in (await self.session.execute(stmt)).all()}
