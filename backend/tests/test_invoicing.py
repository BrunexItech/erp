import os
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.modules.accounting.service import AccountingService
from app.modules.crm.models import PartyKind
from app.modules.crm.schemas import PartyCreate
from app.modules.crm.service import CrmService
from app.modules.inventory import valuation
from app.modules.inventory.schemas import ProductCreate, WarehouseCreate
from app.modules.inventory.service import InventoryService
from app.modules.platform.schemas import BrandingUpdate
from app.modules.platform.service import PlatformService
from app.modules.sales.documents import amount_in_words
from app.modules.sales.models import InvoiceStatus, QuoteStatus
from app.modules.sales.schemas import (
    CreditNoteCreate,
    CreditNoteLineInput,
    DocumentLineInput,
    InvoiceCreate,
    QuoteConvert,
    QuoteCreate,
)
from app.modules.sales.service import SalesService


async def _setup(session, workspace_id):
    await AccountingService(session, workspace_id).seed_default_accounts()
    crm = CrmService(session, workspace_id)
    customer = await crm.create_party(
        PartyCreate(
            name="Acme Traders Ltd", kind=PartyKind.customer, is_company=True, tax_id="P051234567X",
            email="accounts@acme.co.ke", phone="+254 722 000 111",
            billing_address="Moi Avenue, Nairobi",
        )
    )
    inventory = InventoryService(session, workspace_id)
    warehouse = await inventory.create_warehouse(WarehouseCreate(name="Main", code="MAIN"))
    product = await inventory.create_product(ProductCreate(sku="CEM-50", name="Cement 50kg"))
    await inventory.record_adjustment(
        product_id=product.id, warehouse_id=warehouse.id, qty_delta=Decimal("100"),
        unit_cost=Decimal("600"), reason="opening", is_opening=True,
    )
    return customer, warehouse, product


async def test_itemized_invoice_with_discount_rounds_per_line(session, workspace_id):
    customer, _, product = await _setup(session, workspace_id)
    sales = SalesService(session, workspace_id)
    invoice = await sales.create_invoice(
        InvoiceCreate(
            party_id=customer.id,
            lines=[
                DocumentLineInput(product_id=product.id, qty=Decimal("3"), unit_price=Decimal("850"),
                                  discount_pct=Decimal("10"), tax_rate=Decimal("0.16")),
                DocumentLineInput(description="Delivery to site", qty=Decimal("1"),
                                  unit_price=Decimal("1500"), tax_rate=Decimal("0.16")),
            ],
        )
    )
    # 2550 - 255 = 2295 ; +1500 = 3795 net ; VAT 367.20 + 240 = 607.20
    assert invoice.subtotal == Decimal("3795.00")
    assert invoice.discount_total == Decimal("255.00")
    assert invoice.tax_total == Decimal("607.20")
    assert invoice.total == Decimal("4402.20")
    assert invoice.invoice_no.startswith("INV-")
    assert invoice.due_date == invoice.issue_date + timedelta(days=30)

    detail = await sales.invoice_detail(invoice.id)
    assert [l.description for l in detail["lines"]] == ["Cement 50kg", "Delivery to site"]

    # A plain invoice doesn't move stock.
    await session.refresh(product)
    assert product.stock_qty == Decimal("100")


async def test_invoice_and_ship_moves_stock_and_posts_cogs(session, workspace_id):
    customer, warehouse, product = await _setup(session, workspace_id)
    sales = SalesService(session, workspace_id)
    accounting = AccountingService(session, workspace_id)

    invoice = await sales.create_invoice(
        InvoiceCreate(
            party_id=customer.id,
            warehouse_id=warehouse.id,
            lines=[DocumentLineInput(product_id=product.id, qty=Decimal("10"), unit_price=Decimal("850"))],
        )
    )
    assert invoice.order_id is not None
    await session.refresh(product)
    assert product.stock_qty == Decimal("90")

    pnl = await accounting.profit_and_loss(date.today().replace(day=1), date.today())
    assert pnl["total_revenue"] == Decimal("8500")
    assert pnl["total_cost_of_sales"] == Decimal("6000")


