"""KRA eTIMS (electronic Tax Invoice Management System) integration seam.

Kenyan law requires tax invoices to be transmitted to KRA, which returns a
control-unit invoice number and a QR code that must be printed on the invoice.

What is here: everything around the KRA call — per-business mode, invoice
status tracking, the fields and QR code on the printed invoice, and retry of
failed submissions. What is NOT here: the live KRA call itself, which needs
the business's eTIMS device credentials (PIN, branch id, device serial,
communication key) and KRA's current OSCU/VSCU API specification.

Modes (Workspace.etims_mode):
  off      — invoices are not submitted (default).
  test     — a simulated response, so the workflow can be exercised end to
             end. Receipts say "TEST" and are NOT fiscal documents.
  live     — submit to KRA. Raises EtimsNotConfigured until LiveGateway is
             implemented with real credentials.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal


class EtimsError(Exception):
    """Submission failed; the invoice stays valid and can be retried."""


class EtimsNotConfigured(EtimsError):
    pass


@dataclass(frozen=True)
class EtimsInvoice:
    """What a gateway needs, independent of our database models."""

    invoice_no: str
    issued_on: str  # ISO date
    seller_pin: str
    buyer_pin: str
    buyer_name: str
    lines: list[dict]  # {description, qty, unit_price, tax_rate, taxable, vat}
    taxable: Decimal
    vat: Decimal
    total: Decimal


@dataclass(frozen=True)
class EtimsReceipt:
    reference: str  # KRA control-unit invoice number
    qr_data: str  # what the printed QR code encodes (KRA verification URL)
    submitted_at: datetime
    is_test: bool


class TestGateway:
    """Deterministic stand-in for KRA. Clearly marked as non-fiscal."""

    def submit(self, invoice: EtimsInvoice) -> EtimsReceipt:
        digest = hashlib.sha256(f"{invoice.seller_pin}|{invoice.invoice_no}|{invoice.total}".encode()).hexdigest()[:16].upper()
        reference = f"TEST-{digest}"
        return EtimsReceipt(
            reference=reference,
            qr_data=f"https://etims.kra.go.ke/common/link/etims/receipt/indexEtimsReceiptData?Data=TEST{digest}",
            submitted_at=datetime.now(timezone.utc).replace(tzinfo=None),
            is_test=True,
        )


class LiveGateway:
    def submit(self, invoice: EtimsInvoice) -> EtimsReceipt:
        raise EtimsNotConfigured(
            "live eTIMS isn't connected yet — it needs your KRA eTIMS device credentials. "
            "Invoices are saved normally and can be submitted once it is set up."
        )


def gateway_for(mode: str):
    if mode == "test":
        return TestGateway()
    if mode == "live":
        return LiveGateway()
    return None
