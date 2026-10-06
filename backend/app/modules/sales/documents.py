"""Branded commercial documents: tax invoices, quotations, credit notes,
payment receipts and customer statements.

Laid out the way an East African SME's customers and auditors expect a tax
invoice: sequential number, dates, both parties' KRA PINs, per-line VAT,
totals that add up line by line, the amount in words, and how to pay (bank /
M-Pesa paybill with the invoice number as the account reference). The shared
letterhead, stamps and footer come from app/core/pdf.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, Spacer, Table, TableStyle
from reportlab.platypus.flowables import HRFlowable

from app.core.pdf import (
    CONTENT_W,
    INK,
    RULE,
    ZEBRA,
    PdfStyles,
    amount_in_words,
    brand_color,
    build_pdf,
    fmt_date,
    fmt_method,
    fmt_money,
    fmt_pct,
    fmt_qty,
    highlight_box,
    letterhead,
    para,
    party_block,
    payment_details,
    tint,
    two_col,
)

__all__ = ["DocLine", "Totals", "amount_in_words", "fmt_date", "line_from_model", "render_document", "render_receipt", "render_statement"]


@dataclass
class DocLine:
    description: str
    qty: Decimal
    unit_price: Decimal
    discount_pct: Decimal
    tax_rate: Decimal
    amount: Decimal  # net of discount, before tax


@dataclass
class Totals:
    subtotal: Decimal  # before discount
    discount: Decimal
    tax: Decimal
    total: Decimal
    paid: Decimal = Decimal("0")
    credited: Decimal = Decimal("0")
    balance: Decimal | None = None


def line_from_model(line) -> DocLine:
    return DocLine(
        description=line.description,
        qty=line.qty,
        unit_price=line.unit_price,
        discount_pct=line.discount_pct,
        tax_rate=line.tax_rate,
        amount=line.line_subtotal,
    )


# ---------------------------------------------------------------- documents


def render_document(
    *,
    workspace,
    party,
    title: str,
    meta: list[tuple[str, str]],
    lines: list[DocLine],
    totals: Totals,
    notes: str = "",
    terms: str = "",
    payment_reference: str = "",
    stamp: str | None = None,
    show_payment_details: bool = True,
    fiscal: dict | None = None,
) -> bytes:
    brand = brand_color(workspace)
    st = PdfStyles(brand)
    currency = workspace.currency or ""
    story: list = []

    story += letterhead(workspace, st, title, meta)

    is_invoice = totals.balance is not None
    if is_invoice:
        due_value = next((v for k, v in meta if k == "Due Date"), "")
        highlight = highlight_box(
            brand, st, "BALANCE DUE", fmt_money(totals.balance, currency),
            f"Due {due_value}" if due_value and totals.balance > 0 else ("Settled in full" if totals.balance <= 0 else ""),
        )
    else:
        highlight = highlight_box(brand, st, "TOTAL", fmt_money(totals.total, currency), "")
    bill_to_label = "CREDIT TO" if title == "CREDIT NOTE" else ("QUOTATION FOR" if title == "QUOTATION" else "BILL TO")
    left = party_block(party, st, bill_to_label)
    if party.shipping_address and party.shipping_address != party.billing_address:
        left += [Spacer(1, 3 * mm), para("SHIP TO", st.label), Spacer(1, 1.2 * mm), para(party.shipping_address, st.body)]
    story += [two_col(left, highlight), Spacer(1, 7 * mm)]

    # ---- line items
    show_discount = any(l.discount_pct for l in lines)
    headers = ["#", "Description", "Qty", "Unit Price"]
    widths = [8 * mm, None, 16 * mm, 27 * mm]
    if show_discount:
        headers.append("Disc.")
        widths.append(15 * mm)
    headers += ["VAT", "Amount"]
    widths += [15 * mm, 30 * mm]
    fixed = sum(w for w in widths if w)
    widths[1] = CONTENT_W - fixed

    data = [[para(h, st.th if i < 2 else st.th_right) for i, h in enumerate(headers)]]
    for i, line in enumerate(lines, start=1):
        row = [
            para(str(i), st.cell),
            para(line.description, st.cell),
            para(fmt_qty(line.qty), st.cell_right),
            para(fmt_money(line.unit_price), st.cell_right),
        ]
        if show_discount:
            row.append(para(fmt_pct(line.discount_pct, fraction=False), st.cell_right))
        row += [
            para(fmt_pct(line.tax_rate, fraction=True), st.cell_right),
            para(fmt_money(line.amount), st.cell_right),
        ]
        data.append(row)
    if not lines:
        data.append(
            [para("", st.cell), para("Invoice total (not itemised)", st.muted)]
            + [para("", st.cell)] * (len(headers) - 3)
            + [para(fmt_money(totals.subtotal - totals.discount), st.cell_right)]
        )

    items = Table(data, colWidths=widths, repeatRows=1)
    item_style = [
        ("BACKGROUND", (0, 0), (-1, 0), brand),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, RULE),
    ]
    for r in range(2, len(data), 2):
        item_style.append(("BACKGROUND", (0, r), (-1, r), ZEBRA))
    items.setStyle(TableStyle(item_style))
    story += [items, Spacer(1, 5 * mm)]

    # ---- totals + words/payment
    total_rows: list[tuple[str, str, bool]] = [("Subtotal", fmt_money(totals.subtotal), False)]
    if totals.discount:
        total_rows.append(("Discount", f"-{fmt_money(totals.discount)}", False))
    total_rows.append(("VAT", fmt_money(totals.tax), False))
    total_rows.append((f"Total ({currency})" if currency else "Total", fmt_money(totals.total), True))
    if is_invoice:
        if totals.paid:
            total_rows.append(("Amount Paid", f"-{fmt_money(totals.paid)}", False))
        if totals.credited:
            total_rows.append(("Credited", f"-{fmt_money(totals.credited)}", False))

    tdata = [[para(label, st.cell_right), para(value, st.cell_right)] for label, value, _ in total_rows]
    tstyle = [
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]
    for idx, (_, _, bold) in enumerate(total_rows):
        if bold:
            tstyle += [
                ("LINEABOVE", (0, idx), (-1, idx), 0.8, INK),
                ("FONTNAME", (0, idx), (-1, idx), "Helvetica-Bold"),
            ]
            tdata[idx] = [
                Paragraph(f"<b>{escape(total_rows[idx][0])}</b>", st.cell_right),
                Paragraph(f"<b>{escape(total_rows[idx][1])}</b>", st.cell_right),
            ]
    if is_invoice:
        tdata.append(
            [
                Paragraph("<b>Balance Due</b>", ParagraphStyle("bd", parent=st.cell_right, textColor=colors.white)),
                Paragraph(
                    f"<b>{escape(fmt_money(totals.balance, currency))}</b>",
                    ParagraphStyle("bdv", parent=st.cell_right, textColor=colors.white),
                ),
            ]
        )
        tstyle.append(("BACKGROUND", (0, len(tdata) - 1), (-1, len(tdata) - 1), brand))
    totals_table = Table(tdata, colWidths=[35 * mm, 38 * mm], hAlign="RIGHT")
    totals_table.setStyle(TableStyle(tstyle))

    left_block: list = [
        para("AMOUNT IN WORDS", st.label),
        Spacer(1, 1.2 * mm),
        para(amount_in_words(totals.total, currency), st.body),
        Spacer(1, 4 * mm),
    ]
    if show_payment_details:
        left_block += payment_details(workspace, st, payment_reference)
    story.append(KeepTogether(two_col(left_block, totals_table, split=0.57)))

    # ---- KRA eTIMS: control number + verification QR
    if fiscal:
        from app.core.pdf import qr_flowable

        label = "KRA eTIMS — TEST MODE, NOT A FISCAL RECEIPT" if fiscal.get("is_test") else "KRA eTIMS"
        block = Table(
            [[
                qr_flowable(fiscal["qr"], 24 * mm),
                [
                    para(label, st.label),
                    Spacer(1, 1.2 * mm),
                    Paragraph(f"Control unit invoice no.: <b>{escape(fiscal['reference'])}</b>", st.body),
                    para("Scan the code to verify this invoice with KRA.", st.small),
                ],
            ]],
            colWidths=[28 * mm, CONTENT_W - 28 * mm],
        )
        block.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        story += [Spacer(1, 5 * mm), HRFlowable(width="100%", thickness=0.5, color=RULE), Spacer(1, 3 * mm), KeepTogether(block)]

    # ---- notes / terms
    for label, text in (("NOTES", notes), ("TERMS & CONDITIONS", terms)):
        if text:
            story += [
                Spacer(1, 6 * mm),
                HRFlowable(width="100%", thickness=0.5, color=RULE),
                Spacer(1, 3 * mm),
                para(label, st.label),
                Spacer(1, 1.2 * mm),
                para(text, st.muted),
            ]

    return build_pdf(BytesIO(), story, workspace, brand, stamp, title)


def render_receipt(
    *,
    workspace,
    party,
    receipt_no: str,
    receipt_date: date,
    amount: Decimal,
    method: str,
    reference: str,
    invoice_no: str,
    balance_after: Decimal | None,
) -> bytes:
    brand = brand_color(workspace)
    st = PdfStyles(brand)
    currency = workspace.currency or ""
    story = letterhead(
        workspace,
        st,
        "PAYMENT RECEIPT",
        [("Receipt No.", receipt_no), ("Date", fmt_date(receipt_date))],
    )
    story += [
        two_col(
            party_block(party, st, "RECEIVED FROM"),
            highlight_box(brand, st, "AMOUNT RECEIVED", fmt_money(amount, currency), fmt_method(method) if method else ""),
        ),
        Spacer(1, 8 * mm),
    ]
    rows = [
        ("Amount in words", amount_in_words(amount, currency)),
        ("Payment method", fmt_method(method)),
        ("Transaction reference", reference or "—"),
        ("Applied to invoice", invoice_no or "—"),
    ]
    if balance_after is not None:
        rows.append(("Invoice balance remaining", fmt_money(balance_after, currency)))
    table = Table(
        [[para(k, st.muted), para(v, st.body)] for k, v in rows],
        colWidths=[50 * mm, CONTENT_W - 50 * mm],
    )
    table.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story += [table, Spacer(1, 22 * mm)]
    sign = Table(
        [[para("Received by", st.small), "", para("Signature & stamp", st.small)]],
        colWidths=[CONTENT_W * 0.42, CONTENT_W * 0.16, CONTENT_W * 0.42],
    )
    sign.setStyle(
        TableStyle(
            [
                ("LINEABOVE", (0, 0), (0, 0), 0.6, INK),
                ("LINEABOVE", (2, 0), (2, 0), 0.6, INK),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(sign)
    return build_pdf(BytesIO(), story, workspace, brand, None, "Payment Receipt")


def render_statement(*, workspace, party, statement: dict, aging: dict) -> bytes:
    brand = brand_color(workspace)
    st = PdfStyles(brand)
    currency = workspace.currency or ""
    story = letterhead(
        workspace,
        st,
        "STATEMENT",
        [
            ("Statement Date", fmt_date(statement["end"])),
            ("Period", f"{fmt_date(statement['start'])} – {fmt_date(statement['end'])}"),
        ],
    )
    closing = statement["closing_balance"]
    story += [
        two_col(
            party_block(party, st, "ACCOUNT"),
            highlight_box(
                brand, st, "BALANCE DUE" if closing >= 0 else "IN CREDIT", fmt_money(abs(closing), currency),
                f"as at {fmt_date(statement['end'])}",
            ),
        ),
        Spacer(1, 7 * mm),
    ]

    headers = ["Date", "Transaction", "Document", "Reference", "Debit", "Credit", "Balance"]
    widths = [23 * mm, 28 * mm, 24 * mm, None, 22 * mm, 22 * mm, 24 * mm]
    widths[3] = CONTENT_W - sum(w for w in widths if w)
    data = [[para(h, st.th if i < 4 else st.th_right) for i, h in enumerate(headers)]]
    data.append(
        [
            para(fmt_date(statement["start"]), st.cell),
            Paragraph("<b>Opening balance</b>", st.cell),
            para("", st.cell), para("", st.cell), para("", st.cell), para("", st.cell),
            para(fmt_money(statement["opening_balance"]), st.cell_right),
        ]
    )
    for line in statement["lines"]:
        data.append(
            [
                para(fmt_date(line["date"]), st.cell),
                para(line["type"], st.cell),
                para(line["document_no"], st.cell),
                para(line["reference"], st.cell),
                para(fmt_money(line["debit"]) if line["debit"] else "", st.cell_right),
                para(fmt_money(line["credit"]) if line["credit"] else "", st.cell_right),
                para(fmt_money(line["balance"]), st.cell_right),
            ]
        )
    data.append(
        [
            para("", st.cell), Paragraph("<b>Closing balance</b>", st.cell),
            para("", st.cell), para("", st.cell), para("", st.cell), para("", st.cell),
            Paragraph(f"<b>{escape(fmt_money(closing))}</b>", st.cell_right),
        ]
    )
    table = Table(data, colWidths=widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), brand),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, RULE),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, INK),
    ]
    for r in range(2, len(data) - 1, 2):
        style.append(("BACKGROUND", (0, r), (-1, r), ZEBRA))
    table.setStyle(TableStyle(style))
    story += [table, Spacer(1, 7 * mm)]

    labels = [
        ("Current", "current"), ("1–30 days", "days_1_30"), ("31–60 days", "days_31_60"),
        ("61–90 days", "days_61_90"), ("Over 90", "over_90"), ("Total due", "total"),
    ]
    aging_table = Table(
        [
            [para(l, st.th_right) for l, _ in labels],
            [para(fmt_money(aging.get(k, 0)), st.cell_right) for _, k in labels],
        ],
        colWidths=[CONTENT_W / len(labels)] * len(labels),
    )
    aging_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), tint(brand, 0.15)),
                ("BOX", (0, 0), (-1, -1), 0.5, RULE),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story += [KeepTogether([para("AGEING SUMMARY", st.label), Spacer(1, 1.5 * mm), aging_table]), Spacer(1, 6 * mm)]
    story += payment_details(workspace, st, "")
    return build_pdf(BytesIO(), story, workspace, brand, None, "Statement of Account")
