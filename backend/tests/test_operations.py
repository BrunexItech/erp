"""VAT-inclusive pricing, idempotent POS, stock takes, supplier returns,
recurring invoices, attachments and M-Pesa STK push."""

import io
import json
import uuid
from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi import HTTPException, UploadFile

from app.core import crypto
from app.core.attachments import AttachmentService
from app.modules.accounting.service import AccountingService
from app.modules.crm.models import PartyKind
from app.modules.crm.schemas import PartyCreate
from app.modules.crm.service import CrmService
from app.modules.inventory import valuation
from app.modules.inventory.schemas import ProductCreate, StockCountEntry, WarehouseCreate
from app.modules.inventory.service import InventoryService
from app.modules.purchasing.schemas import VendorBillCreate, VendorReturnCreate, VendorReturnLine
from app.modules.purchasing.service import PurchasingService
from app.modules.sales.mpesa import MpesaService, normalise_phone
from app.modules.sales.schemas import (
    DocumentLineInput,
    InvoiceCreate,
    PosCheckoutLine,
    PosCheckoutRequest,
    QuoteConvert,
    QuoteCreate,
    RecurringInvoiceCreate,
)
from app.modules.sales.service import SalesService, compute_lines

VAT = Decimal("0.16")


async def _shop(session, workspace_id, qty="50", cost="60"):
    await AccountingService(session, workspace_id).seed_default_accounts()
    inventory = InventoryService(session, workspace_id)
    warehouse = await inventory.create_warehouse(WarehouseCreate(name="Shop", code="SHP"))
    product = await inventory.create_product(ProductCreate(sku=f"P-{uuid.uuid4().hex[:5]}", name="Soda", tax_rate=VAT, low_stock_threshold=Decimal("10")))
    await inventory.record_adjustment(product_id=product.id, warehouse_id=warehouse.id, qty_delta=Decimal(qty), unit_cost=Decimal(cost), reason="opening", is_opening=True)
    customer = await CrmService(session, workspace_id).create_party(PartyCreate(name="Cust", kind=PartyKind.customer, email="c@example.com"))
    return inventory, warehouse, product, customer


def test_vat_inclusive_lines_add_up_to_the_shelf_price():
    lines = [DocumentLineInput(description="Item", qty=Decimal("3"), unit_price=Decimal("99"), tax_rate=VAT)]
    computed, totals = compute_lines(lines, {}, prices_include_tax=True)
    assert totals.total == Decimal("297.00")  # exactly 3 x 99, VAT taken out not added on
    assert totals.tax_total == Decimal("40.97") and totals.subtotal == Decimal("256.03")
    assert computed[0].unit_price == Decimal("85.3448")

    _, exclusive = compute_lines(lines, {}, prices_include_tax=False)
    assert exclusive.total == Decimal("344.52")

    # Zero-rated lines are unaffected either way.
    _, zero = compute_lines([DocumentLineInput(description="Books", qty=Decimal("2"), unit_price=Decimal("50"))], {}, True)
    assert zero.total == Decimal("100.00") and zero.tax_total == Decimal("0")


async def test_inclusive_quote_converts_without_a_rounding_cent(session, workspace_id):
    _, _, product, customer = await _shop(session, workspace_id)
    sales = SalesService(session, workspace_id)
    quote = await sales.create_quote(
        QuoteCreate(party_id=customer.id, prices_include_tax=True, lines=[DocumentLineInput(product_id=product.id, qty=Decimal("3"), unit_price=Decimal("99"), tax_rate=VAT)])
    )
    assert quote.total == Decimal("297.00")
    invoice = await sales.convert_quote_to_invoice(quote.id, QuoteConvert())
    assert (invoice.total, invoice.tax_total) == (quote.total, quote.tax_total)


