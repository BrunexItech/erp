from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, ForeignKey, Numeric, String, func
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
    # KRA eTIMS (see sales/etims.py). "" = not applicable (eTIMS off).
    etims_status: Mapped[str] = mapped_column(String(16), default="")  # "" | pending | submitted | failed
    etims_reference: Mapped[str] = mapped_column(String(64), default="")
    etims_qr: Mapped[str] = mapped_column(String(500), default="")
    etims_error: Mapped[str] = mapped_column(String(300), default="")
    # Set by a till for each sale it rings up. If the same sale is sent twice
    # (a retry after a dropped connection, or an offline sale syncing), the
    # second attempt returns the first invoice instead of selling it again.
    client_ref: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)


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


class RecurringFrequency(str, enum.Enum):
    weekly = "weekly"
    monthly = "monthly"
    quarterly = "quarterly"
    yearly = "yearly"


class RecurringInvoice(TenantModel):
    """A template that raises the same invoice on a schedule — rent, a
    retainer, a monthly service contract."""

    __tablename__ = "recurring_invoices"

    party_id: Mapped[str] = mapped_column(ForeignKey("parties.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    frequency: Mapped[RecurringFrequency] = mapped_column(default=RecurringFrequency.monthly)
    next_date: Mapped[date]
    end_date: Mapped[date | None] = mapped_column(nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    reference: Mapped[str] = mapped_column(String(64), default="")
    notes: Mapped[str] = mapped_column(String(2000), default="")
    prices_include_tax: Mapped[bool] = mapped_column(default=False)
    lines: Mapped[list] = mapped_column(JSON, default=list)  # DocumentLineInput dicts
    invoices_raised: Mapped[int] = mapped_column(default=0)
    last_invoice_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    email_to_customer: Mapped[bool] = mapped_column(default=False)


class MpesaConfig(TenantModel):
    """A business's own Safaricom Daraja credentials, so money goes straight
    to their paybill/till. Secrets are stored encrypted (core/crypto.py)."""

    __tablename__ = "mpesa_configs"

    environment: Mapped[str] = mapped_column(String(16), default="sandbox")  # sandbox | production
    shortcode: Mapped[str] = mapped_column(String(20), default="")  # paybill, or the store number for a till
    till_number: Mapped[str] = mapped_column(String(20), default="")  # set for Buy Goods (till) accounts
    consumer_key_enc: Mapped[str] = mapped_column(String(500), default="")
    consumer_secret_enc: Mapped[str] = mapped_column(String(500), default="")
    passkey_enc: Mapped[str] = mapped_column(String(500), default="")
    is_active: Mapped[bool] = mapped_column(default=False)


class MpesaRequest(TenantModel):
    """One STK push ("pay now" prompt on the customer's phone) and its outcome."""

    __tablename__ = "mpesa_requests"

    invoice_id: Mapped[str | None] = mapped_column(ForeignKey("invoices.id"), nullable=True, index=True)
    phone: Mapped[str] = mapped_column(String(16))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    account_reference: Mapped[str] = mapped_column(String(32), default="")
    checkout_request_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    merchant_request_id: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | success | failed
    result_desc: Mapped[str] = mapped_column(String(300), default="")
    mpesa_receipt: Mapped[str] = mapped_column(String(32), default="")
    callback_token_hash: Mapped[str] = mapped_column(String(64), index=True)
    requested_by: Mapped[str] = mapped_column(String(36), default="")
