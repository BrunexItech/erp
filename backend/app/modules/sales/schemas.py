from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.modules.sales.models import InvoiceStatus, QuoteStatus, SalesOrderStatus


class SalesOrderLineCreate(BaseModel):
    product_id: str
    qty: Decimal
    unit_price: Decimal
    tax_rate: Decimal = Decimal("0")


class SalesOrderCreate(BaseModel):
    party_id: str
    lines: list[SalesOrderLineCreate]


class SalesOrderOut(BaseModel):
    id: str
    so_no: str
    party_id: str
    status: SalesOrderStatus
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal

    class Config:
        from_attributes = True


class SalesOrderLineOut(BaseModel):
    id: str
    product_id: str
    qty: Decimal
    unit_price: Decimal
    tax_rate: Decimal
    qty_delivered: Decimal

    class Config:
        from_attributes = True


class DeliveryLineInput(BaseModel):
    order_line_id: str
    product_id: str
    qty_delivered: Decimal


class DeliveryCreate(BaseModel):
    order_id: str
    warehouse_id: str
    lines: list[DeliveryLineInput]


class DocumentLineInput(BaseModel):
    """One line on an invoice or quote. product_id is optional — a line can be a
    free-text service ("Consulting, March") with no stock item behind it."""

    product_id: str | None = None
    description: str = ""
    qty: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    discount_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    tax_rate: Decimal = Field(default=Decimal("0"), ge=0, le=1)  # 0.16 = 16% VAT


class DocumentLineOut(BaseModel):
    id: str
    position: int
    product_id: str | None
    description: str
    qty: Decimal
    unit_price: Decimal
    discount_pct: Decimal
    tax_rate: Decimal
    line_subtotal: Decimal
    tax_amount: Decimal
    line_total: Decimal

    class Config:
        from_attributes = True


class InvoiceCreate(BaseModel):
    """Either itemized (`lines`) or, for backwards compatibility, a bare
    subtotal/tax. With `order_id` and no lines, the order's lines are copied.
    With `warehouse_id`, product lines are shipped from that warehouse as part
    of invoicing (stock out at COGS) — Sage's 'invoice and ship' in one step."""

    party_id: str
    order_id: str | None = None
    issue_date: date | None = None
    due_date: date | None = None
    reference: str = ""
    notes: str = ""
    terms: str | None = None
    lines: list[DocumentLineInput] | None = None
    warehouse_id: str | None = None
    subtotal: Decimal | None = None
    tax_total: Decimal = Decimal("0")


class InvoiceOut(BaseModel):
    id: str
    invoice_no: str
    order_id: str | None
    party_id: str
    status: InvoiceStatus
    issue_date: date | None
    due_date: date | None
    reference: str
    notes: str
    terms: str
    subtotal: Decimal
    discount_total: Decimal
    tax_total: Decimal
    total: Decimal
    amount_paid: Decimal
    amount_credited: Decimal

    class Config:
        from_attributes = True


class InvoiceDetailOut(InvoiceOut):
    lines: list[DocumentLineOut]
    balance_due: Decimal
    party_name: str


class CustomerPaymentCreate(BaseModel):
    invoice_id: str
    amount: Decimal = Field(gt=0)
    method: str = ""
    payment_date: date | None = None
    reference: str = ""


class PaymentOut(BaseModel):
    id: str
    document_no: str
    invoice_id: str | None
    party_id: str
    amount: Decimal
    method: str
    reference: str
    entry_date: date | None

    class Config:
        from_attributes = True


class QuoteCreate(BaseModel):
    party_id: str
    issue_date: date | None = None
    valid_until: date | None = None
    reference: str = ""
    notes: str = ""
    terms: str | None = None
    lines: list[DocumentLineInput] = Field(min_length=1)


class QuoteOut(BaseModel):
    id: str
    quote_no: str
    party_id: str
    status: QuoteStatus
    issue_date: date
    valid_until: date | None
    reference: str
    notes: str
    terms: str
    subtotal: Decimal
    discount_total: Decimal
    tax_total: Decimal
    total: Decimal
    converted_invoice_id: str | None

    class Config:
        from_attributes = True


class QuoteDetailOut(QuoteOut):
    lines: list[DocumentLineOut]
    party_name: str


class QuoteStatusUpdate(BaseModel):
    status: QuoteStatus


class QuoteConvert(BaseModel):
    issue_date: date | None = None
    due_date: date | None = None
    warehouse_id: str | None = None


class CreditNoteLineInput(BaseModel):
    invoice_line_id: str | None = None  # credit a specific invoice line...
    product_id: str | None = None  # ...or a free line
    description: str = ""
    qty: Decimal = Field(gt=0)
    unit_price: Decimal | None = None  # defaults to the invoice line's net unit price
    tax_rate: Decimal | None = None


class CreditNoteCreate(BaseModel):
    invoice_id: str
    issue_date: date | None = None
    reason: str = ""
    restock_warehouse_id: str | None = None  # return product lines to this warehouse
    lines: list[CreditNoteLineInput] | None = None  # None = credit the whole invoice


class CreditNoteOut(BaseModel):
    id: str
    credit_note_no: str
    invoice_id: str
    party_id: str
    issue_date: date
    reason: str
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal

    class Config:
        from_attributes = True


class VoidRequest(BaseModel):
    reason: str = ""


class PosCheckoutLine(BaseModel):
    product_id: str
    qty: Decimal
    unit_price: Decimal
    tax_rate: Decimal = Decimal("0")


class PosCheckoutRequest(BaseModel):
    warehouse_id: str
    party_id: str | None = None  # None -> billed to the workspace's Walk-in Customer
    payment_method: str = "cash"
    payment_reference: str = ""  # M-Pesa confirmation code, card slip no.
    amount_tendered: Decimal | None = None  # cash handed over; change is computed
    lines: list[PosCheckoutLine] = Field(min_length=1)


class PosReceiptOut(BaseModel):
    order_id: str
    invoice_id: str
    invoice_no: str
    receipt_no: str
    party_id: str
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal
    total_cogs: Decimal
    payment_method: str
    payment_reference: str
    amount_tendered: Decimal
    change_due: Decimal
    issued_at: datetime


class EmailDocumentRequest(BaseModel):
    to: str | None = None  # defaults to the customer's email on file
    cc: list[str] = []
    message: str = ""
    start: date | None = None  # statements only
    end: date | None = None


class EmailDocumentResult(BaseModel):
    to: str
    delivered: bool  # False = email isn't configured; the message was saved to the outbox
    backend: str