async def test_pos_sale_is_not_repeated_when_the_till_retries(session, workspace_id):
    _, warehouse, product, _ = await _shop(session, workspace_id)
    sales = SalesService(session, workspace_id)
    request = PosCheckoutRequest(
        warehouse_id=warehouse.id, client_ref="till-1:abc123", prices_include_tax=True,
        lines=[PosCheckoutLine(product_id=product.id, qty=Decimal("2"), unit_price=Decimal("116"), tax_rate=VAT)],
    )
    first, _, payment = await sales.pos_checkout(request)
    assert first.total == Decimal("232.00") and first.tax_total == Decimal("32.00")
    again, _, payment_again = await sales.pos_checkout(request)  # e.g. connection dropped before the reply arrived
    assert again.id == first.id and payment_again.id == payment.id
    await session.refresh(product)
    assert product.stock_qty == Decimal("48")  # sold once, not twice


async def test_stock_take_adjusts_to_the_count_and_the_ledger(session, workspace_id):
    inventory, warehouse, product, _ = await _shop(session, workspace_id)
    accounting = AccountingService(session, workspace_id)
    count = await inventory.start_count(warehouse.id, None, "Month end")
    detail = await inventory.count_detail(count.id)
    assert count.count_no.startswith("SC-") and detail["lines"][0]["system_qty"] == Decimal("50")

    with pytest.raises(HTTPException):  # nothing counted yet
        await inventory.post_count(count.id)
    await session.rollback()
    inventory = InventoryService(session, workspace_id)
    for row in (product, warehouse, count):  # the rollback expired them
        await session.refresh(row)

    # Two units sell after the sheet was printed, then the shelf is counted at 45.
    await inventory.record_adjustment(product_id=product.id, warehouse_id=warehouse.id, qty_delta=Decimal("-2"), unit_cost=None, reason="sold meanwhile")
    await inventory.save_count(count.id, [StockCountEntry(line_id=detail["lines"][0]["id"], counted_qty=Decimal("45"))])
    result = await inventory.post_count(count.id)
    assert result["adjusted_lines"] == 1 and result["variance_value"] == Decimal("-180")  # 3 missing (not 5) x 60

    await session.refresh(product)
    assert product.stock_qty == Decimal("45")
    assert await accounting.balance_for_key("INVENTORY") == await valuation.current_value(session, workspace_id, product, warehouse.id)
    with pytest.raises(HTTPException):  # a posted count is final
        await inventory.post_count(count.id)
    await session.rollback()
    await session.refresh(product)

    reorder = await InventoryService(session, workspace_id).reorder_report()
    assert reorder == []  # 45 on hand, reorder level 10


async def test_return_to_supplier(session, workspace_id):
    inventory, warehouse, product, _ = await _shop(session, workspace_id, qty="20", cost="100")
    accounting = AccountingService(session, workspace_id)
    vendor = await CrmService(session, workspace_id).create_party(PartyCreate(name="Supplier", kind=PartyKind.vendor))
    purchasing = PurchasingService(session, workspace_id)
    bill = await purchasing.create_vendor_bill(VendorBillCreate(party_id=vendor.id, subtotal=Decimal("2000"), tax_total=Decimal("320")))

    note = await purchasing.return_to_vendor(
        VendorReturnCreate(vendor_bill_id=bill.id, warehouse_id=warehouse.id, reason="Damaged", tax_rate=VAT,
                           lines=[VendorReturnLine(product_id=product.id, qty=Decimal("5"), unit_price=Decimal("100"))])
    )
    assert note.debit_note_no.startswith("DN-") and note.total == Decimal("580.00")
    await session.refresh(product)
    assert product.stock_qty == Decimal("15")
    assert await purchasing.vendor_balance(vendor.id) == Decimal("1740.00")  # 2,320 - 580
    assert await accounting.balance_for_key("AP") == Decimal("1740.00")  # ledger agrees with the supplier balance
    assert await accounting.balance_for_key("INVENTORY") == Decimal("1500")
    assert (await accounting.balance_sheet(date.today()))["balanced"]

    # Paying the rest settles the bill; you can't pay or return more than is owed.
    with pytest.raises(HTTPException):
        await purchasing.record_payment(bill.id, Decimal("2000"), "bank")
    await session.rollback()
    await session.refresh(bill)
    purchasing = PurchasingService(session, workspace_id)
    await purchasing.record_payment(bill.id, Decimal("1740"), "bank")
    await session.refresh(bill)
    assert bill.status.value == "paid"


