from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.aging import bucket_for, empty_buckets
from app.core.db import TenantRepository
from app.core.numbering import next_number
from app.modules.inventory.models import StockMovementType
from app.modules.inventory.service import InventoryService
from app.modules.sales.models import (
    ArPaymentEntry,
    ArPaymentEntryType,
    CreditNote,
    CreditNoteLine,
    Delivery,
    DeliveryLine,
    Invoice,
    InvoiceLine,
    InvoiceStatus,
    Quote,
    QuoteLine,
    QuoteStatus,
    SalesOrder,
    SalesOrderLine,
    SalesOrderStatus,
)
from app.modules.sales.schemas import (
    CreditNoteCreate,
    DeliveryCreate,
    DocumentLineInput,
    InvoiceCreate,
    PosCheckoutRequest,
    QuoteConvert,
    QuoteCreate,
    SalesOrderCreate,
)

ZERO = Decimal("0")
CENT = Decimal("0.01")


def q2(value: Decimal) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class ComputedLine:
    product_id: str | None
    description: str
    qty: Decimal
    unit_price: Decimal
    discount_pct: Decimal
    tax_rate: Decimal
    line_subtotal: Decimal
    tax_amount: Decimal
    line_total: Decimal
    discount_amount: Decimal


@dataclass
class DocumentTotals:
    subtotal: Decimal  # net of discounts, before tax
    discount_total: Decimal
    tax_total: Decimal
    total: Decimal


def compute_lines(lines: list[DocumentLineInput], descriptions: dict[str, str]) -> tuple[list[ComputedLine], DocumentTotals]:
    """Per-line rounding (not per-document) — each printed line total must add
    up exactly to the printed document total, which is what KRA-compliant tax
    invoices and customers checking the arithmetic expect."""
    computed: list[ComputedLine] = []
    for line in lines:
        gross = line.qty * line.unit_price
        discount = q2(gross * line.discount_pct / 100)
        line_subtotal = q2(gross) - discount
        tax = q2(line_subtotal * line.tax_rate)
        description = line.description or (descriptions.get(line.product_id, "") if line.product_id else "")
        if not description:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "each line needs a product or a description")
        computed.append(
            ComputedLine(
                product_id=line.product_id,
                description=description,
                qty=line.qty,
                unit_price=line.unit_price,
                discount_pct=line.discount_pct,
                tax_rate=line.tax_rate,
                line_subtotal=line_subtotal,
                tax_amount=tax,
                line_total=line_subtotal + tax,
                discount_amount=discount,
            )
        )
    subtotal = sum((c.line_subtotal for c in computed), ZERO)
    tax_total = sum((c.tax_amount for c in computed), ZERO)
    return computed, DocumentTotals(
        subtotal=subtotal,
        discount_total=sum((c.discount_amount for c in computed), ZERO),
        tax_total=tax_total,
        total=subtotal + tax_total,
    )


