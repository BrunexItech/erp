from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import TenantModel


class SalesOrderStatus(str, enum.Enum):
    draft = "draft"
    confirmed = "confirmed"
    partially_delivered = "partially_delivered"
    delivered = "delivered"
    invoiced = "invoiced"
    closed = "closed"
    cancelled = "cancelled"


class SalesOrder(TenantModel):
    __tablename__ = "sales_orders"

    so_no: Mapped[str] = mapped_column(String(32), default="", index=True)
    party_id: Mapped[str] = mapped_column(ForeignKey("parties.id"), index=True)
    status: Mapped[SalesOrderStatus] = mapped_column(default=SalesOrderStatus.draft)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    tax_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)


class SalesOrderLine(TenantModel):
    __tablename__ = "sales_order_lines"

    order_id: Mapped[str] = mapped_column(ForeignKey("sales_orders.id"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"))
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(6, 4), default=0)
    qty_delivered: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)


class Delivery(TenantModel):
    __tablename__ = "deliveries"

    order_id: Mapped[str] = mapped_column(ForeignKey("sales_orders.id"), index=True)
    warehouse_id: Mapped[str] = mapped_column(ForeignKey("warehouses.id"))
    delivered_at: Mapped[datetime] = mapped_column(server_default=func.now())
    total_cogs: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=0)


class DeliveryLine(TenantModel):
    __tablename__ = "delivery_lines"

    delivery_id: Mapped[str] = mapped_column(ForeignKey("deliveries.id"), index=True)
    order_line_id: Mapped[str] = mapped_column(ForeignKey("sales_order_lines.id"))
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"))
    qty_delivered: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    cogs_amount: Mapped[Decimal] = mapped_column(Numeric(18, 6))  # snapshot from apply_movement


class InvoiceStatus(str, enum.Enum):
    draft = "draft"
    posted = "posted"
    partially_paid = "partially_paid"
    paid = "paid"
    void = "void"


class Invoice(TenantModel):
    __tablename__ = "invoices"

    invoice_no: Mapped[str] = mapped_column(String(32), default="", index=True)
    order_id: Mapped[str | None] = mapped_column(ForeignKey("sales_orders.id"), nullable=True)
    quote_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    party_id: Mapped[str] = mapped_column(ForeignKey("parties.id"), index=True)
    status: Mapped[InvoiceStatus] = mapped_column(default=InvoiceStatus.draft)
    issue_date: Mapped[date | None] = mapped_column(nullable=True)
    due_date: Mapped[date | None] = mapped_column(nullable=True)
    reference: Mapped[str] = mapped_column(String(64), default="")  # customer's PO / LPO number
    notes: Mapped[str] = mapped_column(String(2000), default="")
    terms: Mapped[str] = mapped_column(String(2000), default="")
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    discount_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    tax_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    amount_credited: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    channel: Mapped[str] = mapped_column(String(16), default="invoice", index=True)  # "invoice" | "pos"
    warehouse_id: Mapped[str | None] = mapped_column(ForeignKey("warehouses.id"), nullable=True)  # POS till location
    cashier_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class InvoiceLine(TenantModel):
    """Stored on the invoice itself (not derived from the sales order at print
    time) so a tax invoice reprints identically forever, and so service/direct
    invoices with no order can still be itemized."""

    __tablename__ = "invoice_lines"

    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoices.id"), index=True)
    position: Mapped[int] = mapped_column(default=0)
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    description: Mapped[str] = mapped_column(String(500))
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    discount_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=0)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(6, 4), default=0)
    line_subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2))  # after discount, before tax
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    line_total: Mapped[Decimal] = mapped_column(Numeric(18, 2))


class QuoteStatus(str, enum.Enum):
    draft = "draft"
    sent = "sent"
    accepted = "accepted"
    declined = "declined"
    converted = "converted"


class Quote(TenantModel):
    __tablename__ = "quotes"

    quote_no: Mapped[str] = mapped_column(String(32), default="", index=True)
    party_id: Mapped[str] = mapped_column(ForeignKey("parties.id"), index=True)
    status: Mapped[QuoteStatus] = mapped_column(default=QuoteStatus.draft)
    issue_date: Mapped[date]
    valid_until: Mapped[date | None] = mapped_column(nullable=True)
    reference: Mapped[str] = mapped_column(String(64), default="")
    notes: Mapped[str] = mapped_column(String(2000), default="")
    terms: Mapped[str] = mapped_column(String(2000), default="")
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    discount_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    tax_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    converted_invoice_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class QuoteLine(TenantModel):
    __tablename__ = "quote_lines"

    quote_id: Mapped[str] = mapped_column(ForeignKey("quotes.id"), index=True)
    position: Mapped[int] = mapped_column(default=0)
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    description: Mapped[str] = mapped_column(String(500))
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    discount_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=0)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(6, 4), default=0)
    line_subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    line_total: Mapped[Decimal] = mapped_column(Numeric(18, 2))


class CreditNote(TenantModel):
    __tablename__ = "credit_notes"

    credit_note_no: Mapped[str] = mapped_column(String(32), default="", index=True)
    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoices.id"), index=True)
    party_id: Mapped[str] = mapped_column(ForeignKey("parties.id"), index=True)
    issue_date: Mapped[date]
    reason: Mapped[str] = mapped_column(String(500), default="")
    restocked_warehouse_id: Mapped[str | None] = mapped_column(ForeignKey("warehouses.id"), nullable=True)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    tax_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)


class CreditNoteLine(TenantModel):
    __tablename__ = "credit_note_lines"

    credit_note_id: Mapped[str] = mapped_column(ForeignKey("credit_notes.id"), index=True)
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    description: Mapped[str] = mapped_column(String(500))
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(6, 4), default=0)
    line_subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    line_total: Mapped[Decimal] = mapped_column(Numeric(18, 2))


class ArPaymentEntryType(str, enum.Enum):
    invoice_charge = "invoice_charge"
    payment = "payment"
    credit_note = "credit_note"


class ArPaymentEntry(TenantModel):
    """Accounts-receivable sub-ledger — same append-only pattern as Stoka's
    DebtEntry. Balance = SUM(invoice_charge) - SUM(payment + credit_note),
    computed on read, never stored (see SalesService.customer_balance)."""

    __tablename__ = "ar_payment_entries"

    party_id: Mapped[str] = mapped_column(ForeignKey("parties.id"), index=True)
    invoice_id: Mapped[str | None] = mapped_column(ForeignKey("invoices.id"), nullable=True)
    type: Mapped[ArPaymentEntryType]
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))  # always positive
    method: Mapped[str] = mapped_column(String(32), default="")
    entry_date: Mapped[date | None] = mapped_column(nullable=True)
    document_no: Mapped[str] = mapped_column(String(32), default="")  # INV-/CN-/RCT- number
    reference: Mapped[str] = mapped_column(String(64), default="")  # M-Pesa code, cheque no, ...
    credit_note_id: Mapped[str | None] = mapped_column(ForeignKey("credit_notes.id"), nullable=True)
