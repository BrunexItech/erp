from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import TenantModel


class PurchaseOrderStatus(str, enum.Enum):
    draft = "draft"
    confirmed = "confirmed"
    partially_received = "partially_received"
    received = "received"
    closed = "closed"
    cancelled = "cancelled"


class PurchaseOrder(TenantModel):
    __tablename__ = "purchase_orders"

    po_no: Mapped[str] = mapped_column(String(32), default="", index=True)
    party_id: Mapped[str] = mapped_column(ForeignKey("parties.id"), index=True)  # vendor
    status: Mapped[PurchaseOrderStatus] = mapped_column(default=PurchaseOrderStatus.draft)
    expected_date: Mapped[date | None] = mapped_column(nullable=True)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    tax_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)


class PurchaseOrderLine(TenantModel):
    __tablename__ = "purchase_order_lines"

    po_id: Mapped[str] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"))
    qty_ordered: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6))  # expected cost
    qty_received: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)


class GoodsReceipt(TenantModel):
    __tablename__ = "goods_receipts"

    po_id: Mapped[str] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    warehouse_id: Mapped[str] = mapped_column(ForeignKey("warehouses.id"))
    received_at: Mapped[datetime] = mapped_column(server_default=func.now())


class GoodsReceiptLine(TenantModel):
    __tablename__ = "goods_receipt_lines"

    receipt_id: Mapped[str] = mapped_column(ForeignKey("goods_receipts.id"), index=True)
    po_line_id: Mapped[str] = mapped_column(ForeignKey("purchase_order_lines.id"))
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"))
    qty_received: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    actual_unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    landed_cost_amount: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=0)  # freight/duties


class VendorBillStatus(str, enum.Enum):
    draft = "draft"
    posted = "posted"
    partially_paid = "partially_paid"
    paid = "paid"
    void = "void"


class VendorBill(TenantModel):
    __tablename__ = "vendor_bills"

    bill_no: Mapped[str] = mapped_column(String(32), default="", index=True)
    vendor_reference: Mapped[str] = mapped_column(String(64), default="")  # the supplier's own invoice no.
    bill_date: Mapped[date | None] = mapped_column(nullable=True)
    memo: Mapped[str] = mapped_column(String(500), default="")
    # Direct (non-PO) bills only: which expense account the cost is booked to.
    expense_account_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    po_id: Mapped[str | None] = mapped_column(ForeignKey("purchase_orders.id"), nullable=True)
    party_id: Mapped[str] = mapped_column(ForeignKey("parties.id"), index=True)
    status: Mapped[VendorBillStatus] = mapped_column(default=VendorBillStatus.draft)
    due_date: Mapped[date | None] = mapped_column(nullable=True)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    tax_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)


class ApPaymentEntryType(str, enum.Enum):
    bill_charge = "bill_charge"
    payment = "payment"
    debit_note = "debit_note"


class ApPaymentEntry(TenantModel):
    """Accounts-payable sub-ledger — same append-only pattern as Stoka's DebtEntry.
    Balance = SUM(bill_charge) - SUM(payment + debit_note), computed on read, never
    stored (see PurchasingService.vendor_balance)."""

    __tablename__ = "ap_payment_entries"

    party_id: Mapped[str] = mapped_column(ForeignKey("parties.id"), index=True)
    vendor_bill_id: Mapped[str | None] = mapped_column(ForeignKey("vendor_bills.id"), nullable=True)
    type: Mapped[ApPaymentEntryType]
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))  # always positive
    method: Mapped[str] = mapped_column(String(32), default="")