class SalesService:
    def __init__(self, session: AsyncSession, workspace_id: str):
        self.session = session
        self.workspace_id = workspace_id
        self.orders = TenantRepository(session, workspace_id, SalesOrder)
        self.order_lines = TenantRepository(session, workspace_id, SalesOrderLine)
        self.deliveries = TenantRepository(session, workspace_id, Delivery)
        self.delivery_lines = TenantRepository(session, workspace_id, DeliveryLine)
        self.invoices = TenantRepository(session, workspace_id, Invoice)
        self.invoice_lines = TenantRepository(session, workspace_id, InvoiceLine)
        self.quotes = TenantRepository(session, workspace_id, Quote)
        self.quote_lines = TenantRepository(session, workspace_id, QuoteLine)
        self.credit_notes = TenantRepository(session, workspace_id, CreditNote)
        self.credit_note_lines = TenantRepository(session, workspace_id, CreditNoteLine)
        self.ar_entries = TenantRepository(session, workspace_id, ArPaymentEntry)
        self.inventory = InventoryService(session, workspace_id)

    # ---------------------------------------------------------------- helpers

    async def _product_descriptions(self, product_ids: set[str]) -> dict[str, str]:
        if not product_ids:
            return {}
        from app.modules.inventory.models import Product

        products = await self.inventory.products.list(Product.id.in_(product_ids))
        missing = product_ids - {p.id for p in products}
        if missing:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"product not found: {sorted(missing)[0]}")
        return {p.id: p.name for p in products}

    async def _workspace(self):
        from app.modules.platform.service import PlatformService

        return await PlatformService(self.session).get_workspace(self.workspace_id)

    async def _default_due_date(self, party_id: str, issue_date: date) -> date:
        from app.modules.crm.models import CustomerProfile

        profiles = await TenantRepository(self.session, self.workspace_id, CustomerProfile).list(
            CustomerProfile.party_id == party_id
        )
        if profiles:
            days = profiles[0].payment_terms_days
        else:
            days = (await self._workspace()).default_payment_terms_days
        return issue_date + timedelta(days=days)

    async def _party(self, party_id: str):
        from app.modules.crm.service import CrmService

        party = await CrmService(self.session, self.workspace_id).parties.get(party_id)
        if party is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "customer not found")
        return party

    # ----------------------------------------------------------------- orders

    async def create_sales_order(self, payload: SalesOrderCreate) -> SalesOrder:
        subtotal = sum((l.qty * l.unit_price for l in payload.lines), Decimal("0"))
        tax_total = sum(
            (l.qty * l.unit_price * l.tax_rate for l in payload.lines), Decimal("0")
        )
        order = SalesOrder(
            so_no=await next_number(self.session, self.workspace_id, "sales_order"),
            party_id=payload.party_id,
            subtotal=subtotal,
            tax_total=tax_total,
            total=subtotal + tax_total,
            status=SalesOrderStatus.draft,
        )
        await self.orders.add(order)
        await self.session.flush()

        for line in payload.lines:
            await self.order_lines.add(
                SalesOrderLine(
                    order_id=order.id,
                    product_id=line.product_id,
                    qty=line.qty,
                    unit_price=line.unit_price,
                    tax_rate=line.tax_rate,
                )
            )
        await self.session.commit()
        await self.session.refresh(order)
        return order

    async def confirm_sales_order(self, order_id: str) -> SalesOrder:
        order = await self.orders.get(order_id)
        if order is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "sales order not found")
        order.status = SalesOrderStatus.confirmed
        await self.session.commit()
        await self.session.refresh(order)
        return order

    async def create_delivery(self, payload: DeliveryCreate) -> Delivery:
        """Delivery: decrements stock at COGS (via apply_movement), snapshots the
        cost onto each DeliveryLine, and posts the COGS/Inventory journal entry
        via the DeliveryConfirmed event — all in one transaction/commit.

        Lines are processed sorted by product_id (deterministic order), matching
        Stoka's deadlock-avoidance pattern: two concurrent deliveries touching the
        same two products always lock them in the same order.
        """
        order = await self.orders.get(payload.order_id)
        if order is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "sales order not found")

        delivery = Delivery(order_id=payload.order_id, warehouse_id=payload.warehouse_id)
        await self.deliveries.add(delivery)
        await self.session.flush()

        total_cogs = Decimal("0")
        for line in sorted(payload.lines, key=lambda l: l.product_id):
            movement = await self.inventory.apply_movement(
                product_id=line.product_id,
                warehouse_id=payload.warehouse_id,
                type=StockMovementType.sale,
                qty_delta=-line.qty_delivered,
                ref_type="delivery",
                ref_id=delivery.id,
            )
            cogs_amount = movement.unit_cost * line.qty_delivered
            total_cogs += cogs_amount

            await self.delivery_lines.add(
                DeliveryLine(
                    delivery_id=delivery.id,
                    order_line_id=line.order_line_id,
                    product_id=line.product_id,
                    qty_delivered=line.qty_delivered,
                    cogs_amount=cogs_amount,
                )
            )

            order_line = await self.order_lines.get(line.order_line_id)
            if order_line is not None:
                order_line.qty_delivered += line.qty_delivered

        delivery.total_cogs = total_cogs

        fully_delivered = all(
            ol.qty_delivered >= ol.qty
            for ol in await self.order_lines.list(SalesOrderLine.order_id == order.id)
        )
        order.status = (
            SalesOrderStatus.delivered if fully_delivered else SalesOrderStatus.partially_delivered
        )

        await events.publish(
            events.DeliveryConfirmed(
                workspace_id=self.workspace_id,
                delivery_id=delivery.id,
                sales_order_id=order.id,
                cogs_amount=float(total_cogs),
            ),
            self.session,
        )

        await self.session.commit()
        await self.session.refresh(delivery)
        return delivery

    async def _ship_new_order(
        self,
        *,
        party_id: str,
        lines: list[ComputedLine],
        warehouse_id: str,
        ref_type: str,
        entry_date: date | None = None,
    ) -> tuple[SalesOrder, Decimal]:
        """Creates an already-confirmed order for `lines` and immediately ships
        every product line from `warehouse_id` (stock out at COGS + the COGS
        journal entry). Shared by POS checkout and invoice-and-ship. Does NOT
        commit — the caller finishes its own document in the same transaction,
        so an insufficient-stock failure rolls the whole sale back."""
        product_lines = [l for l in lines if l.product_id]
        subtotal = sum((l.line_subtotal for l in lines), ZERO)
        tax_total = sum((l.tax_amount for l in lines), ZERO)
        order = SalesOrder(
            so_no=await next_number(self.session, self.workspace_id, "sales_order"),
            party_id=party_id,
            subtotal=subtotal,
            tax_total=tax_total,
            total=subtotal + tax_total,
            status=SalesOrderStatus.confirmed,
        )
        await self.orders.add(order)
        await self.session.flush()

        order_lines: list[tuple[ComputedLine, SalesOrderLine]] = []
        for line in product_lines:
            order_line = SalesOrderLine(
                order_id=order.id,
                product_id=line.product_id,
                qty=line.qty,
                unit_price=line.line_subtotal / line.qty,
                tax_rate=line.tax_rate,
            )
            await self.order_lines.add(order_line)
            order_lines.append((line, order_line))

        total_cogs = ZERO
        if order_lines:
            delivery = Delivery(order_id=order.id, warehouse_id=warehouse_id)
            await self.deliveries.add(delivery)
            await self.session.flush()

            for line, order_line in sorted(order_lines, key=lambda pair: pair[0].product_id):
                movement = await self.inventory.apply_movement(
                    product_id=line.product_id,
                    warehouse_id=warehouse_id,
                    type=StockMovementType.sale,
                    qty_delta=-line.qty,
                    ref_type=ref_type,
                    ref_id=delivery.id,
                )
                cogs_amount = movement.unit_cost * line.qty
                total_cogs += cogs_amount
                order_line.qty_delivered = line.qty
                await self.delivery_lines.add(
                    DeliveryLine(
                        delivery_id=delivery.id,
                        order_line_id=order_line.id,
                        product_id=line.product_id,
                        qty_delivered=line.qty,
                        cogs_amount=cogs_amount,
                    )
                )
            delivery.total_cogs = total_cogs
            await events.publish(
                events.DeliveryConfirmed(
                    workspace_id=self.workspace_id,
                    delivery_id=delivery.id,
                    sales_order_id=order.id,
                    cogs_amount=float(total_cogs),
                    entry_date=entry_date,
                ),
                self.session,
            )
        order.status = SalesOrderStatus.delivered
        return order, total_cogs

    # --------------------------------------------------------------- invoices

    async def _lines_from_order(self, order_id: str) -> list[DocumentLineInput]:
        order_lines = await self.order_lines.list(SalesOrderLine.order_id == order_id)
        descriptions = await self._product_descriptions({l.product_id for l in order_lines})
        return [
            DocumentLineInput(
                product_id=l.product_id,
                description=descriptions.get(l.product_id, ""),
                qty=l.qty,
                unit_price=l.unit_price,
                tax_rate=l.tax_rate,
            )
            for l in order_lines
        ]

    async def create_invoice(self, payload: InvoiceCreate, *, quote_id: str | None = None) -> Invoice:
        issue_date = payload.issue_date or date.today()
        due_date = payload.due_date or await self._default_due_date(payload.party_id, issue_date)

        order = None
        if payload.order_id:
            order = await self.orders.get(payload.order_id)
            if order is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "sales order not found")

        line_inputs = payload.lines
        if not line_inputs and order is not None:
            line_inputs = await self._lines_from_order(order.id)

        computed: list[ComputedLine] = []
        if line_inputs:
            descriptions = await self._product_descriptions({l.product_id for l in line_inputs if l.product_id})
            computed, totals = compute_lines(line_inputs, descriptions)
        elif payload.subtotal is not None:
            # Legacy un-itemized invoice: totals only.
            totals = DocumentTotals(
                subtotal=q2(payload.subtotal),
                discount_total=ZERO,
                tax_total=q2(payload.tax_total),
                total=q2(payload.subtotal + payload.tax_total),
            )
        else:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "an invoice needs at least one line")
        if totals.total <= 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invoice total must be greater than zero")

        if payload.warehouse_id:
            if order is not None:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "an order's goods ship via deliveries — don't pass warehouse_id with order_id",
                )
            order, _ = await self._ship_new_order(
                party_id=payload.party_id,
                lines=computed,
                warehouse_id=payload.warehouse_id,
                ref_type="invoice_shipment",
                entry_date=issue_date,
            )

        workspace = await self._workspace()
        invoice = Invoice(
            invoice_no=await next_number(self.session, self.workspace_id, "invoice"),
            order_id=order.id if order else None,
            quote_id=quote_id,
            party_id=payload.party_id,
            issue_date=issue_date,
            due_date=due_date,
            reference=payload.reference,
            notes=payload.notes,
            terms=payload.terms if payload.terms is not None else workspace.invoice_terms,
            subtotal=totals.subtotal,
            discount_total=totals.discount_total,
            tax_total=totals.tax_total,
            total=totals.total,
            status=InvoiceStatus.posted,
        )
        await self.invoices.add(invoice)
        await self.session.flush()

        for position, line in enumerate(computed):
            await self.invoice_lines.add(
                InvoiceLine(
                    invoice_id=invoice.id,
                    position=position,
                    product_id=line.product_id,
                    description=line.description,
                    qty=line.qty,
                    unit_price=line.unit_price,
                    discount_pct=line.discount_pct,
                    tax_rate=line.tax_rate,
                    line_subtotal=line.line_subtotal,
                    tax_amount=line.tax_amount,
                    line_total=line.line_total,
                )
            )

        if order is not None and order.status == SalesOrderStatus.delivered:
            order.status = SalesOrderStatus.invoiced

        await self.ar_entries.add(
            ArPaymentEntry(
                party_id=payload.party_id,
                invoice_id=invoice.id,
                type=ArPaymentEntryType.invoice_charge,
                amount=totals.total,
                entry_date=issue_date,
                document_no=invoice.invoice_no,
                reference=payload.reference,
            )
        )

        await events.publish(
            events.InvoicePosted(
                workspace_id=self.workspace_id,
                invoice_id=invoice.id,
                party_id=payload.party_id,
                subtotal=float(totals.subtotal),
                tax_total=float(totals.tax_total),
                total=float(totals.total),
                entry_date=issue_date,
            ),
            self.session,
        )

        await self.session.commit()
        await self.session.refresh(invoice)
        return invoice

    async def invoice_detail(self, invoice_id: str) -> dict:
        invoice = await self.invoices.get(invoice_id)
        if invoice is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "invoice not found")
        lines = sorted(
            await self.invoice_lines.list(InvoiceLine.invoice_id == invoice.id), key=lambda l: l.position
        )
        party = await self._party(invoice.party_id)
        return {
            **{c.name: getattr(invoice, c.name) for c in Invoice.__table__.columns},
            "lines": lines,
            "balance_due": self.balance_due(invoice),
            "party_name": party.name,
        }

    @staticmethod
    def balance_due(invoice: Invoice) -> Decimal:
        if invoice.status == InvoiceStatus.void:
            return ZERO
        return invoice.total - invoice.amount_paid - invoice.amount_credited

    def _refresh_status(self, invoice: Invoice) -> None:
        if invoice.status == InvoiceStatus.void:
            return
        settled = invoice.amount_paid + invoice.amount_credited
        if settled >= invoice.total:
            invoice.status = InvoiceStatus.paid
        elif invoice.amount_paid > 0:
            invoice.status = InvoiceStatus.partially_paid
        else:
            invoice.status = InvoiceStatus.posted

    async def record_payment(
        self,
        invoice_id: str,
        amount: Decimal,
        method: str,
        payment_date: date | None = None,
        reference: str = "",
    ) -> ArPaymentEntry:
        invoice = await self.invoices.get_for_update(invoice_id)
        if invoice is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "invoice not found")
        if invoice.status == InvoiceStatus.void:
            raise HTTPException(status.HTTP_409_CONFLICT, "invoice is void")
        if amount <= 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "payment amount must be positive")
        outstanding = self.balance_due(invoice)
        if amount > outstanding:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"payment {amount} exceeds the invoice's balance due {outstanding}",
            )

        payment_date = payment_date or date.today()
        entry = ArPaymentEntry(
            party_id=invoice.party_id,
            invoice_id=invoice.id,
            type=ArPaymentEntryType.payment,
            amount=amount,
            method=method,
            entry_date=payment_date,
            document_no=await next_number(self.session, self.workspace_id, "receipt"),
            reference=reference,
        )
        await self.ar_entries.add(entry)
        await self.session.flush()

        invoice.amount_paid += amount
        self._refresh_status(invoice)

        await events.publish(
            events.PaymentReceived(
                workspace_id=self.workspace_id,
                payment_id=entry.id,
                invoice_id=invoice.id,
                amount=float(amount),
                entry_date=payment_date,
            ),
            self.session,
        )

        await self.session.commit()
        await self.session.refresh(entry)
        return entry

    async def void_invoice(self, invoice_id: str, reason: str = "") -> Invoice:
        invoice = await self.invoices.get_for_update(invoice_id)
        if invoice is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "invoice not found")
        if invoice.status == InvoiceStatus.void:
            raise HTTPException(status.HTTP_409_CONFLICT, "invoice is already void")
        if invoice.amount_paid > 0 or invoice.amount_credited > 0:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "invoice has payments or credit notes — issue a credit note instead of voiding",
            )
        invoice.status = InvoiceStatus.void
        if reason:
            invoice.notes = f"{invoice.notes}\nVOID: {reason}".strip()
        # Offset the original charge in the AR sub-ledger, mirroring the GL reversal.
        await self.ar_entries.add(
            ArPaymentEntry(
                party_id=invoice.party_id,
                invoice_id=invoice.id,
                type=ArPaymentEntryType.credit_note,
                amount=invoice.total,
                entry_date=date.today(),
                document_no=invoice.invoice_no,
                reference="VOID",
            )
        )
        await events.publish(
            events.InvoiceVoided(workspace_id=self.workspace_id, invoice_id=invoice.id, entry_date=date.today()),
            self.session,
        )
        await self.session.commit()
        await self.session.refresh(invoice)
        return invoice

    # ----------------------------------------------------------- credit notes

    async def _unit_cogs(self, invoice: Invoice, product_id: str) -> Decimal:
        """Cost per unit the goods left stock at when this invoice's order was
        delivered — returned goods go back in at that same cost, so a return
        exactly undoes the sale's COGS instead of re-pricing the stock."""
        if invoice.order_id:
            stmt = (
                select(
                    func.coalesce(func.sum(DeliveryLine.cogs_amount), 0),
                    func.coalesce(func.sum(DeliveryLine.qty_delivered), 0),
                )
                .join(Delivery, Delivery.id == DeliveryLine.delivery_id)
                .where(
                    DeliveryLine.workspace_id == self.workspace_id,
                    Delivery.order_id == invoice.order_id,
                    DeliveryLine.product_id == product_id,
                )
            )
            cogs, qty = (await self.session.execute(stmt)).one()
            if Decimal(qty) > 0:
                return Decimal(cogs) / Decimal(qty)
        product = await self.inventory.products.get(product_id)
        return product.avg_cost if product else ZERO

    async def create_credit_note(self, payload: CreditNoteCreate) -> CreditNote:
        invoice = await self.invoices.get_for_update(payload.invoice_id)
        if invoice is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "invoice not found")
        if invoice.status == InvoiceStatus.void:
            raise HTTPException(status.HTTP_409_CONFLICT, "can't credit a void invoice")

        invoice_lines = {l.id: l for l in await self.invoice_lines.list(InvoiceLine.invoice_id == invoice.id)}

        # (product_id, description, qty, unit_price, tax_rate, line_subtotal, tax_amount)
        resolved: list[tuple[str | None, str, Decimal, Decimal, Decimal, Decimal, Decimal]] = []
        if payload.lines is None:
            if invoice_lines:
                for l in sorted(invoice_lines.values(), key=lambda l: l.position):
                    resolved.append(
                        (l.product_id, l.description, l.qty, l.line_subtotal / l.qty, l.tax_rate,
                         l.line_subtotal, l.tax_amount)
                    )
            else:
                resolved.append(
                    (None, f"Credit for {invoice.invoice_no or 'invoice'}", Decimal("1"),
                     invoice.subtotal, ZERO, invoice.subtotal, invoice.tax_total)
                )
        else:
            descriptions = await self._product_descriptions(
                {l.product_id for l in payload.lines if l.product_id}
            )
            for l in payload.lines:
                source = invoice_lines.get(l.invoice_line_id) if l.invoice_line_id else None
                if l.invoice_line_id and source is None:
                    raise HTTPException(status.HTTP_404_NOT_FOUND, "invoice line not found on this invoice")
                product_id = source.product_id if source else l.product_id
                unit_price = l.unit_price if l.unit_price is not None else (
                    source.line_subtotal / source.qty if source else None
                )
                if unit_price is None:
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, "unit_price required for a free credit line")
                tax_rate = l.tax_rate if l.tax_rate is not None else (source.tax_rate if source else ZERO)
                description = l.description or (source.description if source else descriptions.get(product_id or "", ""))
                if not description:
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, "each credit line needs a description")
                line_subtotal = q2(l.qty * unit_price)
                resolved.append(
                    (product_id, description, l.qty, unit_price, tax_rate, line_subtotal, q2(line_subtotal * tax_rate))
                )

        subtotal = sum((r[5] for r in resolved), ZERO)
        tax_total = sum((r[6] for r in resolved), ZERO)
        total = subtotal + tax_total
        if total <= 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "credit note total must be greater than zero")
        creditable = invoice.total - invoice.amount_credited
        if total > creditable:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"credit {total} exceeds the amount still creditable on this invoice ({creditable})",
            )

        issue_date = payload.issue_date or date.today()
        credit_note = CreditNote(
            credit_note_no=await next_number(self.session, self.workspace_id, "credit_note"),
            invoice_id=invoice.id,
            party_id=invoice.party_id,
            issue_date=issue_date,
            reason=payload.reason,
            restocked_warehouse_id=payload.restock_warehouse_id,
            subtotal=subtotal,
            tax_total=tax_total,
            total=total,
        )
        await self.credit_notes.add(credit_note)
        await self.session.flush()

        restock_cost = ZERO
        for product_id, description, qty, unit_price, tax_rate, line_subtotal, tax_amount in resolved:
            await self.credit_note_lines.add(
                CreditNoteLine(
                    credit_note_id=credit_note.id,
                    product_id=product_id,
                    description=description,
                    qty=qty,
                    unit_price=unit_price,
                    tax_rate=tax_rate,
                    line_subtotal=line_subtotal,
                    tax_amount=tax_amount,
                    line_total=line_subtotal + tax_amount,
                )
            )
            if payload.restock_warehouse_id and product_id:
                unit_cost = await self._unit_cogs(invoice, product_id)
                await self.inventory.apply_movement(
                    product_id=product_id,
                    warehouse_id=payload.restock_warehouse_id,
                    type=StockMovementType.return_,
                    qty_delta=qty,
                    unit_cost=unit_cost,
                    ref_type="credit_note",
                    ref_id=credit_note.id,
                )
                restock_cost += q2(unit_cost * qty)

        await self.ar_entries.add(
            ArPaymentEntry(
                party_id=invoice.party_id,
                invoice_id=invoice.id,
                credit_note_id=credit_note.id,
                type=ArPaymentEntryType.credit_note,
                amount=total,
                entry_date=issue_date,
                document_no=credit_note.credit_note_no,
                reference=invoice.invoice_no,
            )
        )
        invoice.amount_credited += total
        self._refresh_status(invoice)

        await events.publish(
            events.CreditNoteIssued(
                workspace_id=self.workspace_id,
                credit_note_id=credit_note.id,
                invoice_id=invoice.id,
                subtotal=float(subtotal),
                tax_total=float(tax_total),
                total=float(total),
                restock_cost=float(restock_cost),
                entry_date=issue_date,
            ),
            self.session,
        )
        await self.session.commit()
        await self.session.refresh(credit_note)
        return credit_note

    # ----------------------------------------------------------------- quotes

    async def create_quote(self, payload: QuoteCreate) -> Quote:
        await self._party(payload.party_id)
        descriptions = await self._product_descriptions({l.product_id for l in payload.lines if l.product_id})
        computed, totals = compute_lines(payload.lines, descriptions)
        issue_date = payload.issue_date or date.today()
        workspace = await self._workspace()
        quote = Quote(
            quote_no=await next_number(self.session, self.workspace_id, "quote"),
            party_id=payload.party_id,
            issue_date=issue_date,
            valid_until=payload.valid_until or issue_date + timedelta(days=30),
            reference=payload.reference,
            notes=payload.notes,
            terms=payload.terms if payload.terms is not None else workspace.invoice_terms,
            subtotal=totals.subtotal,
            discount_total=totals.discount_total,
            tax_total=totals.tax_total,
            total=totals.total,
        )
        await self.quotes.add(quote)
        await self.session.flush()
        for position, line in enumerate(computed):
            await self.quote_lines.add(
                QuoteLine(
                    quote_id=quote.id,
                    position=position,
                    product_id=line.product_id,
                    description=line.description,
                    qty=line.qty,
                    unit_price=line.unit_price,
                    discount_pct=line.discount_pct,
                    tax_rate=line.tax_rate,
                    line_subtotal=line.line_subtotal,
                    tax_amount=line.tax_amount,
                    line_total=line.line_total,
                )
            )
        await self.session.commit()
        await self.session.refresh(quote)
        return quote

    async def quote_detail(self, quote_id: str) -> dict:
        quote = await self.quotes.get(quote_id)
        if quote is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "quote not found")
        lines = sorted(await self.quote_lines.list(QuoteLine.quote_id == quote.id), key=lambda l: l.position)
        party = await self._party(quote.party_id)
        return {
            **{c.name: getattr(quote, c.name) for c in Quote.__table__.columns},
            "lines": lines,
            "party_name": party.name,
        }

    async def set_quote_status(self, quote_id: str, new_status: QuoteStatus) -> Quote:
        quote = await self.quotes.get_for_update(quote_id)
        if quote is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "quote not found")
        if quote.status == QuoteStatus.converted:
            raise HTTPException(status.HTTP_409_CONFLICT, "quote has already been converted to an invoice")
        if new_status == QuoteStatus.converted:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "use the convert endpoint to invoice a quote")
        quote.status = new_status
        await self.session.commit()
        await self.session.refresh(quote)
        return quote

    async def convert_quote_to_invoice(self, quote_id: str, payload: QuoteConvert) -> Invoice:
        quote = await self.quotes.get_for_update(quote_id)
        if quote is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "quote not found")
        if quote.status in (QuoteStatus.converted, QuoteStatus.declined):
            raise HTTPException(status.HTTP_409_CONFLICT, f"quote is {quote.status.value}")
        lines = sorted(await self.quote_lines.list(QuoteLine.quote_id == quote.id), key=lambda l: l.position)
        quote.status = QuoteStatus.converted
        invoice = await self.create_invoice(
            InvoiceCreate(
                party_id=quote.party_id,
                issue_date=payload.issue_date,
                due_date=payload.due_date,
                reference=quote.reference or quote.quote_no,
                notes=quote.notes,
                terms=quote.terms,
                warehouse_id=payload.warehouse_id,
                lines=[
                    DocumentLineInput(
                        product_id=l.product_id,
                        description=l.description,
                        qty=l.qty,
                        unit_price=l.unit_price,
                        discount_pct=l.discount_pct,
                        tax_rate=l.tax_rate,
                    )
                    for l in lines
                ],
            ),
            quote_id=quote.id,
        )
        quote.converted_invoice_id = invoice.id
        await self.session.commit()
        return invoice

    # -------------------------------------------------------------------- POS

    async def pos_checkout(self, payload: PosCheckoutRequest, cashier_user_id: str | None = None) -> tuple[Invoice, Decimal, ArPaymentEntry]:
        """Instant walk-in sale for a POS till: order (created already
        confirmed) -> delivery (stock out at COGS) -> invoice -> payment in
        full, all in ONE transaction/commit. If anything fails partway (most
        likely: insufficient stock on a line), the whole sale rolls back rather
        than leaving a half-completed order sitting in the system — a POS
        register can't afford a "confirmed but not actually paid" state.

        Returns (Invoice, total_cogs, payment).
        """
        party_id = payload.party_id
        if not party_id:
            from app.modules.crm.service import CrmService

            walk_in = await CrmService(self.session, self.workspace_id).get_or_create_walk_in_customer()
            party_id = walk_in.id

        descriptions = await self._product_descriptions({l.product_id for l in payload.lines})
        computed, totals = compute_lines(
            [
                DocumentLineInput(product_id=l.product_id, qty=l.qty, unit_price=l.unit_price, tax_rate=l.tax_rate)
                for l in payload.lines
            ],
            descriptions,
        )
        today = date.today()
        order, total_cogs = await self._ship_new_order(
            party_id=party_id,
            lines=computed,
            warehouse_id=payload.warehouse_id,
            ref_type="pos_sale",
        )
        order.status = SalesOrderStatus.invoiced

        if payload.amount_tendered is not None and payload.amount_tendered < totals.total:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"amount tendered {payload.amount_tendered} is less than the total {totals.total}",
            )

        invoice = Invoice(
            invoice_no=await next_number(self.session, self.workspace_id, "invoice"),
            order_id=order.id,
            party_id=party_id,
            issue_date=today,
            due_date=today,
            channel="pos",
            warehouse_id=payload.warehouse_id,
            cashier_user_id=cashier_user_id,
            subtotal=totals.subtotal,
            tax_total=totals.tax_total,
            total=totals.total,
            amount_paid=totals.total,
            status=InvoiceStatus.paid,
        )
        await self.invoices.add(invoice)
        await self.session.flush()
        for position, line in enumerate(computed):
            await self.invoice_lines.add(
                InvoiceLine(
                    invoice_id=invoice.id,
                    position=position,
                    product_id=line.product_id,
                    description=line.description,
                    qty=line.qty,
                    unit_price=line.unit_price,
                    tax_rate=line.tax_rate,
                    line_subtotal=line.line_subtotal,
                    tax_amount=line.tax_amount,
                    line_total=line.line_total,
                )
            )

        await self.ar_entries.add(
            ArPaymentEntry(
                party_id=party_id, invoice_id=invoice.id,
                type=ArPaymentEntryType.invoice_charge, amount=totals.total,
                entry_date=today, document_no=invoice.invoice_no,
            )
        )

        await events.publish(
            events.InvoicePosted(
                workspace_id=self.workspace_id,
                invoice_id=invoice.id,
                party_id=party_id,
                subtotal=float(totals.subtotal),
                tax_total=float(totals.tax_total),
                total=float(totals.total),
            ),
            self.session,
        )

        payment = ArPaymentEntry(
            party_id=party_id, invoice_id=invoice.id,
            type=ArPaymentEntryType.payment, amount=totals.total, method=payload.payment_method,
            entry_date=today, document_no=await next_number(self.session, self.workspace_id, "receipt"),
            reference=payload.payment_reference,
        )
        await self.ar_entries.add(payment)

        await events.publish(
            events.PaymentReceived(
                workspace_id=self.workspace_id,
                payment_id=payment.id,
                invoice_id=invoice.id,
                amount=float(totals.total),
            ),
            self.session,
        )

        await self.session.commit()
        await self.session.refresh(invoice)
        await self.session.refresh(payment)
        return invoice, total_cogs, payment

    async def pos_summary(self, day: date, warehouse_id: str | None = None) -> dict:
        """End-of-day till summary (X/Z report): POS takings by payment method,
        so the cashier can count the drawer and match M-Pesa statements."""
        filters = [Invoice.channel == "pos", Invoice.issue_date == day, Invoice.status != InvoiceStatus.void]
        if warehouse_id:
            filters.append(Invoice.warehouse_id == warehouse_id)
        invoices = await self.invoices.list(*filters)
        by_method: dict[str, dict] = defaultdict(lambda: {"count": 0, "amount": ZERO})
        if invoices:
            payments = await self.ar_entries.list(
                ArPaymentEntry.invoice_id.in_([i.id for i in invoices]),
                ArPaymentEntry.type == ArPaymentEntryType.payment,
            )
            for p in payments:
                row = by_method[p.method or "cash"]
                row["count"] += 1
                row["amount"] += p.amount
        return {
            "date": day,
            "warehouse_id": warehouse_id,
            "sales_count": len(invoices),
            "gross_sales": sum((i.total for i in invoices), ZERO),
            "vat": sum((i.tax_total for i in invoices), ZERO),
            "net_sales": sum((i.subtotal for i in invoices), ZERO),
            "by_method": [{"method": m, **v} for m, v in sorted(by_method.items())],
            "recent": [
                {"id": i.id, "invoice_no": i.invoice_no, "total": i.total, "created_at": i.created_at}
                for i in sorted(invoices, key=lambda i: i.created_at, reverse=True)[:20]
            ],
        }

    # -------------------------------------------------------------------- PDFs

    async def invoice_pdf(self, invoice_id: str) -> bytes:
        """Renders the invoice as a branded tax-invoice PDF (see documents.py)."""
        from app.modules.sales import documents

        invoice = await self.invoices.get(invoice_id)
        if invoice is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "invoice not found")
        party = await self._party(invoice.party_id)
        workspace = await self._workspace()

        stored = sorted(await self.invoice_lines.list(InvoiceLine.invoice_id == invoice.id), key=lambda l: l.position)
        if stored:
            lines = [documents.line_from_model(l) for l in stored]
        elif invoice.order_id:
            # Invoices created before lines were stored: derive from the order.
            lines = []
            for l in await self.order_lines.list(SalesOrderLine.order_id == invoice.order_id):
                product = await self.inventory.products.get(l.product_id)
                sub = q2(l.qty * l.unit_price)
                lines.append(
                    documents.DocLine(
                        description=f"{product.sku} — {product.name}" if product else l.product_id,
                        qty=l.qty, unit_price=l.unit_price, discount_pct=ZERO, tax_rate=l.tax_rate,
                        amount=sub,
                    )
                )
        else:
            lines = []

        overdue = (
            invoice.status in (InvoiceStatus.posted, InvoiceStatus.partially_paid)
            and invoice.due_date is not None
            and invoice.due_date < date.today()
        )
        stamp = {"paid": "PAID", "void": "VOID"}.get(invoice.status.value) or ("OVERDUE" if overdue else None)

        return documents.render_document(
            workspace=workspace,
            party=party,
            title="TAX INVOICE" if invoice.tax_total > 0 else "INVOICE",
            meta=[
                ("Invoice No.", invoice.invoice_no or invoice.id[:8].upper()),
                ("Invoice Date", documents.fmt_date(invoice.issue_date or invoice.created_at.date())),
                ("Due Date", documents.fmt_date(invoice.due_date)),
                ("Reference", invoice.reference),
            ],
            lines=lines,
            totals=documents.Totals(
                subtotal=invoice.subtotal + invoice.discount_total,
                discount=invoice.discount_total,
                tax=invoice.tax_total,
                total=invoice.total,
                paid=invoice.amount_paid,
                credited=invoice.amount_credited,
                balance=self.balance_due(invoice),
            ),
            notes=invoice.notes,
            terms=invoice.terms,
            payment_reference=invoice.invoice_no,
            stamp=stamp,
            show_payment_details=invoice.status != InvoiceStatus.void,
        )

    async def sample_invoice_pdf(self, template: str | None, brand_color: str | None) -> bytes:
        """A made-up invoice on the workspace's real letterhead — lets an owner
        compare designs and colours before saving them. Nothing is stored."""
        from types import SimpleNamespace

        from app.modules.sales import documents

        workspace = await self._workspace()
        preview = SimpleNamespace(**{c.name: getattr(workspace, c.name) for c in workspace.__table__.columns})
        if template:
            preview.invoice_template = template
        if brand_color:
            preview.brand_color = brand_color
        customer = SimpleNamespace(
            name="Sample Customer Ltd", billing_address="Moi Avenue, Nairobi", shipping_address="",
            phone="+254 722 000 111", email="accounts@customer.co.ke", tax_id="P051234567X",
        )
        lines = [
            documents.DocLine("Product or service name", Decimal("12"), Decimal("1850"), ZERO, Decimal("0.16"), Decimal("22200")),
            documents.DocLine("Another item, with a 5% discount", Decimal("3"), Decimal("4200"), Decimal("5"), Decimal("0.16"), Decimal("11970")),
            documents.DocLine("Delivery", Decimal("1"), Decimal("1500"), ZERO, Decimal("0.16"), Decimal("1500")),
        ]
        today = date.today()
        return documents.render_document(
            workspace=preview,
            party=customer,
            title="TAX INVOICE",
            meta=[
                ("Invoice No.", "INV-000123"),
                ("Invoice Date", documents.fmt_date(today)),
                ("Due Date", documents.fmt_date(today + timedelta(days=workspace.default_payment_terms_days))),
                ("Reference", "LPO-4471"),
            ],
            lines=lines,
            totals=documents.Totals(
                subtotal=Decimal("36300"), discount=Decimal("630"), tax=Decimal("5707.20"),
                total=Decimal("41377.20"), paid=Decimal("15000"), balance=Decimal("26377.20"),
            ),
            notes="This is a preview with sample figures.",
            terms=workspace.invoice_terms,
            payment_reference="INV-000123",
        )

    async def quote_pdf(self, quote_id: str) -> bytes:
        from app.modules.sales import documents

        quote = await self.quotes.get(quote_id)
        if quote is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "quote not found")
        party = await self._party(quote.party_id)
        workspace = await self._workspace()
        stored = sorted(await self.quote_lines.list(QuoteLine.quote_id == quote.id), key=lambda l: l.position)
        return documents.render_document(
            workspace=workspace,
            party=party,
            title="QUOTATION",
            meta=[
                ("Quote No.", quote.quote_no),
                ("Date", documents.fmt_date(quote.issue_date)),
                ("Valid Until", documents.fmt_date(quote.valid_until)),
                ("Reference", quote.reference),
            ],
            lines=[documents.line_from_model(l) for l in stored],
            totals=documents.Totals(
                subtotal=quote.subtotal + quote.discount_total,
                discount=quote.discount_total,
                tax=quote.tax_total,
                total=quote.total,
            ),
            notes=quote.notes,
            terms=quote.terms,
            stamp="DECLINED" if quote.status == QuoteStatus.declined else None,
            show_payment_details=False,
        )

    async def credit_note_pdf(self, credit_note_id: str) -> bytes:
        from app.modules.sales import documents

        note = await self.credit_notes.get(credit_note_id)
        if note is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "credit note not found")
        invoice = await self.invoices.get(note.invoice_id)
        party = await self._party(note.party_id)
        workspace = await self._workspace()
        lines = await self.credit_note_lines.list(CreditNoteLine.credit_note_id == note.id)
        return documents.render_document(
            workspace=workspace,
            party=party,
            title="CREDIT NOTE",
            meta=[
                ("Credit Note No.", note.credit_note_no),
                ("Date", documents.fmt_date(note.issue_date)),
                ("Against Invoice", invoice.invoice_no if invoice else ""),
            ],
            lines=[
                documents.DocLine(
                    description=l.description, qty=l.qty, unit_price=l.unit_price,
                    discount_pct=ZERO, tax_rate=l.tax_rate, amount=l.line_subtotal,
                )
                for l in lines
            ],
            totals=documents.Totals(subtotal=note.subtotal, discount=ZERO, tax=note.tax_total, total=note.total),
            notes=f"Reason: {note.reason}" if note.reason else "",
            terms="",
            show_payment_details=False,
        )

    async def receipt_pdf(self, payment_id: str) -> bytes:
        from app.modules.sales import documents

        payment = await self.ar_entries.get(payment_id)
        if payment is None or payment.type != ArPaymentEntryType.payment:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "payment not found")
        invoice = await self.invoices.get(payment.invoice_id) if payment.invoice_id else None
        party = await self._party(payment.party_id)
        workspace = await self._workspace()
        return documents.render_receipt(
            workspace=workspace,
            party=party,
            receipt_no=payment.document_no or payment.id[:8].upper(),
            receipt_date=payment.entry_date or payment.created_at.date(),
            amount=payment.amount,
            method=payment.method,
            reference=payment.reference,
            invoice_no=invoice.invoice_no if invoice else "",
            balance_after=self.balance_due(invoice) if invoice else None,
        )

    async def statement_pdf(self, party_id: str, start: date, end: date) -> bytes:
        from app.modules.sales import documents

        statement = await self.customer_statement(party_id, start, end)
        party = await self._party(party_id)
        workspace = await self._workspace()
        aging = await self.ar_aging(end, party_id=party_id)
        buckets = aging["rows"][0] if aging["rows"] else {**empty_buckets(), "total": ZERO}
        return documents.render_statement(workspace=workspace, party=party, statement=statement, aging=buckets)

    # ------------------------------------------------------------------ email

    async def email_document(
        self, *, kind: str, document_id: str, to: str | None, cc: list[str], message: str, sent_by: str,
        start: date | None = None, end: date | None = None,
    ) -> dict:
        """Emails an invoice, quote or statement to the customer as a PDF, from
        the business's name with replies going to its billing address."""
        from html import escape

        from app.core import mailer
        from app.modules.platform.accounts import AccountService
        from app.modules.sales import documents

        workspace = await self._workspace()
        currency = workspace.currency
        if kind == "invoice":
            invoice = await self.invoices.get(document_id)
            if invoice is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "invoice not found")
            if invoice.status == InvoiceStatus.void:
                raise HTTPException(status.HTTP_409_CONFLICT, "a void invoice can't be sent")
            party = await self._party(invoice.party_id)
            number = invoice.invoice_no
            pdf = await self.invoice_pdf(invoice.id)
            balance = self.balance_due(invoice)
            subject = f"Invoice {number} from {workspace.name}"
            summary = (
                f"<p>Please find attached invoice <b>{escape(number)}</b> for "
                f"<b>{escape(documents.fmt_money(invoice.total, currency))}</b>."
                + (f" The balance of <b>{escape(documents.fmt_money(balance, currency))}</b> is due on "
                   f"<b>{escape(documents.fmt_date(invoice.due_date))}</b>.</p>" if balance > 0 else " It has been paid in full — thank you.</p>")
            )
        elif kind == "quote":
            quote = await self.quotes.get(document_id)
            if quote is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "quote not found")
            party = await self._party(quote.party_id)
            number = quote.quote_no
            pdf = await self.quote_pdf(quote.id)
            subject = f"Quotation {number} from {workspace.name}"
            summary = (
                f"<p>Please find attached our quotation <b>{escape(number)}</b> for "
                f"<b>{escape(documents.fmt_money(quote.total, currency))}</b>, valid until "
                f"<b>{escape(documents.fmt_date(quote.valid_until))}</b>.</p>"
            )
            if quote.status == QuoteStatus.draft:
                quote.status = QuoteStatus.sent
        elif kind == "statement":
            party = await self._party(document_id)
            end = end or date.today()
            start = start or date(end.year, 1, 1)
            number = f"statement-{end.isoformat()}"
            pdf = await self.statement_pdf(party.id, start, end)
            balance = await self.customer_balance(party.id)
            subject = f"Statement of account from {workspace.name}"
            summary = (
                f"<p>Please find attached your statement of account to {escape(documents.fmt_date(end))}. "
                f"Your balance is <b>{escape(documents.fmt_money(balance, currency))}</b>.</p>"
            )
        else:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "unknown document type")

        recipient = (to or party.email or "").strip()
        if not recipient:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{party.name} has no email address — add one in CRM or type an address to send to",
            )
        note = f"<p>{escape(message).replace(chr(10), '<br>')}</p>" if message.strip() else ""
        how_to_pay = ""
        if kind != "quote" and workspace.mpesa_paybill:
            how_to_pay = f"<p>Pay by M-Pesa Paybill <b>{escape(workspace.mpesa_paybill)}</b>" + (
                f", account <b>{escape(number)}</b>.</p>" if kind == "invoice" else ".</p>"
            )
        result = await AccountService(self.session).send_logged(
            mailer.Mail(
                to=[recipient],
                cc=[c for c in cc if c.strip()],
                subject=subject,
                html=mailer.layout(
                    heading=subject,
                    body_html=f"<p>Dear {escape(party.name)},</p>{note}{summary}{how_to_pay}"
                              f"<p>Kind regards,<br>{escape(workspace.name)}</p>",
                    brand=workspace.brand_color or "#1a7a8c",
                    sender=" · ".join(b for b in [workspace.name, workspace.phone, workspace.billing_email] if b),
                ),
                text=f"{subject}. The document is attached as a PDF.",
                reply_to=workspace.billing_email,
                from_name=workspace.name,
                attachments=[mailer.Attachment(filename=f"{number}.pdf", content=pdf)],
            ),
            kind=kind, reference=number, workspace_id=self.workspace_id, sent_by=sent_by,
        )
        await self.session.commit()
        if result.backend == "smtp" and not result.delivered:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"the mail server rejected the message: {result.detail[:200]}")
        return {"to": recipient, "delivered": result.delivered, "backend": result.backend}

    # ---------------------------------------------------------------- reports

    async def customer_balance(self, party_id: str) -> Decimal:
        charges = select(func.coalesce(func.sum(ArPaymentEntry.amount), 0)).where(
            ArPaymentEntry.workspace_id == self.workspace_id,
            ArPaymentEntry.party_id == party_id,
            ArPaymentEntry.type == ArPaymentEntryType.invoice_charge,
        )
        # Credit notes reduce what the customer owes, same as payments.
        settlements = select(func.coalesce(func.sum(ArPaymentEntry.amount), 0)).where(
            ArPaymentEntry.workspace_id == self.workspace_id,
            ArPaymentEntry.party_id == party_id,
            ArPaymentEntry.type.in_([ArPaymentEntryType.payment, ArPaymentEntryType.credit_note]),
        )
        charge_total = Decimal((await self.session.execute(charges)).scalar_one())
        settled_total = Decimal((await self.session.execute(settlements)).scalar_one())
        return charge_total - settled_total

    async def ar_aging(self, as_of: date | None = None, party_id: str | None = None) -> dict:
        as_of = as_of or date.today()
        filters = [Invoice.status.in_([InvoiceStatus.posted, InvoiceStatus.partially_paid])]
        if party_id:
            filters.append(Invoice.party_id == party_id)
        invoices = await self.invoices.list(*filters)

        from app.modules.crm.models import Party

        parties = {p.id: p for p in await TenantRepository(self.session, self.workspace_id, Party).list()}
        rows: dict[str, dict] = defaultdict(lambda: {"buckets": empty_buckets(), "total": ZERO})
        totals = empty_buckets()
        for invoice in invoices:
            outstanding = self.balance_due(invoice)
            if outstanding <= 0:
                continue
            bucket = bucket_for(invoice.due_date, as_of)
            row = rows[invoice.party_id]
            row["buckets"][bucket] += outstanding
            row["total"] += outstanding
            totals[bucket] += outstanding
        return {
            "as_of": as_of,
            "rows": [
                {
                    "party_id": pid,
                    "party_name": parties[pid].name if pid in parties else pid,
                    **row["buckets"],
                    "total": row["total"],
                }
                for pid, row in sorted(rows.items(), key=lambda kv: -kv[1]["total"])
            ],
            "totals": {**totals, "total": sum(totals.values(), ZERO)},
        }

    async def customer_statement(self, party_id: str, start: date, end: date) -> dict:
        entries = await self.ar_entries.list(ArPaymentEntry.party_id == party_id)

        def entry_day(e: ArPaymentEntry) -> date:
            return e.entry_date or e.created_at.date()

        def signed(e: ArPaymentEntry) -> Decimal:
            return e.amount if e.type == ArPaymentEntryType.invoice_charge else -e.amount

        opening = sum((signed(e) for e in entries if entry_day(e) < start), ZERO)
        in_range = sorted(
            (e for e in entries if start <= entry_day(e) <= end), key=lambda e: (entry_day(e), e.created_at)
        )
        labels = {
            ArPaymentEntryType.invoice_charge: "Invoice",
            ArPaymentEntryType.payment: "Payment",
            ArPaymentEntryType.credit_note: "Credit note",
        }
        running = opening
        lines = []
        for e in in_range:
            running += signed(e)
            is_charge = e.type == ArPaymentEntryType.invoice_charge
            label = labels[e.type]
            if e.type == ArPaymentEntryType.credit_note and e.reference == "VOID":
                label = "Invoice voided"
            lines.append(
                {
                    "date": entry_day(e),
                    "type": label,
                    "document_no": e.document_no,
                    "reference": e.reference or e.method,
                    "debit": e.amount if is_charge else ZERO,
                    "credit": ZERO if is_charge else e.amount,
                    "balance": running,
                }
            )
        return {
            "party_id": party_id,
            "start": start,
            "end": end,
            "opening_balance": opening,
            "closing_balance": running,
            "lines": lines,
        }

    async def sales_summary(self, start: date, end: date) -> dict:
        """Revenue by product and by customer for a period, from invoice lines
        (net of discounts, before VAT, excluding void invoices)."""
        stmt = (
            select(InvoiceLine, Invoice.party_id)
            .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
            .where(
                InvoiceLine.workspace_id == self.workspace_id,
                Invoice.status != InvoiceStatus.void,
                Invoice.issue_date >= start,
                Invoice.issue_date <= end,
            )
        )
        by_product: dict[str, dict] = defaultdict(lambda: {"qty": ZERO, "revenue": ZERO, "description": ""})
        by_customer: dict[str, Decimal] = defaultdict(lambda: ZERO)
        for line, party_id in (await self.session.execute(stmt)).all():
            key = line.product_id or f"text:{line.description}"
            by_product[key]["qty"] += line.qty
            by_product[key]["revenue"] += line.line_subtotal
            by_product[key]["description"] = line.description
            by_customer[party_id] += line.line_subtotal

        from app.modules.crm.models import Party

        parties = {p.id: p.name for p in await TenantRepository(self.session, self.workspace_id, Party).list()}
        invoice_count_stmt = select(func.count(Invoice.id), func.coalesce(func.sum(Invoice.total), 0)).where(
            Invoice.workspace_id == self.workspace_id,
            Invoice.status != InvoiceStatus.void,
            Invoice.issue_date >= start,
            Invoice.issue_date <= end,
        )
        count, gross = (await self.session.execute(invoice_count_stmt)).one()
        return {
            "start": start,
            "end": end,
            "invoice_count": count,
            "total_invoiced": Decimal(gross),
            "by_product": sorted(
                (
                    {"product_id": None if k.startswith("text:") else k, **v}
                    for k, v in by_product.items()
                ),
                key=lambda r: -r["revenue"],
            )[:20],
            "by_customer": sorted(
                ({"party_id": k, "party_name": parties.get(k, k), "revenue": v} for k, v in by_customer.items()),
                key=lambda r: -r["revenue"],
            )[:20],
        }
