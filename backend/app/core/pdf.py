"""Shared PDF building blocks for every printable document in the ERP —
tax invoices, quotes, statements, receipts, payslips, P9 cards.

Each document is rendered as the workspace's own letterhead: logo, name, KRA
PIN, contact details and brand colour, a brand band across the top, an
optional status stamp (PAID / OVERDUE / VOID) behind the content, and a
"Page x of y" footer. Modules build their own story out of these pieces and
hand it to build_pdf().
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO

import httpx

from app.core.media import local_logo_path
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from xml.sax.saxutils import escape

DEFAULT_BRAND = "#1a7a8c"
INK = colors.HexColor("#1f2937")
MUTED = colors.HexColor("#6b7280")
RULE = colors.HexColor("#e5e7eb")
ZEBRA = colors.HexColor("#f8fafc")

PAGE_W, PAGE_H = A4
MARGIN = 16 * mm
FRAME_PAD = 6  # SimpleDocTemplate's frame padding (points) on each side
CONTENT_W = PAGE_W - 2 * MARGIN - 2 * FRAME_PAD

STAMP_COLORS = {
    "PAID": colors.HexColor("#059669"),
    "VOID": colors.HexColor("#dc2626"),
    "OVERDUE": colors.HexColor("#dc2626"),
    "DECLINED": colors.HexColor("#dc2626"),
}

CURRENCY_WORDS = {
    "KES": ("Kenya Shillings", "Cents"),
    "UGX": ("Uganda Shillings", "Cents"),
    "TZS": ("Tanzania Shillings", "Cents"),
    "RWF": ("Rwanda Francs", "Centimes"),
    "USD": ("US Dollars", "Cents"),
    "EUR": ("Euros", "Cents"),
    "GBP": ("Pounds Sterling", "Pence"),
}


# --------------------------------------------------------------- formatting


PAYMENT_METHOD_LABELS = {
    "mpesa": "M-Pesa", "m-pesa": "M-Pesa", "cash": "Cash", "bank": "Bank transfer",
    "bank_transfer": "Bank transfer", "cheque": "Cheque", "card": "Card",
}


def fmt_method(method: str) -> str:
    return PAYMENT_METHOD_LABELS.get((method or "").lower(), (method or "—").replace("_", " ").title())


def fmt_date(value: date | None) -> str:
    return value.strftime("%d %b %Y") if value else ""


def fmt_money(value: Decimal | float | int, currency: str = "") -> str:
    text = f"{Decimal(value):,.2f}"
    return f"{currency} {text}" if currency else text


def fmt_qty(value: Decimal) -> str:
    value = Decimal(value)
    return f"{value:,.0f}" if value == value.to_integral() else f"{value.normalize():,f}"


def fmt_pct(rate: Decimal, *, fraction: bool) -> str:
    pct = Decimal(rate) * 100 if fraction else Decimal(rate)
    return f"{pct.normalize():f}%" if pct else "—"


_ONES = [
    "", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
    "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen",
]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]
_SCALES = [(10**12, "Trillion"), (10**9, "Billion"), (10**6, "Million"), (10**3, "Thousand")]


def _below_thousand(n: int) -> str:
    words = []
    if n >= 100:
        words.append(f"{_ONES[n // 100]} Hundred")
        n %= 100
        if n:
            words.append("and")
    if n >= 20:
        words.append(_TENS[n // 10] + (f"-{_ONES[n % 10]}" if n % 10 else ""))
    elif n:
        words.append(_ONES[n])
    return " ".join(words)


def number_to_words(n: int) -> str:
    if n == 0:
        return "Zero"
    parts = []
    for scale, name in _SCALES:
        if n >= scale:
            parts.append(f"{number_to_words(n // scale)} {name}")
            n %= scale
    if n:
        if parts and n < 100:
            parts.append("and")
        parts.append(_below_thousand(n))
    return " ".join(parts)


def amount_in_words(amount: Decimal, currency: str) -> str:
    major_name, minor_name = CURRENCY_WORDS.get(currency, (currency, "Cents"))
    amount = Decimal(amount).quantize(Decimal("0.01"))
    major = int(amount)
    minor = int((amount - major) * 100)
    text = f"{major_name} {number_to_words(major)}"
    if minor:
        text += f" and {minor_name} {number_to_words(minor)}"
    return f"{text} Only"


# ------------------------------------------------------------------- styles


TEMPLATES = ("modern", "bold", "classic")


def template_of(workspace) -> str:
    value = getattr(workspace, "invoice_template", "") or "modern"
    return value if value in TEMPLATES else "modern"


def real_brand(workspace) -> colors.Color:
    try:
        return colors.HexColor(getattr(workspace, "brand_color", "") or DEFAULT_BRAND)
    except ValueError:
        return colors.HexColor(DEFAULT_BRAND)


def brand_color(workspace) -> colors.Color:
    """Accent used for table headers, totals and highlight panels. The Classic
    design is deliberately monochrome — near-black ink, with the company's
    colour kept to a thin band — so it returns ink instead."""
    if template_of(workspace) == "classic":
        return colors.HexColor("#111827")
    return real_brand(workspace)


def tint(color: colors.Color, amount: float) -> colors.Color:
    """Mix `color` toward white; amount=0.9 -> 90% white."""
    return colors.Color(
        color.red + (1 - color.red) * amount,
        color.green + (1 - color.green) * amount,
        color.blue + (1 - color.blue) * amount,
    )


class PdfStyles:
    def __init__(self, brand: colors.Color):
        base = dict(fontName="Helvetica", fontSize=8.5, leading=11.5, textColor=INK)
        self.body = ParagraphStyle("body", **base)
        self.muted = ParagraphStyle("muted", **{**base, "textColor": MUTED})
        self.small = ParagraphStyle("small", **{**base, "fontSize": 7.5, "leading": 10, "textColor": MUTED})
        self.company = ParagraphStyle(
            "company", fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=INK
        )
        self.title = ParagraphStyle(
            "title", fontName="Helvetica-Bold", fontSize=21, leading=24, textColor=brand, alignment=TA_RIGHT
        )
        self.label = ParagraphStyle(
            "label", fontName="Helvetica-Bold", fontSize=7, leading=9, textColor=brand
        )
        self.party = ParagraphStyle("party", fontName="Helvetica-Bold", fontSize=10.5, leading=13, textColor=INK)
        self.meta_label = ParagraphStyle("meta_label", **{**base, "textColor": MUTED, "alignment": TA_RIGHT})
        self.meta_value = ParagraphStyle(
            "meta_value", **{**base, "fontName": "Helvetica-Bold", "alignment": TA_RIGHT}
        )
        self.th = ParagraphStyle(
            "th", fontName="Helvetica-Bold", fontSize=7.5, leading=9, textColor=colors.white
        )
        self.th_right = ParagraphStyle("th_right", parent=self.th, alignment=TA_RIGHT)
        self.cell = ParagraphStyle("cell", **base)
        self.cell_right = ParagraphStyle("cell_right", **{**base, "alignment": TA_RIGHT})
        self.due_label = ParagraphStyle(
            "due_label", fontName="Helvetica-Bold", fontSize=7, leading=9, textColor=colors.white
        )
        self.due_amount = ParagraphStyle(
            "due_amount", fontName="Helvetica-Bold", fontSize=17, leading=21, textColor=colors.white
        )
        self.due_sub = ParagraphStyle(
            "due_sub", fontName="Helvetica", fontSize=8, leading=10, textColor=tint(brand, 0.75)
        )


def para(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(text or "").replace("\n", "<br/>"), style)


# ------------------------------------------------------------ page chrome


def fetch_logo(logo_url: str, max_h: float = 20 * mm, max_w: float = 55 * mm) -> Image | None:
    """Best-effort logo load — a missing/unreachable logo must never break
    document generation, so any failure here just means no logo on the page.
    Uploaded logos are read straight from disk; external URLs are fetched."""
    try:
        local = local_logo_path(logo_url)
        if local is not None:
            image = Image(str(local))
        elif logo_url.startswith(("http://", "https://")):
            response = httpx.get(logo_url, timeout=5.0, follow_redirects=True)
            response.raise_for_status()
            image = Image(BytesIO(response.content))
        else:
            return None
        ratio = image.imageWidth / image.imageHeight
        image.drawHeight = max_h
        image.drawWidth = max_h * ratio
        if image.drawWidth > max_w:
            image.drawWidth = max_w
            image.drawHeight = max_w / ratio
        return image
    except Exception:
        return None


def canvas_factory(workspace, brand: colors.Color, stamp: str | None, page_size=A4):
    page_w, page_h = page_size
    footer_left = getattr(workspace, "invoice_footer_note", "") or "Thank you for your business."
    pin = getattr(workspace, "tax_pin", "")
    footer_mid = workspace.name + (f"  ·  PIN {pin}" if pin else "")
    template = template_of(workspace)
    band = real_brand(workspace)

    class DocumentCanvas(rl_canvas.Canvas):
        """Two-pass canvas: pages are buffered so the footer can say
        'Page x of y' once the total page count is known."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._pages: list[dict] = []

        def showPage(self):
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._pages)
            for number, state in enumerate(self._pages, start=1):
                self.__dict__.update(state)
                self._draw_chrome(number, total)
                super().showPage()
            super().save()

        def _draw_chrome(self, number: int, total: int):
            # Brand band across the top edge (the Bold design has its own
            # full colour header block instead).
            if template != "bold":
                self.setFillColor(band)
                self.rect(0, page_h - (2.5 if template == "classic" else 4) * mm, page_w, 4 * mm, stroke=0, fill=1)

            if stamp and number == 1:
                color = STAMP_COLORS.get(stamp, brand)
                self.saveState()
                self.translate(page_w - 62 * mm, page_h - 118 * mm)
                self.rotate(18)
                self.setStrokeColor(color, alpha=0.35)
                self.setFillColor(color, alpha=0.35)
                self.setLineWidth(3)
                width = 12 * mm + len(stamp) * 9 * mm
                self.roundRect(-width / 2, -9 * mm, width, 20 * mm, 4 * mm, stroke=1, fill=0)
                self.setFont("Helvetica-Bold", 30)
                self.drawCentredString(0, -1.5 * mm, stamp)
                self.restoreState()

            self.setStrokeColor(RULE)
            self.setLineWidth(0.6)
            left, right = MARGIN + FRAME_PAD, page_w - MARGIN - FRAME_PAD
            self.line(left, 14 * mm, right, 14 * mm)
            self.setFont("Helvetica", 7)
            self.setFillColor(MUTED)
            self.drawString(left, 9.5 * mm, footer_left[:110])
            self.drawCentredString(page_w / 2, 5.5 * mm, footer_mid[:110])
            self.drawRightString(right, 9.5 * mm, f"Page {number} of {total}")

    return DocumentCanvas


