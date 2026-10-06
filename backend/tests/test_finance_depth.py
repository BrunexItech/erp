"""Payment-method ledgers, bank reconciliation, VAT return, year-end close,
activity log and the eTIMS seam."""

import io
import uuid
from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import select

from app.core.activity import ActivityLog
from app.core.db import set_tenant_context
from app.modules.accounting.banking import BankingService, parse_date
from app.modules.accounting.models import Account
from app.modules.accounting.service import AccountingService, JournalLineInput
from app.modules.crm.models import PartyKind
from app.modules.crm.schemas import PartyCreate
from app.modules.crm.service import CrmService
from app.modules.platform.models import Workspace
from app.modules.purchasing.schemas import VendorBillCreate
from app.modules.purchasing.service import PurchasingService
from app.modules.sales.schemas import CreditNoteCreate, CreditNoteLineInput, DocumentLineInput, InvoiceCreate
from app.modules.sales.service import SalesService


def _csv(text: str) -> UploadFile:
    return UploadFile(filename="statement.csv", file=io.BytesIO(text.encode()))


async def _customer_invoice(session, workspace_id, amount="1000", **kwargs):
    crm = CrmService(session, workspace_id)
    customer = await crm.create_party(PartyCreate(name=f"Cust {uuid.uuid4().hex[:4]}", kind=PartyKind.customer))
    sales = SalesService(session, workspace_id)
    invoice = await sales.create_invoice(
        InvoiceCreate(party_id=customer.id, lines=[DocumentLineInput(description="Work", qty=Decimal("1"), unit_price=Decimal(amount), tax_rate=Decimal("0.16"))], **kwargs)
    )
    return sales, invoice


async def test_payments_land_in_the_ledger_for_their_method(session, workspace_id):
    accounting = AccountingService(session, workspace_id)
    await accounting.seed_default_accounts()
    sales, invoice = await _customer_invoice(session, workspace_id, "1000")  # total 1,160
    await sales.record_payment(invoice.id, Decimal("500"), "mpesa")
    await sales.record_payment(invoice.id, Decimal("400"), "bank")
    await sales.record_payment(invoice.id, Decimal("260"), "cash")
    assert await accounting.balance_for_key("MPESA") == Decimal("500")
    assert await accounting.balance_for_key("BANK") == Decimal("400")
    assert await accounting.balance_for_key("CASH") == Decimal("260")

    # A workspace can point a method at its own account (e.g. a second bank).
    kcb = await accounting.create_account(code="1030", name="KCB Current", type="asset", subtype="bank", description="")
    await accounting.set_payment_accounts({"bank": kcb.id})
    _, second = await _customer_invoice(session, workspace_id, "100")
    await sales.record_payment(second.id, Decimal("116"), "bank")
    assert await accounting.account_balance(kcb.id) == Decimal("116")


def test_statement_date_formats():
    assert parse_date("2026-03-31") == date(2026, 3, 31)
    assert parse_date("31/03/2026") == date(2026, 3, 31)
    assert parse_date("31 Mar 2026") == date(2026, 3, 31)
    with pytest.raises(ValueError):
        parse_date("yesterday")


