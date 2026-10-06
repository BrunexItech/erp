"""Subscriptions, account locking, two-factor sign-in, session invalidation
and the platform admin's support tools."""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core import totp
from app.core.security import hash_password
from app.modules.admin.operations import AdminOperations
from app.modules.billing.models import BillingCycle, Subscription, SubscriptionInvoiceStatus, SubscriptionStatus
from app.modules.billing.service import BillingService, access_for, add_period
from app.modules.platform.models import Package, User, Workspace, WorkspaceMember, WorkspaceRole

TODAY = date(2026, 3, 15)


def _sub(**fields) -> Subscription:
    return Subscription(workspace_id="w", **fields)


def test_add_period_clamps_to_month_end():
    assert add_period(date(2026, 1, 31), BillingCycle.monthly) == date(2026, 2, 28)
    assert add_period(date(2024, 2, 29), BillingCycle.yearly) == date(2025, 2, 28)
    assert add_period(date(2026, 12, 10), BillingCycle.monthly) == date(2027, 1, 10)


def test_access_rules():
    assert access_for(None, TODAY, 7).level == "ok"
    assert access_for(_sub(status=SubscriptionStatus.complimentary), TODAY, 7).level == "ok"

    trial = _sub(status=SubscriptionStatus.trialing, trial_ends_at=TODAY + timedelta(days=3))
    assert (access_for(trial, TODAY, 7).level, access_for(trial, TODAY, 7).days_left) == ("ok", 3)
    assert access_for(trial, TODAY + timedelta(days=3), 7).level == "ok"  # last day still works
    ended = access_for(trial, TODAY + timedelta(days=4), 7)
    assert (ended.level, ended.state) == ("locked", "trial_ended")

    paid = _sub(status=SubscriptionStatus.active, current_period_end=TODAY)
    assert access_for(paid, TODAY, 7).level == "ok"
    grace = access_for(paid, TODAY + timedelta(days=5), 7)
    assert (grace.level, grace.days_left) == ("grace", 2)
    assert access_for(paid, TODAY + timedelta(days=7), 7).level == "grace"
    assert access_for(paid, TODAY + timedelta(days=8), 7).level == "locked"

    assert access_for(_sub(status=SubscriptionStatus.active), TODAY, 7).level == "ok"  # open-ended
    assert access_for(_sub(status=SubscriptionStatus.cancelled), TODAY, 7).level == "locked"


async def _paid_workspace(session, price="2500") -> tuple[Workspace, Package]:
    package = Package(key=f"paid-{uuid.uuid4().hex[:8]}", name="Paid Plan", modules=["*"], limits={}, price_monthly=Decimal(price), trial_days=14)
    session.add(package)
    await session.flush()
    workspace = Workspace(name="Billing Co", package_id=package.id)
    session.add(workspace)
    await session.flush()
    return workspace, package


async def test_trial_then_invoice_then_payment(session):
    workspace, package = await _paid_workspace(session)
    billing = BillingService(session)
    start = date.today()
    subscription = await billing.start_for_new_workspace(workspace, package)
    assert subscription.status == SubscriptionStatus.trialing
    assert subscription.trial_ends_at == start + timedelta(days=14)

    # Too early for an invoice; it appears a week before the trial ends.
    assert await billing.ensure_renewal_invoice(workspace.id, today=start) is None
    invoice = await billing.ensure_renewal_invoice(workspace.id, today=start + timedelta(days=8))
    assert invoice.number.startswith("SUB-") and invoice.amount == Decimal("2500")
    assert invoice.period_start == subscription.trial_ends_at
    again = await billing.ensure_renewal_invoice(workspace.id, today=start + timedelta(days=9))
    assert again.id == invoice.id  # never two open invoices

    assert (await billing.access(workspace.id, today=start + timedelta(days=15))).level == "locked"

    paid = await billing.record_payment(invoice.id, method="mpesa", reference="SJK1", recorded_by="admin", today=start + timedelta(days=10))
    assert paid.status == SubscriptionInvoiceStatus.paid
    await session.refresh(subscription)
    assert subscription.status == SubscriptionStatus.active
    assert subscription.current_period_end == add_period(subscription.trial_ends_at, BillingCycle.monthly) - timedelta(days=1)
    assert (await billing.access(workspace.id, today=start + timedelta(days=15))).level == "ok"

    with pytest.raises(HTTPException):  # can't pay twice
        await billing.record_payment(invoice.id, method="mpesa", reference="SJK2", recorded_by="admin")


