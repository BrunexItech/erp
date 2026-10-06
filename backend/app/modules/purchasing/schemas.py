from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from app.modules.purchasing.models import PurchaseOrderStatus, VendorBillStatus


class PurchaseOrderLineCreate(BaseModel):
    product_id: str
    qty_ordered: Decimal
    unit_cost: Decimal


class PurchaseOrderCreate(BaseModel):
    party_id: str
    expected_date: date | None = None
    lines: list[PurchaseOrderLineCreate]


class PurchaseOrderLineOut(BaseModel):
    id: str
    product_id: str
    qty_ordered: Decimal
    unit_cost: Decimal
    qty_received: Decimal

    class Config:
        from_attributes = True


class PurchaseOrderOut(BaseModel):
    id: str
    po_no: str
    expected_date: date | None
    party_id: str
    status: PurchaseOrderStatus
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal

    class Config:
        from_attributes = True


class GoodsReceiptLineInput(BaseModel):
    po_line_id: str
    product_id: str
    qty_received: Decimal
    actual_unit_cost: Decimal
    landed_cost_amount: Decimal = Decimal("0")


class GoodsReceiptCreate(BaseModel):
    po_id: str
    warehouse_id: str
    lines: list[GoodsReceiptLineInput]


class VendorBillCreate(BaseModel):
    party_id: str
    po_id: str | None = None
    bill_date: date | None = None
    due_date: date | None = None
    vendor_reference: str = ""
    memo: str = ""
    expense_account_id: str | None = None
    subtotal: Decimal
    tax_total: Decimal = Decimal("0")


class VendorBillOut(BaseModel):
    id: str
    bill_no: str
    vendor_reference: str
    bill_date: date | None
    due_date: date | None
    memo: str
    po_id: str | None
    party_id: str
    status: VendorBillStatus
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal

    class Config:
        from_attributes = True


class VendorPaymentCreate(BaseModel):
    vendor_bill_id: str
    amount: Decimal
    method: str = ""
    payment_date: date | None = None


class VendorReturnLine(BaseModel):
    product_id: str
    qty: Decimal
    unit_price: Decimal  # credit per unit, before VAT


class VendorReturnCreate(BaseModel):
    vendor_bill_id: str
    warehouse_id: str  # where the goods leave from
    note_date: date | None = None
    reason: str = ""
    tax_rate: Decimal = Decimal("0")  # VAT rate on the original purchase, e.g. 0.16
    lines: list[VendorReturnLine]
