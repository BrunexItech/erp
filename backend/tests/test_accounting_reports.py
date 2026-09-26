from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.modules.accounting.service import AccountingService, JournalLineInput
from app.modules.crm.models import PartyKind
from app.modules.crm.schemas import PartyCreate
from app.modules.crm.service import CrmService
from app.modules.inventory import valuation
from app.modules.inventory.schemas import ProductCreate, WarehouseCreate
from app.modules.inventory.service import InventoryService
from app.modules.purchasing.schemas import VendorBillCreate
from app.modules.purchasing.service import PurchasingService
from app.modules.sales.schemas import InvoiceCreate
from app.modules.sales.service import SalesService


async def _capital(accounting: AccountingService, amount: str, on: date | None = None):
    await accounting.post_journal_entry(
        entry_date=on or date.today(),
        memo="Owner capital",
        source_type="manual",
        source_id="test",
        lines=[
            JournalLineInput("CASH", debit=Decimal(amount)),
            JournalLineInput("OPENING_EQUITY", credit=Decimal(amount)),
        ],
    )


async def test_profit_and_loss_and_balance_sheet_tie_out(session, workspace_id):
    accounting = AccountingService(session, workspace_id)
    await accounting.seed_default_accounts()
    crm = CrmService(session, workspace_id)
    customer = await crm.create_party(PartyCreate(name="C", kind=PartyKind.customer))
    vendor = await crm.create_party(PartyCreate(name="Landlord", kind=PartyKind.vendor))

    await _capital(accounting, "10000")
    await SalesService(session, workspace_id).create_invoice(
        InvoiceCreate(party_id=customer.id, subtotal=Decimal("5000"), tax_total=Decimal("800"))
    )
    # Direct expense bill (no PO) — must hit the GL, not only the AP sub-ledger.
    await PurchasingService(session, workspace_id).create_vendor_bill(
        VendorBillCreate(party_id=vendor.id, subtotal=Decimal("1200"), tax_total=Decimal("192"))
    )

    today = date.today()
    pnl = await accounting.profit_and_loss(today.replace(day=1), today)
    assert pnl["total_revenue"] == Decimal("5000")
    assert pnl["total_operating_expenses"] == Decimal("1200")
    assert pnl["net_profit"] == Decimal("3800")

    sheet = await accounting.balance_sheet(today)
    assert sheet["balanced"], sheet
    # Assets: cash 10000 + AR 5800 + input VAT 192
    assert sheet["total_assets"] == Decimal("15992")
    # Liabilities: output VAT 800 + AP 1392
    assert sheet["total_liabilities"] == Decimal("2192")
    assert sheet["total_equity"] == Decimal("13800")

    ap_balance = await PurchasingService(session, workspace_id).vendor_balance(vendor.id)
    assert await accounting.balance_for_key("AP") == ap_balance == Decimal("1392")


async def test_general_ledger_running_balance(session, workspace_id):
    accounting = AccountingService(session, workspace_id)
    await accounting.seed_default_accounts()
    yesterday = date.today() - timedelta(days=1)
    await _capital(accounting, "100", on=yesterday)
    await _capital(accounting, "50")

    cash = (await accounting.accounts.list())
    cash_id = next(a.id for a in cash if a.code == "1000")
    ledger = await accounting.general_ledger(cash_id, date.today(), date.today())
    assert ledger["opening_balance"] == Decimal("100")
    assert ledger["closing_balance"] == Decimal("150")
    assert len(ledger["lines"]) == 1
    assert ledger["lines"][0]["entry_no"].startswith("JE-")


async def test_lock_date_blocks_backdated_postings(session, workspace_id):
    accounting = AccountingService(session, workspace_id)
    await accounting.seed_default_accounts()
    last_month = date.today().replace(day=1) - timedelta(days=1)
    await accounting.update_settings(lock_date=last_month, fiscal_year_start_month=None)

    with pytest.raises(HTTPException) as exc:
        await _capital(accounting, "10", on=last_month)
    assert exc.value.status_code == 409

    await _capital(accounting, "10")  # current period still open


async def test_reversal_nets_to_zero_and_cannot_repeat(session, workspace_id):
    accounting = AccountingService(session, workspace_id)
    await accounting.seed_default_accounts()
    await _capital(accounting, "700")
    entry = (await accounting.list_entries())[0]

    await accounting.reverse_entry(entry["id"], date.today())
    assert await accounting.balance_for_key("CASH") == Decimal("0")

    with pytest.raises(HTTPException):
        await accounting.reverse_entry(entry["id"], date.today())


async def test_unbalanced_entry_rejected(session, workspace_id):
    accounting = AccountingService(session, workspace_id)
    await accounting.seed_default_accounts()
    with pytest.raises(HTTPException) as exc:
        await accounting.post_journal_entry(
            entry_date=date.today(), memo="bad", source_type="manual", source_id="t",
            lines=[JournalLineInput("CASH", debit=Decimal("5")), JournalLineInput("REVENUE", credit=Decimal("4"))],
        )
    assert exc.value.status_code == 400


async def test_stock_adjustment_keeps_inventory_gl_in_sync(session, workspace_id):
    """Before adjustments posted to the GL, a stock-count correction left the
    Inventory account disagreeing with the valuation engine."""
    accounting = AccountingService(session, workspace_id)
    await accounting.seed_default_accounts()
    inventory = InventoryService(session, workspace_id)
    warehouse = await inventory.create_warehouse(WarehouseCreate(name="Main", code="ADJ"))
    product = await inventory.create_product(ProductCreate(sku="ADJ-1", name="Thing"))

    await inventory.record_adjustment(
        product_id=product.id, warehouse_id=warehouse.id,
        qty_delta=Decimal("10"), unit_cost=Decimal("40"), reason="count",
    )
    await inventory.record_adjustment(
        product_id=product.id, warehouse_id=warehouse.id,
        qty_delta=Decimal("-3"), unit_cost=None, reason="damaged",
    )

    physical = await valuation.current_value(session, workspace_id, product, warehouse.id)
    assert physical == Decimal("280")
    assert await accounting.balance_for_key("INVENTORY") == Decimal("280")


async def test_budget_vs_actual(session, workspace_id):
    accounting = AccountingService(session, workspace_id)
    await accounting.seed_default_accounts()
    revenue = next(a for a in await accounting.accounts.list() if a.code == "4000")
    year = date.today().year
    await accounting.set_budget(revenue.id, year, [Decimal("1000")] * 12)

    crm = CrmService(session, workspace_id)
    customer = await crm.create_party(PartyCreate(name="C", kind=PartyKind.customer))
    await SalesService(session, workspace_id).create_invoice(
        InvoiceCreate(party_id=customer.id, subtotal=Decimal("1500"))
    )

    rows = await accounting.budget_vs_actual(year)
    row = next(r for r in rows if r["code"] == "4000")
    this_month = row["months"][date.today().month - 1]
    assert this_month["actual"] == Decimal("1500")
    assert this_month["variance"] == Decimal("500")
    assert row["total_budget"] == Decimal("12000")