async def test_paying_after_lock_starts_the_period_from_today(session):
    workspace, package = await _paid_workspace(session)
    billing = BillingService(session)
    subscription = await billing.start_for_new_workspace(workspace, package)
    late = subscription.trial_ends_at + timedelta(days=40)
    invoice = await billing.ensure_renewal_invoice(workspace.id, today=late)
    await billing.record_payment(invoice.id, method="bank", reference="", recorded_by="admin", today=late)
    await session.refresh(subscription)
    assert subscription.current_period_start == late  # not charged for the locked weeks


async def test_free_package_never_bills(session):
    workspace, package = await _paid_workspace(session, price="0")
    billing = BillingService(session)
    subscription = await billing.start_for_new_workspace(workspace, package)
    assert subscription.status == SubscriptionStatus.active
    assert await billing.ensure_renewal_invoice(workspace.id, today=date.today() + timedelta(days=400)) is None
    assert (await billing.access(workspace.id, today=date.today() + timedelta(days=400))).level == "ok"


def test_totp_matches_rfc_6238_vector():
    # RFC 6238 Appendix B, SHA-1, secret "12345678901234567890", T = 59s -> 94287082 (8 digits) -> last 6
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    assert totp.code_at(secret, at=59) == "287082"
    assert totp.verify(secret, "287082", at=59)
    assert totp.verify(secret, "287 082", at=59 + 30)  # one step of clock drift, spaces ignored
    assert not totp.verify(secret, "287082", at=59 + 120)
    assert not totp.verify(secret, "abcdef", at=59)
    assert "<svg" in totp.qr_svg(totp.provisioning_uri(secret, "a@b.co", "Suite"))