async def test_recurring_invoice_catches_up_and_stops(session, workspace_id):
    _, _, _, customer = await _shop(session, workspace_id)
    sales = SalesService(session, workspace_id)
    today = date.today()
    start = SalesService._advance(SalesService._advance(today, "monthly"), "monthly")  # dummy use to prove forward maths
    assert start > today

    first_due = (today.replace(day=1) - timedelta(days=1)).replace(day=1)  # the 1st of last month
    template = await sales.create_recurring(
        RecurringInvoiceCreate(
            party_id=customer.id, name="Monthly retainer", frequency="monthly", next_date=first_due, end_date=today,
            lines=[DocumentLineInput(description="Retainer", qty=Decimal("1"), unit_price=Decimal("10000"), tax_rate=VAT)],
        )
    )
    raised = await sales.run_recurring(today)
    assert [i.issue_date for i in raised] == [first_due, today.replace(day=1)]  # last month's and this month's
    assert all(i.total == Decimal("11600.00") for i in raised)
    assert await sales.run_recurring(today) == []  # nothing more due
    await session.refresh(template)
    assert template.invoices_raised == 2 and template.is_active is False  # next would be past end_date


async def test_attachments_are_private_and_type_checked(session, workspace_id, tmp_path, monkeypatch):
    from app.core import attachments

    monkeypatch.setattr(attachments.settings, "media_root", str(tmp_path))
    service = AttachmentService(session, workspace_id)
    pdf = UploadFile(filename="../../etc/supplier invoice.pdf", file=io.BytesIO(b"%PDF-1.4 scan"))
    saved = await service.add("vendor_bill", "bill-1", pdf, "user-1")
    assert saved.filename == "supplier invoice.pdf"  # path stripped
    record, path = await service.path(saved.id)
    assert path.read_bytes() == b"%PDF-1.4 scan" and path.parent == tmp_path / "attachments" / workspace_id
    assert path.name != saved.filename  # stored under a random name

    with pytest.raises(HTTPException):
        await service.add("vendor_bill", "bill-1", UploadFile(filename="run.exe", file=io.BytesIO(b"MZ")), "user-1")
    with pytest.raises(HTTPException):
        await service.add("secrets", "x", UploadFile(filename="a.pdf", file=io.BytesIO(b"x")), "user-1")

    # Another business can't reach it, even with the id.
    with pytest.raises(HTTPException):
        await AttachmentService(session, "some-other-workspace").path(saved.id)

    await service.delete(saved.id)
    assert not path.exists()


def test_phone_numbers_and_secret_encryption():
    assert normalise_phone("0712 345 678") == "254712345678"
    assert normalise_phone("+254 112 345678") == "254112345678"
    assert normalise_phone("712345678") == "254712345678"
    with pytest.raises(HTTPException):
        normalise_phone("12345")
    token = crypto.encrypt("super-secret-key")
    assert token != "super-secret-key" and crypto.decrypt(token) == "super-secret-key"
    assert crypto.mask("super-secret-key") == "••••-key"


