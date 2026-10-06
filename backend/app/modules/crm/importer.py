"""Bulk contact import/export (CSV)."""

from __future__ import annotations

from fastapi import UploadFile

from app.core import csvio
from app.modules.crm.models import Party, PartyKind
from app.modules.crm.service import CrmService

COLUMNS = ["name", "kind", "is_company", "email", "phone", "tax_id", "billing_address", "shipping_address"]
TEMPLATE_ROWS = [
    ["Acme Builders Ltd", "customer", "yes", "accounts@acme.co.ke", "+254 722 000 111", "P051234567X", "Moi Avenue, Nairobi", ""],
    ["Bamburi Cement", "vendor", "yes", "sales@bamburi.co.ke", "", "", "Mombasa", ""],
]


async def import_parties(service: CrmService, file: UploadFile) -> dict:
    rows = await csvio.read_rows(file, required=["name"])
    report = csvio.ImportReport()
    # A contact is matched on name (case-insensitive) — re-importing updates
    # details instead of creating duplicates.
    existing = {p.name.lower(): p for p in await service.parties.list()}
    for number, row in rows:
        try:
            name = row.get("name", "")
            if not name:
                raise ValueError("name is required")
            kind_text = (row.get("kind") or "customer").lower()
            if kind_text == "supplier":
                kind_text = "vendor"
            if kind_text not in PartyKind.__members__:
                raise ValueError(f"kind '{row.get('kind')}' must be customer, vendor, lead or both")
            fields = {
                "kind": PartyKind(kind_text),
                "is_company": csvio.bool_of(row.get("is_company", "")),
                "email": row.get("email") or None,
                "phone": row.get("phone") or None,
                "tax_id": row.get("tax_id") or None,
                "billing_address": row.get("billing_address", "")[:500],
                "shipping_address": row.get("shipping_address", "")[:500],
            }
            party = existing.get(name.lower())
            async with service.session.begin_nested():
                if party is not None:
                    for key, value in fields.items():
                        setattr(party, key, value)
                    await service.session.flush()
                    report.updated += 1
                else:
                    party = Party(name=name[:200], **fields)
                    await service.parties.add(party)
                    existing[name.lower()] = party
                    report.created += 1
        except ValueError as exc:
            report.fail(number, str(exc))
        except Exception as exc:
            report.fail(number, getattr(exc, "detail", None) or str(exc))
    await service.session.commit()
    return report.as_dict()


async def export_parties(service: CrmService):
    parties = sorted(await service.parties.list(), key=lambda p: p.name.lower())
    return csvio.csv_response(
        "contacts.csv",
        COLUMNS,
        [
            [p.name, p.kind.value, "yes" if p.is_company else "no", p.email or "", p.phone or "", p.tax_id or "", p.billing_address, p.shipping_address]
            for p in parties
        ],
    )


def template():
    return csvio.csv_response("contacts-template.csv", COLUMNS, TEMPLATE_ROWS)