async def test_bank_reconciliation(session, workspace_id):
    accounting = AccountingService(session, workspace_id)
    await accounting.seed_default_accounts()
    banking = BankingService(session, workspace_id)
    today = date.today()
    sales, invoice = await _customer_invoice(session, workspace_id, "1000")
    await sales.record_payment(invoice.id, Decimal("1160"), "bank", payment_date=today)
    _, other = await _customer_invoice(session, workspace_id, "500")
    await sales.record_payment(other.id, Decimal("580"), "bank", payment_date=today)  # not on the statement yet

    bank = next(a for a in await banking.accounts() if a["code"] == "1020")
    assert bank["book_balance"] == Decimal("1740")

    statement = (
        "Date,Details,Reference,Debit,Credit\n"
        f"{(today + timedelta(days=1)).strftime('%d/%m/%Y')},Deposit Acme,FT1,,\"1,160.00\"\n"
        f"{today.strftime('%d/%m/%Y')},Monthly charges,,350.00,\n"
        f"{today.strftime('%d/%m/%Y')},Bad row,,abc,\n"
    )
    result = await banking.import_statement(bank["id"], _csv(statement))
    assert (result["created"], result["skipped"], result["auto_matched"]) == (2, 1, 1)
    # Importing the same statement again adds nothing.
    again = await banking.import_statement(bank["id"], _csv(statement))
    assert again["created"] == 0

    view = await banking.workspace(bank["id"])
    statuses = {l["description"]: l["status"] for l in view["statement_lines"]}
    assert statuses == {"Deposit Acme": "matched", "Monthly charges": "unmatched"}
    assert [l["amount"] for l in view["book_lines"]] == [Decimal("580")]  # uncleared deposit
    assert view["expected_statement_balance"] == Decimal("1740") - Decimal("580") - Decimal("350")

    # Book the bank charge straight from the statement line.
    charge = next(l for l in view["statement_lines"] if l["description"] == "Monthly charges")
    expense = next(a for a in await accounting.accounts.list() if a.code == "6000")
    await banking.create_entry(charge["id"], expense.id, "Bank charges")
    assert await accounting.balance_for_key("BANK") == Decimal("1390")
    assert await accounting.balance_for_key("GENERAL_EXPENSE") == Decimal("350")
    view = await banking.workspace(bank["id"])
    assert view["unmatched_statement_total"] == Decimal("0")

    # Amounts must agree to match by hand.
    await banking.import_statement(bank["id"], _csv(f"date,description,amount\n{today.isoformat()},Deposit,575\n"))
    view = await banking.workspace(bank["id"])
    stray = next(l for l in view["statement_lines"] if l["status"] == "unmatched")
    with pytest.raises(HTTPException):
        await banking.match(stray["id"], view["book_lines"][0]["id"])


async def test_vat_return(session, workspace_id):
    await AccountingService(session, workspace_id).seed_default_accounts()
    today = date.today()
    sales, invoice = await _customer_invoice(session, workspace_id, "10000")  # VAT 1,600
    await sales.create_invoice(
        InvoiceCreate(party_id=invoice.party_id, lines=[DocumentLineInput(description="Exempt books", qty=Decimal("1"), unit_price=Decimal("2000"))])
    )
    line = (await sales.invoice_detail(invoice.id))["lines"][0]
    await sales.create_credit_note(CreditNoteCreate(invoice_id=invoice.id, lines=[CreditNoteLineInput(invoice_line_id=line.id, qty=Decimal("0.1"))]))

    vendor = await CrmService(session, workspace_id).create_party(PartyCreate(name="Supplier", kind=PartyKind.vendor, tax_id="P000111222A"))
    purchasing = PurchasingService(session, workspace_id)
    await purchasing.create_vendor_bill(VendorBillCreate(party_id=vendor.id, subtotal=Decimal("5000"), tax_total=Decimal("800")))

    output = await sales.vat_output(today.replace(day=1), today)
    rates = {r["rate"]: r for r in output["by_rate"]}
    assert rates[Decimal("0.1600")]["vat"] == Decimal("1600.00")
    assert rates[Decimal("0.0000")]["taxable"] == Decimal("2000.00")
    assert output["output_vat"] == Decimal("1440.00")  # 1,600 less 160 credited

    purchases = await purchasing.vat_input(today.replace(day=1), today)
    assert purchases["input_vat"] == Decimal("800") and purchases["bills"][0]["vendor_pin"] == "P000111222A"


