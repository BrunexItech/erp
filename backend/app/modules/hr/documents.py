"""Payslips (single or a whole run in one PDF) and the KRA P9A tax card,
on the same letterhead as the rest of the ERP's documents."""

from __future__ import annotations

import calendar
from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.pdf import (
    CONTENT_W,
    INK,
    MARGIN,
    RULE,
    ZEBRA,
    PdfStyles,
    brand_color,
    build_pdf,
    canvas_factory,
    fmt_date,
    fmt_money,
    highlight_box,
    letterhead,
    para,
    tint,
    two_col,
)

ZERO = Decimal("0")


def _section(rows: list[tuple[str, Decimal]], title: str, st: PdfStyles, brand, width: float, total_label: str) -> Table:
    data = [[para(title, st.th), para("KES", st.th_right)]]
    for label, amount in rows:
        data.append([para(label, st.cell), para(fmt_money(amount), st.cell_right)])
    total = sum((a for _, a in rows), ZERO)
    data.append(
        [
            Paragraph(f"<b>{escape(total_label)}</b>", st.cell),
            Paragraph(f"<b>{escape(fmt_money(total))}</b>", st.cell_right),
        ]
    )
    table = Table(data, colWidths=[width * 0.62, width * 0.38])
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), brand),
        ("LINEBELOW", (0, 1), (-1, -2), 0.4, RULE),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, INK),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for r in range(2, len(data) - 1, 2):
        style.append(("BACKGROUND", (0, r), (-1, r), ZEBRA))
    table.setStyle(TableStyle(style))
    return table


