import os
from io import BytesIO

import pytest
from fastapi import HTTPException
from PIL import Image, ImageDraw

from app.core import media
from app.modules.platform.schemas import BrandingUpdate
from app.modules.platform.service import PlatformService
from app.modules.sales.service import SalesService


def _logo_png() -> bytes:
    image = Image.new("RGBA", (600, 240), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle([10, 30, 190, 210], radius=36, fill=(234, 88, 12, 255))
    draw.polygon([(60, 160), (100, 70), (140, 160)], fill=(255, 255, 255, 255))
    draw.rectangle([220, 80, 580, 110], fill=(30, 41, 59, 255))
    draw.rectangle([220, 130, 470, 150], fill=(100, 116, 139, 255))
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def test_logo_upload_is_normalised_and_fakes_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(media.settings, "media_root", str(tmp_path))
    url = media.save_logo("ws-1", _logo_png())
    assert url.startswith(media.LOGO_URL_PREFIX) and url.endswith(".png")
    assert media.local_logo_path(url).is_file()

    # A second upload replaces the first file rather than piling up.
    big = Image.new("RGB", (3000, 1500), (10, 120, 140))
    buf = BytesIO()
    big.save(buf, format="JPEG")
    url2 = media.save_logo("ws-1", buf.getvalue())
    assert url2 != url and media.local_logo_path(url) is None
    assert max(Image.open(media.local_logo_path(url2)).size) <= media.MAX_SIDE

    with pytest.raises(HTTPException):
        media.save_logo("ws-1", b"<script>alert(1)</script>")
    # No escaping the logo folder through the URL.
    assert media.local_logo_path(media.LOGO_URL_PREFIX + "../../etc/passwd") is None


async def test_every_template_renders_with_uploaded_logo(session, workspace_id, tmp_path, monkeypatch):
    monkeypatch.setattr(media.settings, "media_root", str(tmp_path))
    platform = PlatformService(session)
    await platform.update_branding(
        workspace_id,
        BrandingUpdate(
            name="Savanna Fresh Foods Ltd", logo_url=media.save_logo(workspace_id, _logo_png()),
            address="Mombasa Road, Nairobi", phone="+254 711 222 333", billing_email="accounts@savanna.co.ke",
            website="www.savanna.co.ke", tax_pin="P051222333Q", brand_color="#c2410c", mpesa_paybill="400200",
            bank_details="Equity Bank, Westlands\nA/C 0170298765432",
            invoice_terms="Payment within 30 days of invoice date.",
        ),
    )
    sales = SalesService(session, workspace_id)
    out_dir = os.environ.get("ERP_PDF_OUT")
    for template in ("modern", "bold", "classic"):
        pdf = await sales.sample_invoice_pdf(template, None)
        assert pdf[:4] == b"%PDF" and len(pdf) > 3000, template
        if out_dir:
            open(os.path.join(out_dir, f"tpl-{template}.pdf"), "wb").write(pdf)