async def test_locked_account_two_factor_and_session_invalidation_over_http(session):
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test/api/v1") as client:
        email = f"pay-{uuid.uuid4().hex[:8]}@example.com"
        tokens = (await client.post("/auth/signup", json={"email": email, "password": "Owner1234!", "workspace_name": "Lock Co"})).json()
        auth = {"Authorization": f"Bearer {tokens['access_token']}"}
        workspace_id = (await client.get("/workspaces", headers=auth)).json()[0]["id"]
        auth["X-Workspace-Id"] = workspace_id

        me = (await client.get("/auth/me", headers=auth)).json()
        assert me["billing"]["level"] == "ok"  # new sign-ups start on a trial
        assert (await client.get("/crm/parties", headers=auth)).status_code == 200

        # Trial runs out.
        subscription = (await session.execute(select(Subscription).where(Subscription.workspace_id == workspace_id))).scalar_one()
        subscription.trial_ends_at = date.today() - timedelta(days=1)
        await session.commit()

        assert (await client.get("/crm/parties", headers=auth)).status_code == 402
        assert (await client.post("/sales/invoices", headers=auth, json={})).status_code == 402
        # ...but they can still sign in, see why, and find out how to pay.
        assert (await client.get("/auth/me", headers=auth)).json()["billing"]["level"] == "locked"
        billing = (await client.get("/workspaces/billing", headers=auth)).json()
        assert billing["access"]["state"] == "trial_ended" and billing["invoices"][0]["status"] == "open"

        # Platform admin records the payment -> access is back at once.
        admin = User(email=f"admin-{uuid.uuid4().hex[:8]}@example.com", hashed_password=hash_password("Admin1234!"), is_platform_admin=True)
        session.add(admin)
        await session.commit()
        admin_auth = {"Authorization": f"Bearer {(await client.post('/auth/login', json={'email': admin.email, 'password': 'Admin1234!'})).json()['access_token']}"}
        paid = await client.post(f"/admin/billing/invoices/{billing['invoices'][0]['id']}/pay", headers=admin_auth, json={"method": "mpesa", "reference": "QWE123"})
        assert paid.status_code == 200
        assert (await client.get("/crm/parties", headers=auth)).status_code == 200
        assert (await client.post("/admin/billing/invoices/x/pay", headers=auth, json={})).status_code == 403  # customers can't

        # Support: sign in as the customer (audited), and it really is their workspace.
        imp = (await client.post(f"/admin/workspaces/{workspace_id}/impersonate", headers=admin_auth)).json()
        as_owner = {"Authorization": f"Bearer {imp['access_token']}", "X-Workspace-Id": workspace_id}
        assert (await client.get("/auth/user", headers=as_owner)).json()["email"] == email
        actions = [e["action"] for e in (await client.get("/admin/audit-log", headers=admin_auth)).json()]
        assert "support.impersonated" in actions and "payment.recorded" in actions

        # Two-factor: enable, then the password alone is no longer enough.
        setup = (await client.post("/auth/2fa/setup", headers=auth)).json()
        assert (await client.post("/auth/2fa/enable", headers=auth, json={"code": "000000"})).status_code == 400
        codes = (await client.post("/auth/2fa/enable", headers=auth, json={"code": totp.code_at(setup["secret"])})).json()["recovery_codes"]
        assert len(codes) == 8
        login = {"email": email, "password": "Owner1234!"}
        assert (await client.post("/auth/login", json=login)).json()["detail"] == "totp_required"
        assert (await client.post("/auth/login", json={**login, "totp_code": "123456"})).status_code == 401
        assert (await client.post("/auth/login", json={**login, "totp_code": totp.code_at(setup["secret"])})).status_code == 200
        assert (await client.post("/auth/login", json={**login, "totp_code": codes[0]})).status_code == 200  # recovery code
        assert (await client.post("/auth/login", json={**login, "totp_code": codes[0]})).status_code == 401  # ...once only

        # Changing the password kills every other session.
        changed = await client.post("/auth/change-password", headers=auth, json={"current_password": "Owner1234!", "new_password": "Fresh5678!"})
        assert changed.status_code == 200
        assert (await client.get("/auth/user", headers=auth)).status_code == 401  # old token
        assert (await client.get("/auth/user", headers=as_owner)).status_code == 401  # the impersonation too
        fresh = {"Authorization": f"Bearer {changed.json()['access_token']}"}
        assert (await client.get("/auth/user", headers=fresh)).status_code == 200


async def test_admin_packages_and_workspace_creation(session, tmp_path, monkeypatch):
    from app.core import mailer

    monkeypatch.setattr(mailer.settings, "media_root", str(tmp_path))
    admin = User(email=f"ops-{uuid.uuid4().hex[:8]}@example.com", hashed_password=hash_password("Admin1234!"), is_platform_admin=True)
    session.add(admin)
    await session.commit()
    ops = AdminOperations(session, admin)

    key = f"pro-{uuid.uuid4().hex[:6]}"
    package = await ops.save_package(None, {"key": key, "name": "Pro", "modules": ["crm", "sales"], "max_users": 10, "price_monthly": Decimal("4000"), "unlimited_sku": True})
    assert package.limits == {"max_users": 10, "max_sku": None}
    package_id_early = package.id
    with pytest.raises(HTTPException):
        await ops.save_package(None, {"key": key, "name": "Dup"})
    await session.rollback()
    await session.refresh(admin)
    package_id = package_id_early
    with pytest.raises(HTTPException):
        await ops.save_package(package_id, {"modules": ["teleport"]})
    await session.rollback()
    await session.refresh(admin)  # rollbacks expire loaded objects

    owner_email = f"client-{uuid.uuid4().hex[:8]}@example.com"
    created = await ops.create_workspace("Client Shop Ltd", owner_email, package_id)
    assert "accept-invite?token=" in created["invite_link"]
    subscription = await BillingService(session).get_subscription(created["workspace_id"])
    assert subscription.status == SubscriptionStatus.trialing
    members = (await session.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id == created["workspace_id"]))).scalars().all()
    assert members == []  # the owner joins by accepting the invitation

    with pytest.raises(HTTPException):  # nobody to sign in as yet
        await ops.impersonate(created["workspace_id"])
    assert WorkspaceRole.owner.value == "owner"
