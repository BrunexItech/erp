"""Lightweight in-process, synchronous event bus.

Modules publish domain events instead of importing and calling each other's services
directly. This keeps cross-module coupling to "knows the event shape", not "knows the
other module's internals" — the seam that lets a module become a separately deployed
service later (swap `publish()`'s body for a message-queue send, subscribers become
their own consumers) without touching call sites.

Deliberately synchronous and same-transaction: an event handler (e.g. accounting's
GL posting) runs inside the same DB session/transaction as the event that triggered it,
so a failure to post the journal entry rolls back the stock movement too. This is a
correctness requirement for an ERP, not just a convenience.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Awaitable, Callable, TypeVar

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

Event = TypeVar("Event")
Handler = Callable[[Event, "AsyncSession"], Awaitable[None]]

_subscribers: dict[type, list[Handler]] = defaultdict(list)


def subscribe(event_type: type[Event], handler: Handler) -> None:
    _subscribers[event_type].append(handler)


async def publish(event: object, session: "AsyncSession") -> None:
    """session must be the SAME session/transaction the publisher is using, so a
    handler's writes (e.g. a journal entry) commit or roll back atomically with the
    action that triggered them."""
    for handler in _subscribers.get(type(event), []):
        await handler(event, session)


def reset_subscribers() -> None:
    """Test-only: clear all registered handlers between test runs."""
    _subscribers.clear()


# --- Canonical event payloads, one per cross-module trigger in the plan ---


@dataclass(frozen=True)
class WorkspaceCreated:
    workspace_id: str


@dataclass(frozen=True)
class StockMovementApplied:
    workspace_id: str
    movement_id: str
    product_id: str
    type: str
    qty_delta: float
    unit_cost: float


@dataclass(frozen=True)
class DeliveryConfirmed:
    workspace_id: str
    delivery_id: str
    sales_order_id: str
    cogs_amount: float
    entry_date: date | None = None  # GL posting date; None = today


@dataclass(frozen=True)
class InvoicePosted:
    workspace_id: str
    invoice_id: str
    party_id: str
    subtotal: float
    tax_total: float
    total: float
    entry_date: date | None = None  # GL posting date; None = today


@dataclass(frozen=True)
class GoodsReceiptPosted:
    workspace_id: str
    receipt_id: str
    purchase_order_id: str
    total_cost: float
    entry_date: date | None = None  # GL posting date; None = today


@dataclass(frozen=True)
class PaymentReceived:
    workspace_id: str
    payment_id: str
    invoice_id: str
    amount: float
    method: str = ""  # cash | mpesa | bank | cheque | card — picks the ledger account
    entry_date: date | None = None  # GL posting date; None = today


@dataclass(frozen=True)
class PaymentMade:
    workspace_id: str
    payment_id: str
    vendor_bill_id: str
    amount: float
    method: str = ""  # cash | mpesa | bank | cheque | card — picks the ledger account
    entry_date: date | None = None  # GL posting date; None = today


@dataclass(frozen=True)
class VendorBillPosted:
    """po_id None = a direct expense bill (rent, utilities...) debited to
    expense_account_id; with a PO the goods already hit Inventory/AP at receipt,
    so only the VAT and any bill-vs-receipt price variance post here."""

    workspace_id: str
    vendor_bill_id: str
    po_id: str | None
    subtotal: float
    tax_total: float
    total: float
    expense_account_id: str | None = None
    price_variance: float = 0.0
    entry_date: date | None = None


@dataclass(frozen=True)
class CreditNoteIssued:
    workspace_id: str
    credit_note_id: str
    invoice_id: str | None
    subtotal: float
    tax_total: float
    total: float
    restock_cost: float = 0.0  # COGS reversed for goods returned to stock
    entry_date: date | None = None


@dataclass(frozen=True)
class PayrollRunApproved:
    workspace_id: str
    run_id: str
    entry_date: date
    gross_pay: float
    paye: float
    nssf_employee: float
    nssf_employer: float
    shif: float
    housing_levy_employee: float
    housing_levy_employer: float
    nita: float
    other_deductions: float
    net_pay: float


@dataclass(frozen=True)
class PayrollRunPaid:
    workspace_id: str
    run_id: str
    entry_date: date
    net_pay: float


@dataclass(frozen=True)
class AssetAcquired:
    workspace_id: str
    asset_id: str
    cost: float
    funding: str  # "cash" | "payable" | "opening"
    entry_date: date
    # Migrating an existing asset onto the system: depreciation it had already
    # accumulated before go-live (posted against Opening Balance Equity).
    opening_accumulated_depreciation: float = 0.0


@dataclass(frozen=True)
class DepreciationPosted:
    """One GL entry for a whole depreciation run, not one per asset."""

    workspace_id: str
    reference: str  # the run's id
    amount: float
    period: str  # "YYYY-MM"
    entry_date: date


@dataclass(frozen=True)
class AssetDisposed:
    workspace_id: str
    asset_id: str
    cost: float
    accumulated_depreciation: float
    proceeds: float
    entry_date: date


@dataclass(frozen=True)
class InvoiceVoided:
    """Only unpaid, uncredited invoices can be voided; accounting reverses the
    invoice's original journal entry dated `entry_date`."""

    workspace_id: str
    invoice_id: str
    entry_date: date


@dataclass(frozen=True)
class ProductionCompleted:
    """Component cost moves Inventory -> Inventory (value-neutral, no entry);
    labour/overhead added to the finished goods is capitalised into
    Inventory against Production Costs Applied."""

    workspace_id: str
    work_order_id: str
    conversion_cost: float
    entry_date: date


@dataclass(frozen=True)
class YearClosed:
    workspace_id: str
    year: int