async def test_payments_cannot_exceed_balance_and_settle_status(session, workspace_id):
    customer, _, _ = await _setup(session, workspace_id)
    sales = SalesService(session, workspace_id)
    invoice = await sales.create_invoice(
        InvoiceCreate(party_id=customer.id, lines=[DocumentLineInput(description="Consulting", qty=Decimal("1"), unit_price=Decimal("1000"))])
    )
    payment = await sales.record_payment(invoice.id, Decimal("400"), "mpesa", reference="QGH7XYZ12")
    assert payment.document_no.startswith("RCT-")
    await session.refresh(invoice)
    assert invoice.status == InvoiceStatus.partially_paid

    with pytest.raises(HTTPException):
        await sales.record_payment(invoice.id, Decimal("700"), "cash")

    await sales.record_payment(invoice.id, Decimal("600"), "cash")
    await session.refresh(invoice)
    assert invoice.status == InvoiceStatus.paid
    assert sales.balance_due(invoice) == Decimal("0")


async def test_credit_note_with_restock_reverses_revenue_and_cogs(session, workspace_id):
    customer, warehouse, product = await _setup(session, workspace_id)
    sales = SalesService(session, workspace_id)
    accounting = AccountingService(session, workspace_id)

    invoice = await sales.create_invoice(
        InvoiceCreate(
            party_id=customer.id, warehouse_id=warehouse.id,
            lines=[DocumentLineInput(product_id=product.id, qty=Decimal("5"), unit_price=Decimal("1000"), tax_rate=Decimal("0.16"))],
        )
    )
    line = (await sales.invoice_detail(invoice.id))["lines"][0]

    note = await sales.create_credit_note(
        CreditNoteCreate(
            invoice_id=invoice.id, reason="2 bags damaged", restock_warehouse_id=warehouse.id,
            lines=[CreditNoteLineInput(invoice_line_id=line.id, qty=Decimal("2"))],
        )
    )
    assert note.total == Decimal("2320.00")  # 2 x 1000 + 16%
    await session.refresh(product)
    assert product.stock_qty == Decimal("97")

    assert await sales.customer_balance(customer.id) == Decimal("3480.00")  # 5800 - 2320
    await session.refresh(invoice)
    assert sales.balance_due(invoice) == Decimal("3480.00")

    # GL: inventory back in at the original cost, COGS reduced, AR reduced.
    physical = await valuation.current_value(session, workspace_id, product, warehouse.id)
    assert await accounting.balance_for_key("INVENTORY") == physical == Decimal("58200")
    assert await accounting.balance_for_key("AR") == Decimal("3480.00")
    sheet = await accounting.balance_sheet(date.today())
    assert sheet["balanced"]

    with pytest.raises(HTTPException):
        # Can't credit more than what's left.
        await sales.create_credit_note(
            CreditNoteCreate(invoice_id=invoice.id, lines=[CreditNoteLineInput(invoice_line_id=line.id, qty=Decimal("4"))])
        )


async def test_void_reverses_gl_and_blocks_paid_invoices(session, workspace_id):
    customer, _, _ = await _setup(session, workspace_id)
    sales = SalesService(session, workspace_id)
    accounting = AccountingService(session, workspace_id)

    invoice = await sales.create_invoice(
        InvoiceCreate(party_id=customer.id, lines=[DocumentLineInput(description="Setup fee", qty=Decimal("1"), unit_price=Decimal("2000"))])
    )
    await sales.void_invoice(invoice.id, "raised in error")
    assert await accounting.balance_for_key("AR") == Decimal("0")
    assert await sales.customer_balance(customer.id) == Decimal("0")

    paid = await sales.create_invoice(
        InvoiceCreate(party_id=customer.id, lines=[DocumentLineInput(description="Fee", qty=Decimal("1"), unit_price=Decimal("100"))])
    )
    await sales.record_payment(paid.id, Decimal("100"), "cash")
    with pytest.raises(HTTPException):
        await sales.void_invoice(paid.id)


async def test_quote_converts_to_invoice_once(session, workspace_id):
    customer, _, product = await _setup(session, workspace_id)
    sales = SalesService(session, workspace_id)
    quote = await sales.create_quote(
        QuoteCreate(
            party_id=customer.id,
            lines=[DocumentLineInput(product_id=product.id, qty=Decimal("20"), unit_price=Decimal("820"), tax_rate=Decimal("0.16"))],
        )
    )
    assert quote.quote_no.startswith("QT-")
    assert quote.total == Decimal("19024.00")

    invoice = await sales.convert_quote_to_invoice(quote.id, QuoteConvert())
    assert invoice.total == quote.total
    assert invoice.quote_id == quote.id
    await session.refresh(quote)
    assert quote.status == QuoteStatus.converted

    with pytest.raises(HTTPException):
        await sales.convert_quote_to_invoice(quote.id, QuoteConvert())


