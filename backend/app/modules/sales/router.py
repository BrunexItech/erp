from datetime import date

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor, get_actor, get_tenant_session, require_feature
from app.modules.sales.models import ArPaymentEntry, ArPaymentEntryType, CreditNote, Invoice, SalesOrderLine
from app.modules.sales.schemas import (
    CreditNoteCreate,
    CreditNoteOut,
    CustomerPaymentCreate,
    DeliveryCreate,
    InvoiceCreate,
    InvoiceDetailOut,
    InvoiceOut,
    PaymentOut,
    PosCheckoutRequest,
    PosReceiptOut,
    QuoteConvert,
    QuoteCreate,
    QuoteDetailOut,
    QuoteOut,
    QuoteStatusUpdate,
    SalesOrderCreate,
    SalesOrderLineOut,
    SalesOrderOut,
    VoidRequest,
)
from app.modules.sales.service import SalesService

router = APIRouter(prefix="/api/v1/sales", tags=["sales"])


def _pdf(content: bytes, filename: str) -> Response:
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}.pdf"'},
    )


# ------------------------------------------------------------------ orders


@router.post("/orders", response_model=SalesOrderOut)
async def create_sales_order(
    payload: SalesOrderCreate,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await SalesService(session, actor.workspace_id).create_sales_order(payload)


@router.get("/orders", response_model=list[SalesOrderOut])
async def list_sales_orders(
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    service = SalesService(session, actor.workspace_id)
    return sorted(await service.orders.list(), key=lambda o: o.created_at, reverse=True)


@router.get("/orders/{order_id}/lines", response_model=list[SalesOrderLineOut])
async def list_sales_order_lines(
    order_id: str,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    service = SalesService(session, actor.workspace_id)
    return await service.order_lines.list(SalesOrderLine.order_id == order_id)


@router.post("/orders/{order_id}/confirm", response_model=SalesOrderOut)
async def confirm_sales_order(
    order_id: str,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await SalesService(session, actor.workspace_id).confirm_sales_order(order_id)


@router.post("/deliveries")
async def create_delivery(
    payload: DeliveryCreate,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    delivery = await SalesService(session, actor.workspace_id).create_delivery(payload)
    return {
        "id": delivery.id,
        "order_id": delivery.order_id,
        "total_cogs": str(delivery.total_cogs),
    }


# ---------------------------------------------------------------- invoices


@router.post("/invoices", response_model=InvoiceOut)
async def create_invoice(
    payload: InvoiceCreate,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await SalesService(session, actor.workspace_id).create_invoice(payload)


@router.get("/invoices", response_model=list[InvoiceOut])
async def list_invoices(
    party_id: str | None = None,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    service = SalesService(session, actor.workspace_id)
    filters = [Invoice.party_id == party_id] if party_id else []
    return sorted(await service.invoices.list(*filters), key=lambda i: i.created_at, reverse=True)


@router.get("/invoices/{invoice_id}", response_model=InvoiceDetailOut)
async def get_invoice(
    invoice_id: str,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await SalesService(session, actor.workspace_id).invoice_detail(invoice_id)


@router.get("/invoices/{invoice_id}/pdf")
async def download_invoice_pdf(
    invoice_id: str,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    service = SalesService(session, actor.workspace_id)
    invoice = await service.invoices.get(invoice_id)
    pdf_bytes = await service.invoice_pdf(invoice_id)
    return _pdf(pdf_bytes, (invoice.invoice_no if invoice else "") or f"invoice-{invoice_id[:8]}")


@router.post("/invoices/{invoice_id}/void", response_model=InvoiceOut)
async def void_invoice(
    invoice_id: str,
    payload: VoidRequest,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await SalesService(session, actor.workspace_id).void_invoice(invoice_id, payload.reason)


@router.post("/invoices/payments", response_model=PaymentOut)
async def record_payment(
    payload: CustomerPaymentCreate,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await SalesService(session, actor.workspace_id).record_payment(
        payload.invoice_id, payload.amount, payload.method, payload.payment_date, payload.reference
    )


@router.get("/payments", response_model=list[PaymentOut])
async def list_payments(
    invoice_id: str | None = None,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    service = SalesService(session, actor.workspace_id)
    filters = [ArPaymentEntry.type == ArPaymentEntryType.payment]
    if invoice_id:
        filters.append(ArPaymentEntry.invoice_id == invoice_id)
    return sorted(await service.ar_entries.list(*filters), key=lambda p: p.created_at, reverse=True)


@router.get("/payments/{payment_id}/receipt")
async def download_receipt_pdf(
    payment_id: str,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    service = SalesService(session, actor.workspace_id)
    return _pdf(await service.receipt_pdf(payment_id), f"receipt-{payment_id[:8]}")


# ------------------------------------------------------------ credit notes


@router.post("/credit-notes", response_model=CreditNoteOut)
async def create_credit_note(
    payload: CreditNoteCreate,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await SalesService(session, actor.workspace_id).create_credit_note(payload)


@router.get("/credit-notes", response_model=list[CreditNoteOut])
async def list_credit_notes(
    invoice_id: str | None = None,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    service = SalesService(session, actor.workspace_id)
    filters = [CreditNote.invoice_id == invoice_id] if invoice_id else []
    return sorted(await service.credit_notes.list(*filters), key=lambda c: c.created_at, reverse=True)


@router.get("/credit-notes/{credit_note_id}/pdf")
async def download_credit_note_pdf(
    credit_note_id: str,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    service = SalesService(session, actor.workspace_id)
    return _pdf(await service.credit_note_pdf(credit_note_id), f"credit-note-{credit_note_id[:8]}")


# ------------------------------------------------------------------ quotes


@router.post("/quotes", response_model=QuoteOut)
async def create_quote(
    payload: QuoteCreate,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await SalesService(session, actor.workspace_id).create_quote(payload)


@router.get("/quotes", response_model=list[QuoteOut])
async def list_quotes(
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    service = SalesService(session, actor.workspace_id)
    return sorted(await service.quotes.list(), key=lambda q: q.created_at, reverse=True)


@router.get("/quotes/{quote_id}", response_model=QuoteDetailOut)
async def get_quote(
    quote_id: str,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await SalesService(session, actor.workspace_id).quote_detail(quote_id)


@router.post("/quotes/{quote_id}/status", response_model=QuoteOut)
async def set_quote_status(
    quote_id: str,
    payload: QuoteStatusUpdate,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await SalesService(session, actor.workspace_id).set_quote_status(quote_id, payload.status)


@router.post("/quotes/{quote_id}/convert", response_model=InvoiceOut)
async def convert_quote(
    quote_id: str,
    payload: QuoteConvert,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await SalesService(session, actor.workspace_id).convert_quote_to_invoice(quote_id, payload)


@router.get("/quotes/{quote_id}/pdf")
async def download_quote_pdf(
    quote_id: str,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    service = SalesService(session, actor.workspace_id)
    quote = await service.quotes.get(quote_id)
    return _pdf(await service.quote_pdf(quote_id), (quote.quote_no if quote else "") or f"quote-{quote_id[:8]}")


# --------------------------------------------------------------------- POS


@router.post(
    "/pos/checkout",
    response_model=PosReceiptOut,
    dependencies=[Depends(require_feature("pos"))],
)
async def pos_checkout(
    payload: PosCheckoutRequest,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    invoice, total_cogs, payment = await SalesService(session, actor.workspace_id).pos_checkout(
        payload, cashier_user_id=actor.user_id
    )
    tendered = payload.amount_tendered if payload.amount_tendered is not None else invoice.total
    return PosReceiptOut(
        order_id=invoice.order_id,
        invoice_id=invoice.id,
        invoice_no=invoice.invoice_no,
        receipt_no=payment.document_no,
        party_id=invoice.party_id,
        subtotal=invoice.subtotal,
        tax_total=invoice.tax_total,
        total=invoice.total,
        total_cogs=total_cogs,
        payment_method=payload.payment_method,
        payment_reference=payload.payment_reference,
        amount_tendered=tendered,
        change_due=tendered - invoice.total,
        issued_at=invoice.created_at,
    )


@router.get("/pos/summary", dependencies=[Depends(require_feature("pos"))])
async def pos_summary(
    day: date | None = None,
    warehouse_id: str | None = None,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await SalesService(session, actor.workspace_id).pos_summary(day or date.today(), warehouse_id)


# ----------------------------------------------------------------- reports


@router.get("/customers/{party_id}/balance")
async def customer_balance(
    party_id: str,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    balance = await SalesService(session, actor.workspace_id).customer_balance(party_id)
    return {"party_id": party_id, "balance": str(balance)}


@router.get("/customers/{party_id}/statement")
async def customer_statement(
    party_id: str,
    start: date | None = None,
    end: date | None = None,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    end = end or date.today()
    start = start or date(end.year, 1, 1)
    return await SalesService(session, actor.workspace_id).customer_statement(party_id, start, end)


@router.get("/customers/{party_id}/statement/pdf")
async def customer_statement_pdf(
    party_id: str,
    start: date | None = None,
    end: date | None = None,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    end = end or date.today()
    start = start or date(end.year, 1, 1)
    pdf_bytes = await SalesService(session, actor.workspace_id).statement_pdf(party_id, start, end)
    return _pdf(pdf_bytes, f"statement-{end.isoformat()}")


@router.get("/reports/ar-aging")
async def ar_aging(
    as_of: date | None = None,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await SalesService(session, actor.workspace_id).ar_aging(as_of)


@router.get("/reports/summary")
async def sales_summary(
    start: date | None = None,
    end: date | None = None,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    end = end or date.today()
    start = start or date(end.year, end.month, 1)
    return await SalesService(session, actor.workspace_id).sales_summary(start, end)
