"""Event-driven auto-journal-entry map. Other modules never import or call
AccountingService directly to post a transaction — they publish an event (see
core/events.py) and this module turns it into balanced JournalEntry/JournalLine
rows, in the same session/transaction the triggering action used.

This is what makes stock valuation numbers tie to the financial statements rather
than being a cosmetic report: DeliveryConfirmed carries the exact COGS amount
apply_movement() computed, and it is posted here verbatim.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.modules.accounting.service import AccountingService, JournalLineInput

_registered = False


def register_subscribers() -> None:
    """Call once at app startup. Idempotent — safe to call again (e.g. in tests)."""
    global _registered
    if _registered:
        return
    events.subscribe(events.WorkspaceCreated, _on_workspace_created)
    events.subscribe(events.DeliveryConfirmed, _on_delivery_confirmed)
    events.subscribe(events.InvoicePosted, _on_invoice_posted)
    events.subscribe(events.GoodsReceiptPosted, _on_goods_receipt_posted)
    events.subscribe(events.PaymentReceived, _on_payment_received)
    events.subscribe(events.PaymentMade, _on_payment_made)
    events.subscribe(events.StockMovementApplied, _on_stock_movement_applied)
    events.subscribe(events.VendorBillPosted, _on_vendor_bill_posted)
    events.subscribe(events.CreditNoteIssued, _on_credit_note_issued)
    events.subscribe(events.PayrollRunApproved, _on_payroll_run_approved)
    events.subscribe(events.PayrollRunPaid, _on_payroll_run_paid)
    events.subscribe(events.AssetAcquired, _on_asset_acquired)
    events.subscribe(events.DepreciationPosted, _on_depreciation_posted)
    events.subscribe(events.AssetDisposed, _on_asset_disposed)
    events.subscribe(events.InvoiceVoided, _on_invoice_voided)
    events.subscribe(events.ProductionCompleted, _on_production_completed)
    events.subscribe(events.VendorReturnPosted, _on_vendor_return_posted)
    _registered = True


def _d(value: float) -> Decimal:
    return Decimal(str(value))


def _date(value: date | None) -> date:
    return value or date.today()


async def _on_workspace_created(event: events.WorkspaceCreated, session: AsyncSession) -> None:
    await AccountingService(session, event.workspace_id).seed_default_accounts()


async def _on_delivery_confirmed(event: events.DeliveryConfirmed, session: AsyncSession) -> None:
    svc = AccountingService(session, event.workspace_id)
    amount = _d(event.cogs_amount)
    if amount == 0:
        return
    await svc.post_journal_entry(
        entry_date=_date(event.entry_date),
        memo=f"COGS for delivery {event.delivery_id[:8]}",
        source_type="delivery",
        source_id=event.delivery_id,
        lines=[
            JournalLineInput("COGS", debit=amount),
            JournalLineInput("INVENTORY", credit=amount),
        ],
    )


async def _on_invoice_posted(event: events.InvoicePosted, session: AsyncSession) -> None:
    svc = AccountingService(session, event.workspace_id)
    subtotal = _d(event.subtotal)
    tax = _d(event.tax_total)
    total = _d(event.total)

    lines = [JournalLineInput("AR", debit=total), JournalLineInput("REVENUE", credit=subtotal)]
    if tax:
        lines.append(JournalLineInput("TAX_PAYABLE", credit=tax))

    await svc.post_journal_entry(
        entry_date=_date(event.entry_date),
        memo=f"Invoice {event.invoice_id[:8]}",
        source_type="sales_invoice",
        source_id=event.invoice_id,
        lines=lines,
    )


async def _on_goods_receipt_posted(event: events.GoodsReceiptPosted, session: AsyncSession) -> None:
    svc = AccountingService(session, event.workspace_id)
    amount = _d(event.total_cost)
    if amount == 0:
        return
    await svc.post_journal_entry(
        entry_date=_date(event.entry_date),
        memo=f"Goods receipt {event.receipt_id[:8]}",
        source_type="goods_receipt",
        source_id=event.receipt_id,
        lines=[
            JournalLineInput("INVENTORY", debit=amount),
            JournalLineInput("AP", credit=amount),
        ],
    )


async def _on_payment_received(event: events.PaymentReceived, session: AsyncSession) -> None:
    svc = AccountingService(session, event.workspace_id)
    amount = _d(event.amount)
    await svc.post_journal_entry(
        entry_date=_date(event.entry_date),
        memo=f"Payment received for invoice {event.invoice_id[:8]}",
        source_type="payment_received",
        source_id=event.payment_id,
        lines=[
            JournalLineInput(await svc.payment_account(event.method), debit=amount),
            JournalLineInput("AR", credit=amount),
        ],
    )


async def _on_payment_made(event: events.PaymentMade, session: AsyncSession) -> None:
    svc = AccountingService(session, event.workspace_id)
    amount = _d(event.amount)
    await svc.post_journal_entry(
        entry_date=_date(event.entry_date),
        memo=f"Payment made for vendor bill {event.vendor_bill_id[:8]}",
        source_type="payment_made",
        source_id=event.payment_id,
        lines=[
            JournalLineInput("AP", debit=amount),
            JournalLineInput(await svc.payment_account(event.method), credit=amount),
        ],
    )


async def _on_stock_movement_applied(event: events.StockMovementApplied, session: AsyncSession) -> None:
    """Manual adjustments (count variances, damage, write-ups) and opening stock
    change inventory value without any sale or purchase behind them — without
    this, the Inventory GL account drifts away from the valuation engine the
    first time someone corrects a stock count. Sales, receipts, transfers,
    returns and production have their own postings (or are value-neutral)."""
    if event.type not in ("adjustment", "opening"):
        return
    value = abs(_d(event.qty_delta) * _d(event.unit_cost))
    if value == 0:
        return
    svc = AccountingService(session, event.workspace_id)
    offset = "OPENING_EQUITY" if event.type == "opening" else "SHRINKAGE"
    if event.qty_delta > 0:
        lines = [JournalLineInput("INVENTORY", debit=value), JournalLineInput(offset, credit=value)]
    else:
        lines = [JournalLineInput(offset, debit=value), JournalLineInput("INVENTORY", credit=value)]
    await svc.post_journal_entry(
        entry_date=date.today(),
        memo=f"Stock {event.type} ({event.qty_delta:+g} units)",
        source_type=f"stock_{event.type}",
        source_id=event.movement_id,
        lines=lines,
    )


async def _on_vendor_bill_posted(event: events.VendorBillPosted, session: AsyncSession) -> None:
    svc = AccountingService(session, event.workspace_id)
    subtotal = _d(event.subtotal)
    tax = _d(event.tax_total)
    total = _d(event.total)
    variance = _d(event.price_variance)

    if event.po_id is None:
        lines = [
            JournalLineInput(event.expense_account_id or "GENERAL_EXPENSE", debit=subtotal),
            JournalLineInput("INPUT_VAT", debit=tax),
            JournalLineInput("AP", credit=total),
        ]
    else:
        # Receipt already posted Dr Inventory / Cr AP at received cost; top AP up
        # (or down) to the billed amount so the GL agrees with the AP sub-ledger.
        lines = [JournalLineInput("INPUT_VAT", debit=tax)]
        if variance > 0:
            lines.append(JournalLineInput("PURCHASE_PRICE_VARIANCE", debit=variance))
        elif variance < 0:
            lines.append(JournalLineInput("PURCHASE_PRICE_VARIANCE", credit=-variance))
        ap_delta = tax + variance
        if ap_delta > 0:
            lines.append(JournalLineInput("AP", credit=ap_delta))
        elif ap_delta < 0:
            lines.append(JournalLineInput("AP", debit=-ap_delta))
        if not any(l.debit for l in lines):
            return  # bill exactly matches the receipt and carries no VAT

    await svc.post_journal_entry(
        entry_date=_date(event.entry_date),
        memo=f"Vendor bill {event.vendor_bill_id[:8]}",
        source_type="vendor_bill",
        source_id=event.vendor_bill_id,
        lines=lines,
    )


async def _on_credit_note_issued(event: events.CreditNoteIssued, session: AsyncSession) -> None:
    svc = AccountingService(session, event.workspace_id)
    subtotal = _d(event.subtotal)
    tax = _d(event.tax_total)
    total = _d(event.total)
    restock = _d(event.restock_cost)
    lines = [
        JournalLineInput("SALES_RETURNS", debit=subtotal),
        JournalLineInput("TAX_PAYABLE", debit=tax),
        JournalLineInput("AR", credit=total),
    ]
    if restock:
        lines += [JournalLineInput("INVENTORY", debit=restock), JournalLineInput("COGS", credit=restock)]
    await svc.post_journal_entry(
        entry_date=_date(event.entry_date),
        memo=f"Credit note {event.credit_note_id[:8]}",
        source_type="credit_note",
        source_id=event.credit_note_id,
        lines=lines,
    )


async def _on_payroll_run_approved(event: events.PayrollRunApproved, session: AsyncSession) -> None:
    """Accrues the payroll: the full employment cost hits expense, and every
    amount owed — to KRA, NSSF, SHA, the Housing Fund, NITA, third parties and
    the employees themselves — lands in its own liability account until paid."""
    svc = AccountingService(session, event.workspace_id)
    employer_statutory = _d(event.nssf_employer) + _d(event.housing_levy_employer) + _d(event.nita)
    await svc.post_journal_entry(
        entry_date=event.entry_date,
        memo=f"Payroll accrual {event.run_id[:8]}",
        source_type="payroll_run",
        source_id=event.run_id,
        lines=[
            JournalLineInput("SALARIES_EXPENSE", debit=_d(event.gross_pay)),
            JournalLineInput("EMPLOYER_STATUTORY_EXPENSE", debit=employer_statutory),
            JournalLineInput("PAYE_PAYABLE", credit=_d(event.paye)),
            JournalLineInput("NSSF_PAYABLE", credit=_d(event.nssf_employee) + _d(event.nssf_employer)),
            JournalLineInput("SHIF_PAYABLE", credit=_d(event.shif)),
            JournalLineInput(
                "HOUSING_LEVY_PAYABLE",
                credit=_d(event.housing_levy_employee) + _d(event.housing_levy_employer),
            ),
            JournalLineInput("NITA_PAYABLE", credit=_d(event.nita)),
            JournalLineInput("OTHER_DEDUCTIONS_PAYABLE", credit=_d(event.other_deductions)),
            JournalLineInput("NET_PAY_PAYABLE", credit=_d(event.net_pay)),
        ],
    )


async def _on_payroll_run_paid(event: events.PayrollRunPaid, session: AsyncSession) -> None:
    svc = AccountingService(session, event.workspace_id)
    amount = _d(event.net_pay)
    if amount == 0:
        return
    await svc.post_journal_entry(
        entry_date=event.entry_date,
        memo=f"Salaries paid {event.run_id[:8]}",
        source_type="payroll_payment",
        source_id=event.run_id,
        lines=[
            JournalLineInput("NET_PAY_PAYABLE", debit=amount),
            JournalLineInput("CASH", credit=amount),
        ],
    )


async def _on_asset_acquired(event: events.AssetAcquired, session: AsyncSession) -> None:
    svc = AccountingService(session, event.workspace_id)
    cost = _d(event.cost)
    if cost == 0:
        return
    offset = {"cash": "CASH", "payable": "AP", "opening": "OPENING_EQUITY"}.get(event.funding, "CASH")
    lines = [JournalLineInput("FIXED_ASSETS", debit=cost), JournalLineInput(offset, credit=cost)]
    accumulated = _d(event.opening_accumulated_depreciation)
    if accumulated:
        lines += [
            JournalLineInput("OPENING_EQUITY", debit=accumulated),
            JournalLineInput("ACCUM_DEPRECIATION", credit=accumulated),
        ]
    await svc.post_journal_entry(
        entry_date=event.entry_date,
        memo=f"Asset acquisition {event.asset_id[:8]}",
        source_type="asset_acquisition",
        source_id=event.asset_id,
        lines=lines,
    )


async def _on_depreciation_posted(event: events.DepreciationPosted, session: AsyncSession) -> None:
    svc = AccountingService(session, event.workspace_id)
    amount = _d(event.amount)
    if amount == 0:
        return
    await svc.post_journal_entry(
        entry_date=event.entry_date,
        memo=f"Depreciation {event.period}",
        source_type="depreciation",
        source_id=event.reference,
        lines=[
            JournalLineInput("DEPRECIATION_EXPENSE", debit=amount),
            JournalLineInput("ACCUM_DEPRECIATION", credit=amount),
        ],
    )


async def _on_asset_disposed(event: events.AssetDisposed, session: AsyncSession) -> None:
    """Removes the asset's cost and accumulated depreciation from the books; the
    difference between net book value and sale proceeds is the gain or loss."""
    svc = AccountingService(session, event.workspace_id)
    cost = _d(event.cost)
    accumulated = _d(event.accumulated_depreciation)
    proceeds = _d(event.proceeds)
    gain = proceeds - (cost - accumulated)
    lines = [
        JournalLineInput("CASH", debit=proceeds),
        JournalLineInput("ACCUM_DEPRECIATION", debit=accumulated),
        JournalLineInput("FIXED_ASSETS", credit=cost),
    ]
    if gain > 0:
        lines.append(JournalLineInput("GAIN_ON_DISPOSAL", credit=gain))
    elif gain < 0:
        lines.append(JournalLineInput("GAIN_ON_DISPOSAL", debit=-gain))
    await svc.post_journal_entry(
        entry_date=event.entry_date,
        memo=f"Asset disposal {event.asset_id[:8]}",
        source_type="asset_disposal",
        source_id=event.asset_id,
        lines=lines,
    )


async def _on_invoice_voided(event: events.InvoiceVoided, session: AsyncSession) -> None:
    svc = AccountingService(session, event.workspace_id)
    await svc.reverse_by_source("sales_invoice", event.invoice_id, event.entry_date, "Invoice voided")


async def _on_production_completed(event: events.ProductionCompleted, session: AsyncSession) -> None:
    amount = _d(event.conversion_cost)
    if amount == 0:
        return
    svc = AccountingService(session, event.workspace_id)
    await svc.post_journal_entry(
        entry_date=event.entry_date,
        memo=f"Production labour/overhead {event.work_order_id[:8]}",
        source_type="work_order",
        source_id=event.work_order_id,
        lines=[
            JournalLineInput("INVENTORY", debit=amount),
            JournalLineInput("PRODUCTION_COSTS_APPLIED", credit=amount),
        ],
    )


async def _on_vendor_return_posted(event: events.VendorReturnPosted, session: AsyncSession) -> None:
    svc = AccountingService(session, event.workspace_id)
    subtotal, tax, total, cost = _d(event.subtotal), _d(event.tax_total), _d(event.total), _d(event.stock_cost)
    lines = [
        JournalLineInput("AP", debit=total),
        JournalLineInput("INVENTORY", credit=cost),
        JournalLineInput("INPUT_VAT", credit=tax),  # VAT claimed on the purchase is given back
    ]
    variance = subtotal - cost  # credited more (or less) than the goods were carried at
    if variance > 0:
        lines.append(JournalLineInput("PURCHASE_PRICE_VARIANCE", credit=variance))
    elif variance < 0:
        lines.append(JournalLineInput("PURCHASE_PRICE_VARIANCE", debit=-variance))
    await svc.post_journal_entry(
        entry_date=event.entry_date,
        memo=f"Return to supplier {event.debit_note_id[:8]}",
        source_type="vendor_return",
        source_id=event.debit_note_id,
        lines=lines,
    )
