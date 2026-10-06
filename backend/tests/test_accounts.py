"""Team invitations, password recovery, package limits, role enforcement,
bulk import and emailing documents."""

import email
import io
import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import select

from app.core import mailer
from app.core.security import hash_password, verify_password
from app.modules.accounting.service import AccountingService
from app.modules.crm import importer as crm_importer
from app.modules.crm.models import PartyKind
from app.modules.crm.schemas import PartyCreate
from app.modules.crm.service import CrmService
from app.modules.inventory import importer as product_importer
from app.modules.inventory.schemas import WarehouseCreate
from app.modules.inventory.service import InventoryService
from app.modules.platform.accounts import AccountService, utcnow
from app.modules.platform.models import AuthToken, Package, User, Workspace, WorkspaceMember, WorkspaceRole
from app.modules.sales.schemas import DocumentLineInput, InvoiceCreate
from app.modules.sales.service import SalesService


@pytest.fixture
def outbox(tmp_path, monkeypatch):
    monkeypatch.setattr(mailer.settings, "media_root", str(tmp_path))
    monkeypatch.setattr(mailer.settings, "smtp_host", "")
    return tmp_path / "outbox"


def _latest_mail(outbox: Path) -> email.message.Message:
    newest = sorted(outbox.glob("*.eml"))[-1]
    return email.message_from_bytes(newest.read_bytes())


def _token_from(message: email.message.Message) -> str:
    body = message.get_body(preferencelist=("plain",)).get_content() if hasattr(message, "get_body") else ""
    if not body:
        for part in message.walk():
            if part.get_content_type() == "text/plain":
                body = part.get_payload(decode=True).decode()
    return body.split("token=")[1].split()[0]


async def _owner(session, workspace_id) -> User:
    user = User(email=f"owner-{uuid.uuid4().hex[:8]}@example.com", hashed_password=hash_password("Owner1234!"), full_name="Olivia Owner")
    session.add(user)
    await session.flush()
    session.add(WorkspaceMember(workspace_id=workspace_id, user_id=user.id, role=WorkspaceRole.owner))
    await session.commit()
    return user


async def test_invite_new_person_and_accept(session, workspace_id, outbox):
    owner = await _owner(session, workspace_id)
    accounts = AccountService(session)
    address = f"new-{uuid.uuid4().hex[:8]}@example.com"

    result = await accounts.invite(workspace_id, address.upper(), WorkspaceRole.staff, owner, "owner")
    assert result["email"] == address and not result["email_delivered"]  # outbox, not SMTP
    token = result["invite_link"].split("token=")[1]
    assert _token_from(_latest_mail(outbox)) == token

    info = await accounts.invitation_info(token)
    assert info["has_account"] is False and info["role"] == "staff"

    with pytest.raises(HTTPException):  # weak password
        await accounts.accept_invitation(token, "Nina New", "short")
    await session.rollback()

    tokens = await accounts.accept_invitation(token, "Nina New", "Welcome123!")
    assert tokens.access_token
    members = {m["email"]: m for m in await accounts.list_members(workspace_id)}
    assert members[address]["role"] == WorkspaceRole.staff and members[address]["full_name"] == "Nina New"

    with pytest.raises(HTTPException):  # single use
        await accounts.accept_invitation(token, "Nina New", "Welcome123!")


async def test_user_limit_and_owner_protection(session, workspace_id, outbox):
    owner = await _owner(session, workspace_id)
    accounts = AccountService(session)
    workspace = (await session.execute(select(Workspace).where(Workspace.id == workspace_id))).scalar_one()
    package = (await session.execute(select(Package).where(Package.id == workspace.package_id))).scalar_one()
    package.limits = {"max_users": 2}
    await session.commit()

    await accounts.invite(workspace_id, "a@example.com", WorkspaceRole.viewer, owner, "owner")
    with pytest.raises(HTTPException) as exc:  # owner + 1 pending invite = 2 seats
        await accounts.invite(workspace_id, "b@example.com", WorkspaceRole.viewer, owner, "owner")
    assert exc.value.status_code == 402

    with pytest.raises(HTTPException):  # admins can't mint owners
        await accounts.invite(workspace_id, "c@example.com", WorkspaceRole.owner, owner, "admin")

    me = next(m for m in await accounts.list_members(workspace_id) if m["email"] == owner.email)
    with pytest.raises(HTTPException):  # last owner can't be demoted…
        await accounts.change_role(workspace_id, me["id"], WorkspaceRole.staff, "owner")
    with pytest.raises(HTTPException):  # …or removed
        await accounts.remove_member(workspace_id, me["id"], "owner")