def _meta_table(
    meta: list[tuple[str, str]], label_style: ParagraphStyle, value_style: ParagraphStyle, value_width: float = 50 * mm
) -> Table:
    rows = [[para(k, label_style), para(v, value_style)] for k, v in meta if v]
    table = Table(rows or [["", ""]], colWidths=[27 * mm, value_width], hAlign="RIGHT")
    table.setStyle(
        TableStyle(
            [
                ("TOPPADDING", (0, 0), (-1, -1), 1.2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.2),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return table


def _contact_lines(workspace) -> list[str]:
    return [
        line
        for line in [
            workspace.address,
            "  ·  ".join(b for b in [workspace.phone, workspace.billing_email] if b),
            getattr(workspace, "website", ""),
        ]
        if line
    ]


def letterhead(workspace, st: PdfStyles, title: str, meta: list[tuple[str, str]], width: float = CONTENT_W) -> list:
    """The top of every document, in the workspace's chosen design."""
    template = template_of(workspace)
    logo = fetch_logo(workspace.logo_url) if workspace.logo_url else None
    pin = getattr(workspace, "tax_pin", "")

    if template == "bold":
        return _letterhead_bold(workspace, st, title, meta, width, logo, pin)
    if template == "classic":
        return _letterhead_classic(workspace, st, title, meta, width, logo, pin)

    left: list = []
    if logo is not None:
        logo.hAlign = "LEFT"
        left += [logo, Spacer(1, 3 * mm)]
    left.append(para(workspace.name, st.company))
    left += [para(line, st.muted) for line in _contact_lines(workspace)]
    if pin:
        left.append(Paragraph(f"<b>KRA PIN:</b> {escape(pin)}", st.body))
    right = [para(title, st.title), Spacer(1, 3 * mm), _meta_table(meta, st.meta_label, st.meta_value)]

    header = Table([[left, right]], colWidths=[width * 0.55, width * 0.45])
    header.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return [header, Spacer(1, 5 * mm)]


def _letterhead_bold(workspace, st, title, meta, width, logo, pin) -> list:
    """A full-width block in the company colour: white type, logo on a white
    plate so it reads on any brand colour."""
    brand = real_brand(workspace)
    soft = tint(brand, 0.78)
    white = colors.white
    name = ParagraphStyle("b_name", fontName="Helvetica-Bold", fontSize=16, leading=19, textColor=white)
    contact = ParagraphStyle("b_contact", fontName="Helvetica", fontSize=8.5, leading=11.5, textColor=soft)
    title_style = ParagraphStyle("b_title", fontName="Helvetica-Bold", fontSize=22, leading=25, textColor=white, alignment=TA_RIGHT)
    label = ParagraphStyle("b_label", parent=st.meta_label, textColor=soft)
    value = ParagraphStyle("b_value", parent=st.meta_value, textColor=white)

    left: list = []
    if logo is not None:
        plate = Table([[logo]], colWidths=[logo.drawWidth + 6 * mm], rowHeights=[logo.drawHeight + 5 * mm], hAlign="LEFT")
        plate.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), white),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ROUNDEDCORNERS", [2 * mm] * 4),
                ]
            )
        )
        left += [plate, Spacer(1, 3 * mm)]
    left.append(para(workspace.name, name))
    left += [para(line, contact) for line in _contact_lines(workspace)]
    if pin:
        left.append(para(f"KRA PIN: {pin}", contact))
    pad = 7 * mm
    right_width = width * 0.48
    # The padded column is narrower than the page column the other designs use.
    right = [para(title, title_style), Spacer(1, 3 * mm), _meta_table(meta, label, value, right_width - pad - 27 * mm - 12)]

    block = Table([[left, right]], colWidths=[width - right_width, right_width])
    block.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), brand),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (0, 0), pad),
                ("RIGHTPADDING", (1, 0), (1, 0), pad),
                ("TOPPADDING", (0, 0), (-1, -1), pad),
                ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
                ("ROUNDEDCORNERS", [3 * mm] * 4),
            ]
        )
    )
    return [block, Spacer(1, 7 * mm)]