async def test_year_end_close_and_reopen(session, workspace_id):
    accounting = AccountingService(session, workspace_id)
    await accounting.seed_default_accounts()
    last_year = date.today().year - 1
    await accounting.post_journal_entry(
        entry_date=date(last_year, 6, 30), memo="Sales", source_type="manual", source_id="t",
        lines=[JournalLineInput("CASH", debit=Decimal("900")), JournalLineInput("REVENUE", credit=Decimal("900"))],
    )
    await accounting.post_journal_entry(
        entry_date=date(last_year, 7, 31), memo="Rent", source_type="manual", source_id="t",
        lines=[JournalLineInput("GENERAL_EXPENSE", debit=Decimal("300")), JournalLineInput("CASH", credit=Decimal("300"))],
    )

    with pytest.raises(HTTPException):  # the current year isn't over
        await accounting.close_year(date.today().year)

    result = await accounting.close_year(last_year)
    assert result["profit"] == Decimal("600")
    assert await accounting.balance_for_key("RETAINED_EARNINGS") == Decimal("600")
    assert await accounting.balance_for_key("REVENUE") == Decimal("0")

    # The closed year still reports its real result, and the sheet balances.
    pnl = await accounting.profit_and_loss(date(last_year, 1, 1), date(last_year, 12, 31))
    assert pnl["net_profit"] == Decimal("600")
    assert (await accounting.balance_sheet(date.today()))["balanced"]

    with pytest.raises(HTTPException):  # books are locked through year end
        await accounting.post_journal_entry(
            entry_date=date(last_year, 12, 1), memo="Late", source_type="manual", source_id="t",
            lines=[JournalLineInput("CASH", debit=Decimal("1")), JournalLineInput("REVENUE", credit=Decimal("1"))],
        )
    await session.rollback()
    accounting = AccountingService(session, workspace_id)  # as a new request would
    with pytest.raises(HTTPException):
        await accounting.close_year(last_year)  # not twice
    await session.rollback()
    accounting = AccountingService(session, workspace_id)

    await accounting.reopen_year(last_year)
    assert await accounting.balance_for_key("REVENUE") == Decimal("900")
    assert await accounting.closed_years() == []
    pnl = await accounting.profit_and_loss(date(last_year, 1, 1), date(last_year, 12, 31))
    assert pnl["net_profit"] == Decimal("600")
    assert (await accounting.get_settings()).lock_date is None


async def test_etims_test_mode_and_failure_never_blocks_the_sale(session, workspace_id):
    await AccountingService(session, workspace_id).seed_default_accounts()
    workspace = (await session.execute(select(Workspace).where(Workspace.id == workspace_id))).scalar_one()

    _, plain = await _customer_invoice(session, workspace_id)
    assert plain.etims_status == ""  # eTIMS off by default

    workspace.etims_mode = "test"
    await session.commit()
    sales, invoice = await _customer_invoice(session, workspace_id)
    assert invoice.etims_status == "submitted" and invoice.etims_reference.startswith("TEST-")
    pdf = await sales.invoice_pdf(invoice.id)
    assert pdf[:4] == b"%PDF"

    workspace.etims_mode = "live"  # not connected yet
    await session.commit()
    _, pending = await _customer_invoice(session, workspace_id)
    assert pending.etims_status == "failed" and "credentials" in pending.etims_error
    assert pending.invoice_no.startswith("INV-")  # the sale itself went through


async def test_activity_log_records_changes_not_reads(session):
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test/api/v1") as client:
        email = f"log-{uuid.uuid4().hex[:8]}@example.com"
        tokens = (await client.post("/auth/signup", json={"email": email, "password": "Owner1234!", "workspace_name": "Log Co"})).json()
        auth = {"Authorization": f"Bearer {tokens['access_token']}"}
        workspace_id = (await client.get("/workspaces", headers=auth)).json()[0]["id"]
        auth["X-Workspace-Id"] = workspace_id

        await client.get("/crm/parties", headers=auth)
        await client.post("/crm/parties", headers=auth, json={"name": "Logged Customer", "kind": "customer"})
        await client.post("/crm/parties", headers=auth, json={})  # 422: nothing changed, nothing logged

        log = (await client.get("/workspaces/activity", headers=auth)).json()
        assert [(e["action"], e["area"], e["user"]) for e in log] == [("Create party", "crm", email)]

    await set_tenant_context(session, workspace_id)
    rows = (await session.execute(select(ActivityLog).where(ActivityLog.workspace_id == workspace_id))).scalars().all()
    assert len(rows) == 1 and rows[0].method == "POST"
    assert Account.__tablename__ == "accounts"