async def test_password_reset_is_single_use_and_expires(session, workspace_id, outbox):
    owner = await _owner(session, workspace_id)
    accounts = AccountService(session)
    address = owner.email  # plain str: ORM attributes expire on rollback

    await accounts.forgot_password("nobody@example.com")  # unknown address: silent
    assert not outbox.exists() or not list(outbox.glob("*.eml"))

    await accounts.forgot_password(address)
    token = _token_from(_latest_mail(outbox))
    await accounts.reset_password(token, "Brandnew123!")
    await session.refresh(owner)
    assert verify_password("Brandnew123!", owner.hashed_password)
    with pytest.raises(HTTPException):
        await accounts.reset_password(token, "Another123!")
    await session.rollback()

    await accounts.forgot_password(address)
    stored = (await session.execute(select(AuthToken).where(AuthToken.email == address, AuthToken.used_at.is_(None)))).scalar_one()
    stored.expires_at = utcnow() - timedelta(minutes=1)
    await session.commit()
    with pytest.raises(HTTPException):
        await accounts.reset_password(_token_from(_latest_mail(outbox)), "Another123!")


def _csv(text: str) -> UploadFile:
    return UploadFile(filename="data.csv", file=io.BytesIO(text.encode("utf-8-sig")))


async def test_product_import_reports_bad_rows_and_never_double_counts(session, workspace_id):
    await AccountingService(session, workspace_id).seed_default_accounts()
    inventory = InventoryService(session, workspace_id)
    await inventory.create_warehouse(WarehouseCreate(name="Main", code="MAIN"))
    text = (
        "SKU,Name,Category,Sale Price,Tax Rate,Opening Qty,Opening Cost,Warehouse Code\n"
        "CEM-50,Cement 50kg,Building,850,16,100,620,MAIN\n"
        "NAIL-4,Nails 4in,Hardware,\"1,280\",16%,,,\n"
        "BAD-1,Broken price,Hardware,abc,16,,,\n"
        ",No sku,,10,,,,\n"
        "CEM-50,Duplicate,Building,1,,,,\n"
    )
    report = await product_importer.import_products(inventory, _csv(text))
    assert (report["created"], report["updated"], report["skipped"]) == (2, 0, 3)
    assert [e["row"] for e in report["errors"]] == [4, 5, 6]

    products = {p.sku: p for p in await inventory.products.list()}
    assert products["CEM-50"].stock_qty == Decimal("100") and products["CEM-50"].tax_rate == Decimal("0.16")
    assert products["NAIL-4"].sale_price == Decimal("1280")
    assert await AccountingService(session, workspace_id).balance_for_key("INVENTORY") == Decimal("62000")

    # Importing the same file again updates details but adds no stock.
    again = await product_importer.import_products(inventory, _csv(text))
    assert (again["created"], again["updated"]) == (0, 2)
    await session.refresh(products["CEM-50"])
    assert products["CEM-50"].stock_qty == Decimal("100")


async def test_contact_import(session, workspace_id):
    crm = CrmService(session, workspace_id)
    report = await crm_importer.import_parties(
        crm, _csv("name;kind;email\nAcme Ltd;customer;a@acme.co.ke\nBamburi;supplier;\nWho;alien;\n")
    )
    assert (report["created"], report["skipped"]) == (2, 1)
    kinds = {p.name: p.kind for p in await crm.parties.list()}
    assert kinds == {"Acme Ltd": PartyKind.customer, "Bamburi": PartyKind.vendor}