def _letterhead_classic(workspace, st, title, meta, width, logo, pin) -> list:
    """Centred, monochrome, formal — the look of a printed letterhead."""
    from reportlab.lib.enums import TA_CENTER

    ink = colors.HexColor("#111827")
    name = ParagraphStyle("c_name", fontName="Times-Bold", fontSize=19, leading=23, textColor=ink, alignment=TA_CENTER)
    contact = ParagraphStyle("c_contact", fontName="Helvetica", fontSize=8.5, leading=12, textColor=MUTED, alignment=TA_CENTER)
    title_style = ParagraphStyle("c_title", fontName="Times-Bold", fontSize=17, leading=21, textColor=ink)

    story: list = []
    if logo is not None:
        logo.hAlign = "CENTER"
        story += [logo, Spacer(1, 2.5 * mm)]
    story.append(para(workspace.name, name))
    details = "   |   ".join(_contact_lines(workspace) + ([f"KRA PIN {pin}"] if pin else []))
    if details:
        story.append(para(details, contact))
    story += [
        Spacer(1, 3.5 * mm),
        Table([[""]], colWidths=[width], rowHeights=[1.2 * mm], style=TableStyle([("LINEABOVE", (0, 0), (-1, -1), 1.4, ink), ("LINEBELOW", (0, 0), (-1, -1), 0.4, ink)])),
        Spacer(1, 5 * mm),
    ]
    row = Table([[para(title, title_style), _meta_table(meta, st.meta_label, st.meta_value)]], colWidths=[width * 0.5, width * 0.5])
    row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story += [row, Spacer(1, 5 * mm)]
    return story