async def test_statement_and_aging(session, workspace_id):
    customer, _, _ = await _setup(session, workspace_id)
    sales = SalesService(session, workspace_id)
    today = date.today()
    old = await sales.create_invoice(
        InvoiceCreate(
            party_id=customer.id, issue_date=today - timedelta(days=75), due_date=today - timedelta(days=45),
            lines=[DocumentLineInput(description="Old work", qty=Decimal("1"), unit_price=Decimal("5000"))],
        )
    )
    await sales.create_invoice(
        InvoiceCreate(party_id=customer.id, lines=[DocumentLineInput(description="New work", qty=Decimal("1"), unit_price=Decimal("3000"))])
    )
    await sales.record_payment(old.id, Decimal("1000"), "bank", payment_date=today - timedelta(days=10))

    aging = await sales.ar_aging(today)
    row = next(r for r in aging["rows"] if r["party_id"] == customer.id)
    assert row["days_31_60"] == Decimal("4000")
    assert row["current"] == Decimal("3000")
    assert row["total"] == Decimal("7000")

    statement = await sales.customer_statement(customer.id, today - timedelta(days=30), today)
    assert statement["opening_balance"] == Decimal("5000")
    assert statement["closing_balance"] == Decimal("7000")
    assert [l["type"] for l in statement["lines"]] == ["Payment", "Invoice"]


async def test_all_documents_render(session, workspace_id):
    customer, warehouse, product = await _setup(session, workspace_id)
    await PlatformService(session).update_branding(
        workspace_id,
        BrandingUpdate(
            name="Mwangaza Hardware Ltd", address="Kenyatta Avenue, Nakuru", phone="+254 700 123 456",
            billing_email="accounts@mwangaza.co.ke", website="www.mwangaza.co.ke", tax_pin="P051987654Z",
            mpesa_paybill="522533", bank_details="KCB Bank, Nakuru Branch\nA/C 1234567890",
            invoice_terms="Payment due within 30 days. Goods remain our property until paid in full.",
            invoice_footer_note="Thank you for building with Mwangaza.",
        ),
    )
    sales = SalesService(session, workspace_id)
    invoice = await sales.create_invoice(
        InvoiceCreate(
            party_id=customer.id, warehouse_id=warehouse.id, reference="LPO-7781",
            notes="Delivered to Mombasa Road site.",
            lines=[
                DocumentLineInput(product_id=product.id, qty=Decimal("40"), unit_price=Decimal("850"),
                                  discount_pct=Decimal("5"), tax_rate=Decimal("0.16")),
                DocumentLineInput(description="Transport (flat rate)", qty=Decimal("1"),
                                  unit_price=Decimal("3500"), tax_rate=Decimal("0.16")),
            ],
        )
    )
    payment = await sales.record_payment(invoice.id, Decimal("10000"), "mpesa", reference="SGH12KLM9P")
    quote = await sales.create_quote(
        QuoteCreate(party_id=customer.id, lines=[DocumentLineInput(product_id=product.id, qty=Decimal("100"), unit_price=Decimal("800"))])
    )
    note = await sales.create_credit_note(CreditNoteCreate(invoice_id=invoice.id, lines=[
        CreditNoteLineInput(description="Goodwill discount", qty=Decimal("1"), unit_price=Decimal("500"))
    ]))

    documents = {
        "invoice": await sales.invoice_pdf(invoice.id),
        "quote": await sales.quote_pdf(quote.id),
        "credit_note": await sales.credit_note_pdf(note.id),
        "receipt": await sales.receipt_pdf(payment.id),
        "statement": await sales.statement_pdf(customer.id, date.today() - timedelta(days=30), date.today()),
    }
    out_dir = os.environ.get("ERP_PDF_OUT")
    for name, pdf in documents.items():
        assert pdf[:4] == b"%PDF", name
        assert len(pdf) > 1500, name
        if out_dir:
            with open(os.path.join(out_dir, f"{name}.pdf"), "wb") as fh:
                fh.write(pdf)


def test_amount_in_words():
    assert amount_in_words(Decimal("4402.20"), "KES") == (
        "Kenya Shillings Four Thousand Four Hundred and Two and Cents Twenty Only"
    )
    assert amount_in_words(Decimal("1250000"), "KES") == "Kenya Shillings One Million Two Hundred and Fifty Thousand Only"
    assert amount_in_words(Decimal("15"), "USD") == "US Dollars Fifteen Only"