async def test_emailing_an_invoice_attaches_the_pdf(session, workspace_id, outbox):
    await AccountingService(session, workspace_id).seed_default_accounts()
    owner = await _owner(session, workspace_id)
    customer = await CrmService(session, workspace_id).create_party(
        PartyCreate(name="Acme <b>Ltd</b>", kind=PartyKind.customer, email="accounts@acme.co.ke")
    )
    sales = SalesService(session, workspace_id)
    invoice = await sales.create_invoice(
        InvoiceCreate(party_id=customer.id, lines=[DocumentLineInput(description="Consulting", qty=Decimal("1"), unit_price=Decimal("5000"))])
    )
    result = await sales.email_document(kind="invoice", document_id=invoice.id, to=None, cc=[], message="Thanks!", sent_by=owner.id)
    assert result == {"to": "accounts@acme.co.ke", "delivered": False, "backend": "outbox"}

    message = _latest_mail(outbox)
    assert invoice.invoice_no in message["Subject"]
    attachments = [p for p in message.walk() if p.get_content_disposition() == "attachment"]
    assert attachments[0].get_filename() == f"{invoice.invoice_no}.pdf"
    assert attachments[0].get_payload(decode=True)[:4] == b"%PDF"
    html = next(p for p in message.walk() if p.get_content_type() == "text/html").get_payload(decode=True).decode()
    assert "&lt;b&gt;" in html and "<b>Ltd</b>" not in html  # customer name is escaped

    no_email = await CrmService(session, workspace_id).create_party(PartyCreate(name="No Mail", kind=PartyKind.customer))
    other = await sales.create_invoice(
        InvoiceCreate(party_id=no_email.id, lines=[DocumentLineInput(description="X", qty=Decimal("1"), unit_price=Decimal("1"))])
    )
    with pytest.raises(HTTPException):
        await sales.email_document(kind="invoice", document_id=other.id, to=None, cc=[], message="", sent_by=owner.id)


async def test_viewer_can_read_but_not_write_over_http(outbox):
    """Through the real app: roles are enforced at the router, per module."""
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test/api/v1") as client:
        owner_email = f"boss-{uuid.uuid4().hex[:8]}@example.com"
        tokens = (await client.post("/auth/signup", json={"email": owner_email, "password": "Owner1234!", "full_name": "Boss", "workspace_name": "RBAC Co"})).json()
        owner = {"Authorization": f"Bearer {tokens['access_token']}"}
        workspace = (await client.get("/workspaces", headers=owner)).json()[0]["id"]
        owner["X-Workspace-Id"] = workspace

        customer = (await client.post("/crm/parties", headers=owner, json={"name": "Cust", "kind": "customer"})).json()
        invite = (await client.post("/workspaces/members", headers=owner, json={"email": f"viewer-{uuid.uuid4().hex[:8]}@example.com", "role": "viewer"})).json()
        accepted = (await client.post("/auth/accept-invite", json={"token": invite["invite_link"].split("token=")[1], "full_name": "Vera Viewer", "password": "Viewer123!"})).json()
        viewer = {"Authorization": f"Bearer {accepted['access_token']}", "X-Workspace-Id": workspace}

        assert (await client.get("/sales/invoices", headers=viewer)).status_code == 200
        body = {"party_id": customer["id"], "lines": [{"description": "x", "qty": "1", "unit_price": "10"}]}
        assert (await client.post("/sales/invoices", headers=viewer, json=body)).status_code == 403
        assert (await client.post("/sales/invoices", headers=owner, json=body)).status_code == 200
        assert (await client.post("/crm/parties", headers=viewer, json={"name": "Nope"})).status_code == 403
        # Team management is owner/admin only.
        assert (await client.post("/workspaces/members", headers=viewer, json={"email": "x@example.com", "role": "staff"})).status_code == 403
        assert (await client.get("/workspaces/members", headers=viewer)).status_code == 200