def party_block(party, st: PdfStyles, label: str) -> list:
    block = [para(label, st.label), Spacer(1, 1.2 * mm), para(party.name, st.party)]
    for line in [party.billing_address, party.phone, party.email]:
        if line:
            block.append(para(line, st.body))
    if party.tax_id:
        block.append(Paragraph(f"<b>PIN:</b> {escape(party.tax_id)}", st.body))
    return block


def highlight_box(brand, st: PdfStyles, label: str, amount: str, sub: str) -> Table:
    content = [para(label, st.due_label), Spacer(1, 1 * mm), para(amount, st.due_amount)]
    if sub:
        content.append(para(sub, st.due_sub))
    box = Table([[content]], colWidths=[70 * mm])
    box.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), brand),
                ("LEFTPADDING", (0, 0), (-1, -1), 5 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 3.5 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5 * mm),
                ("ROUNDEDCORNERS", [2.5 * mm] * 4),
            ]
        )
    )
    box.hAlign = "RIGHT"
    return box


def two_col(left, right, split: float = 0.55) -> Table:
    t = Table([[left, right]], colWidths=[CONTENT_W * split, CONTENT_W * (1 - split)])
    t.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ]
        )
    )
    return t


def payment_details(workspace, st: PdfStyles, reference: str) -> list:
    rows = []
    paybill = getattr(workspace, "mpesa_paybill", "")
    till = getattr(workspace, "mpesa_till", "")
    bank = getattr(workspace, "bank_details", "")
    if paybill:
        acct = f"  ·  Account: <b>{escape(reference)}</b>" if reference else ""
        rows.append(Paragraph(f"<b>M-Pesa Paybill:</b> {escape(paybill)}{acct}", st.body))
    if till:
        rows.append(Paragraph(f"<b>M-Pesa Till (Buy Goods):</b> {escape(till)}", st.body))
    if bank:
        rows.append(Paragraph("<b>Bank transfer</b>", st.body))
        rows.append(para(bank, st.body))
    if not rows:
        return []
    return [para("HOW TO PAY", st.label), Spacer(1, 1.2 * mm), *rows]


def build_pdf(buffer: BytesIO, story: list, workspace, brand, stamp: str | None, title: str) -> bytes:
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=12 * mm,
        bottomMargin=20 * mm,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        title=title,
        author=workspace.name,
    )
    doc.build(story, canvasmaker=canvas_factory(workspace, brand, stamp))
    return buffer.getvalue()