def _payslip_story(workspace, run, payslip, st: PdfStyles, brand) -> list:
    period = f"{calendar.month_name[run.period_month]} {run.period_year}"
    story = letterhead(
        workspace,
        st,
        "PAYSLIP",
        [("Pay Period", period), ("Pay Date", fmt_date(run.pay_date)), ("Payroll", run.run_no)],
    )

    details = [
        ("Employee", payslip.employee_name),
        ("Employee No.", payslip.employee_no),
        ("Department", payslip.department),
        ("Job Title", payslip.job_title),
        ("KRA PIN", payslip.kra_pin),
        ("NSSF No.", payslip.nssf_no),
        ("SHIF No.", payslip.shif_no),
    ]
    if payslip.days_worked != payslip.days_in_period:
        details.append(("Days Worked", f"{payslip.days_worked} of {payslip.days_in_period}"))
    detail_table = Table(
        [[para(k, st.muted), para(v, st.body)] for k, v in details if v],
        colWidths=[28 * mm, 62 * mm],
    )
    detail_table.setStyle(
        TableStyle([("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5), ("LEFTPADDING", (0, 0), (-1, -1), 0)])
    )
    pay_to = {
        "bank": f"{payslip.bank_name} · {payslip.bank_account}".strip(" ·"),
        "mpesa": f"M-Pesa {payslip.mpesa_phone}",
        "cash": "Cash",
    }.get(payslip.payment_method, "")
    story += [
        two_col(detail_table, highlight_box(brand, st, "NET PAY", fmt_money(payslip.net_pay, workspace.currency), pay_to)),
        Spacer(1, 7 * mm),
    ]

    earnings = [("Basic Salary", payslip.basic_salary)] + [
        (e["name"] + ("" if e.get("taxable", True) else " (non-taxable)"), Decimal(e["amount"]))
        for e in payslip.earnings
    ]
    deductions = [
        ("PAYE", payslip.paye),
        ("NSSF", payslip.nssf_employee),
        ("SHIF", payslip.shif),
        ("Housing Levy", payslip.housing_levy_employee),
    ] + [(d["name"], Decimal(d["amount"])) for d in payslip.deductions]
    half = (CONTENT_W - 6 * mm) / 2
    columns = Table(
        [[
            _section(earnings, "EARNINGS", st, brand, half, "Gross Pay"),
            "",
            _section([d for d in deductions if d[1]], "DEDUCTIONS", st, brand, half, "Total Deductions"),
        ]],
        colWidths=[half, 6 * mm, half],
    )
    columns.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story += [columns, Spacer(1, 7 * mm)]

    tax = [
        ("Taxable pay", payslip.taxable_pay),
        ("Tax charged", payslip.paye_before_relief),
        ("Personal relief", payslip.personal_relief),
        ("PAYE", payslip.paye),
    ]
    employer = [
        ("NSSF (employer)", payslip.nssf_employer),
        ("Housing Levy (employer)", payslip.housing_levy_employer),
        ("NITA levy", payslip.nita),
    ]
    info_style = ParagraphStyle("info", parent=st.small)
    tax_table = Table(
        [[para("TAX COMPUTATION", st.label), "", para("EMPLOYER CONTRIBUTIONS", st.label)]]
        + [
            [
                Paragraph(f"{escape(tax[i][0])}: <b>{fmt_money(tax[i][1])}</b>", info_style) if i < len(tax) else "",
                "",
                Paragraph(f"{escape(employer[i][0])}: <b>{fmt_money(employer[i][1])}</b>", info_style) if i < len(employer) else "",
            ]
            for i in range(max(len(tax), len(employer)))
        ],
        colWidths=[half, 6 * mm, half],
    )
    tax_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), tint(brand, 0.93)),
                ("BACKGROUND", (2, 0), (2, -1), tint(brand, 0.93)),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story += [
        tax_table,
        Spacer(1, 8 * mm),
        para("This is a computer-generated payslip and does not require a signature.", st.small),
    ]
    return story


def render_payslips(workspace, run, payslips: list) -> bytes:
    """One payslip per page — a single employee's slip, or the whole run."""
    brand = brand_color(workspace)
    st = PdfStyles(brand)
    story: list = []
    for i, payslip in enumerate(payslips):
        if i:
            story.append(PageBreak())
        story += _payslip_story(workspace, run, payslip, st, brand)
    return build_pdf(BytesIO(), story, workspace, brand, None, "Payslip")


def render_p9(workspace, p9: dict) -> bytes:
    """KRA P9A layout, landscape — twelve months across the year's columns."""
    brand = brand_color(workspace)
    st = PdfStyles(brand)
    page_w = landscape(A4)[0] - 2 * MARGIN - 12
    story = letterhead(
        workspace,
        st,
        "P9A TAX DEDUCTION CARD",
        [("Year", str(p9["year"])), ("Employee", p9["employee_name"]), ("Employee PIN", p9["kra_pin"]),
         ("Employer PIN", getattr(workspace, "tax_pin", ""))],
        width=page_w,
    )
    cols = [
        ("month", "Month"), ("basic_salary", "Basic Salary"), ("benefits", "Benefits"),
        ("gross_pay", "Gross Pay"), ("retirement_contribution", "Retirement Contrib."),
        ("shif", "SHIF"), ("housing_levy", "Housing Levy"), ("taxable_pay", "Chargeable Pay"),
        ("tax_charged", "Tax Charged"), ("personal_relief", "Personal Relief"), ("paye", "PAYE"),
    ]
    data = [[para(label, st.th if i == 0 else st.th_right) for i, (_, label) in enumerate(cols)]]
    for m in p9["months"]:
        data.append(
            [para(m["month"], st.cell)] + [para(fmt_money(m[k]), st.cell_right) for k, _ in cols[1:]]
        )
    data.append(
        [Paragraph("<b>TOTAL</b>", st.cell)]
        + [Paragraph(f"<b>{fmt_money(p9['totals'][k])}</b>", st.cell_right) for k, _ in cols[1:]]
    )
    first = 24 * mm
    rest = (page_w - first) / (len(cols) - 1)
    table = Table(data, colWidths=[first] + [rest] * (len(cols) - 1), repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), brand),
        ("LINEBELOW", (0, 1), (-1, -2), 0.4, RULE),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, INK),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]
    for r in range(2, len(data) - 1, 2):
        style.append(("BACKGROUND", (0, r), (-1, r), ZEBRA))
    table.setStyle(TableStyle(style))
    story += [table, Spacer(1, 6 * mm), para(
        "Chargeable pay is gross taxable pay less NSSF, pension (within the KES 30,000 cap), SHIF and the "
        "Housing Levy. PAYE = tax charged less personal relief.", st.small)]

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(A4), topMargin=12 * mm, bottomMargin=20 * mm,
        leftMargin=MARGIN, rightMargin=MARGIN, title="P9A", author=workspace.name,
    )
    doc.build(story, canvasmaker=canvas_factory(workspace, brand, None, page_size=landscape(A4)))
    return buffer.getvalue()

