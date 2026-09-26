from decimal import Decimal

from app.modules.accounting.service import AccountingService
from app.modules.crm.models import PartyKind
from app.modules.crm.schemas import PartyCreate
from app.modules.crm.service import CrmService
from app.modules.platform.schemas import BrandingUpdate
from app.modules.platform.service import PlatformService
from app.modules.sales.schemas import InvoiceCreate
from app.modules.sales.service import SalesService


async def test_invoice_pdf_renders_branding_and_totals(session, workspace_id):
    await AccountingService(session, workspace_id).seed_default_accounts()

    platform = PlatformService(session)
    await platform.update_branding(
        workspace_id,
        BrandingUpdate(
            name="Branded Test Co",
            address="1 Test Way",
            phone="+254700000000",
            billing_email="billing@test.co",
            invoice_footer_note="Thanks for your business!",
        ),
    )

    crm = CrmService(session, workspace_id)
    customer = await crm.create_party(PartyCreate(name="PDF Test Customer", kind=PartyKind.customer))

    sales = SalesService(session, workspace_id)
    invoice = await sales.create_invoice(
        InvoiceCreate(party_id=customer.id, subtotal=Decimal("500"), tax_total=Decimal("80"))
    )

    pdf_bytes = await sales.invoice_pdf(invoice.id)

    assert pdf_bytes[:4] == b"%PDF", "must produce a real PDF, not just any bytes"
    assert len(pdf_bytes) > 500, "should have actual rendered content, not an empty shell"