async def test_mpesa_stk_push_pays_the_invoice_on_callback(session, workspace_id):
    _, _, _, customer = await _shop(session, workspace_id)
    sales = SalesService(session, workspace_id)
    accounting = AccountingService(session, workspace_id)
    invoice = await sales.create_invoice(
        InvoiceCreate(party_id=customer.id, lines=[DocumentLineInput(description="Goods", qty=Decimal("1"), unit_price=Decimal("1000"), tax_rate=VAT)])
    )
    sent: dict = {}

    def safaricom(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/v1/generate":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": "3599"})
        sent.update(json.loads(request.content))
        return httpx.Response(200, json={"MerchantRequestID": "m-1", "CheckoutRequestID": "ws_CO_1", "ResponseCode": "0", "ResponseDescription": "Success"})

    mpesa = MpesaService(session, workspace_id, transport=httpx.MockTransport(safaricom))
    with pytest.raises(HTTPException):  # not set up yet
        await mpesa.initiate(phone="0712345678", amount=Decimal("1160"), invoice_id=invoice.id, reference=invoice.invoice_no, user_id="u")
    await session.rollback()
    mpesa = MpesaService(session, workspace_id, transport=httpx.MockTransport(safaricom))
    for row in (invoice, customer):
        await session.refresh(row)

    view = await mpesa.save_config({"environment": "sandbox", "shortcode": "174379", "consumer_key": "ck-12345678", "consumer_secret": "cs-12345678", "passkey": "pk-12345678", "is_active": True})
    assert view["configured"] and view["consumer_secret"] == "••••5678"  # secrets are never returned

    request = await mpesa.initiate(phone="0712 345 678", amount=Decimal("1160"), invoice_id=invoice.id, reference=invoice.invoice_no, user_id="u")
    assert request.status == "pending" and request.checkout_request_id == "ws_CO_1"
    assert sent["PhoneNumber"] == "254712345678" and sent["Amount"] == 1160 and sent["TransactionType"] == "CustomerPayBillOnline"
    token = sent["CallBackURL"].rsplit("/", 1)[1]
    assert f"/api/v1/mpesa/callback/{workspace_id}/" in sent["CallBackURL"]

    await mpesa.handle_callback("wrong-token", {"Body": {"stkCallback": {"ResultCode": 0}}})
    assert (await mpesa.status_of(request.id)).status == "pending"  # a guessed address does nothing

    success = {"Body": {"stkCallback": {"ResultCode": 0, "ResultDesc": "The service request is processed successfully.",
               "CallbackMetadata": {"Item": [{"Name": "Amount", "Value": 1160.0}, {"Name": "MpesaReceiptNumber", "Value": "SJK8H2L1QP"}]}}}}
    await mpesa.handle_callback(token, success)
    await mpesa.handle_callback(token, success)  # Safaricom may deliver it twice

    assert (await mpesa.status_of(request.id)).mpesa_receipt == "SJK8H2L1QP"
    await session.refresh(invoice)
    assert invoice.status.value == "paid" and invoice.amount_paid == Decimal("1160.00")  # paid once
    assert await accounting.balance_for_key("MPESA") == Decimal("1160")

    # A cancelled prompt records nothing.
    other = await sales.create_invoice(InvoiceCreate(party_id=customer.id, lines=[DocumentLineInput(description="X", qty=Decimal("1"), unit_price=Decimal("100"))]))
    cancelled = await mpesa.initiate(phone="0712345678", amount=Decimal("100"), invoice_id=other.id, reference="X", user_id="u")
    await mpesa.handle_callback(sent["CallBackURL"].rsplit("/", 1)[1], {"Body": {"stkCallback": {"ResultCode": 1032, "ResultDesc": "Request cancelled by user"}}})
    assert (await mpesa.status_of(cancelled.id)).status == "failed"
    await session.refresh(other)
    assert other.amount_paid == Decimal("0")


def test_sale_date_is_the_day_at_the_till():
    from datetime import datetime, timezone

    # 22:30 UTC on the 5th is already 01:30 on the 6th in Nairobi.
    assert SalesService._sale_date(datetime(2026, 1, 5, 22, 30, tzinfo=timezone.utc)) == date(2026, 1, 6)
    assert SalesService._sale_date(datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)) == date(2026, 1, 5)
    # A till whose clock is set years ahead doesn't get to post into the future.
    assert SalesService._sale_date(datetime(2999, 1, 1, tzinfo=timezone.utc)) <= date.today() + timedelta(days=1)
