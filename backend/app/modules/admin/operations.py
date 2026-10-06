"""Platform-operator actions on customer accounts: packages, subscriptions and
payments, usage, support access, and creating workspaces on a customer's
behalf. Every action that touches a customer is written to the audit log."""

from __future__ import annotations

from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events, features
from app.core.db import set_tenant_context
from app.core.security import create_access_token
from app.modules.billing.models import AdminAuditLog, Announcement, BillingCycle, SubscriptionStatus
from app.modules.billing.service import BillingService
from app.modules.platform.accounts import AccountService
from app.modules.platform.models import Package, User, Workspace, WorkspaceMember, WorkspaceRole


class AdminOperations:
    def __init__(self, session: AsyncSession, admin: User):
        self.session = session
        self.admin = admin
        self.billing = BillingService(session)

    async def _audit(self, action: str, workspace: Workspace | None = None, **detail) -> None:
        await self.billing.audit(actor_id=self.admin.id, actor_email=self.admin.email, action=action, workspace=workspace, detail=detail)

    async def _workspace(self, workspace_id: str) -> Workspace:
        workspace = (await self.session.execute(select(Workspace).where(Workspace.id == workspace_id))).scalar_one_or_none()
        if workspace is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "workspace not found")
        return workspace

    # -------------------------------------------------------------- packages

    async def list_packages(self) -> list[Package]:
        return list((await self.session.execute(select(Package).order_by(Package.sort_order, Package.price_monthly, Package.name))).scalars())

    @staticmethod
    def _limits(current: dict, data: dict) -> dict:
        limits = dict(current or {})
        for field, unlimited in (("max_users", "unlimited_users"), ("max_sku", "unlimited_sku")):
            if data.pop(unlimited, False):
                limits[field] = None
            elif data.get(field) is not None:
                limits[field] = data[field]
            data.pop(field, None)
        return limits

    async def save_package(self, package_id: str | None, data: dict) -> Package:
        data = {k: v for k, v in data.items() if v is not None or k in ("unlimited_users", "unlimited_sku")}
        if "modules" in data:
            unknown = set(data["modules"]) - set(features.MODULES) - {"*"}
            if unknown:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unknown module(s): {', '.join(sorted(unknown))}")
        if package_id is None:
            if not data.get("key") or not data.get("name"):
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "a new package needs a key and a name")
            if (await self.session.execute(select(Package).where(Package.key == data["key"]))).scalar_one_or_none():
                raise HTTPException(status.HTTP_409_CONFLICT, "a package with that key exists")
            package = Package(key=data.pop("key"), name=data.pop("name"), modules=data.pop("modules", []), limits={})
            self.session.add(package)
        else:
            package = (await self.session.execute(select(Package).where(Package.id == package_id))).scalar_one_or_none()
            if package is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "package not found")
            data.pop("key", None)  # the key is an identifier other code may reference
        package.limits = self._limits(package.limits, data)
        if data.get("is_default"):
            # Exactly one package is offered to new sign-ups.
            for other in await self.list_packages():
                other.is_default = False
        elif data.get("is_default") is False and package.is_default:
            raise HTTPException(status.HTTP_409_CONFLICT, "pick another package as the default instead of unsetting this one")
        if data.get("is_active") is False and package.is_default:
            raise HTTPException(status.HTTP_409_CONFLICT, "the default package can't be deactivated")
        for key, value in data.items():
            setattr(package, key, value)
        await self._audit("package.saved", package=package.key, changes=sorted(data))
        await self.session.commit()
        await self.session.refresh(package)
        return package

    # ------------------------------------------------------------ workspaces

    async def workspace_detail(self, workspace_id: str) -> dict:
        """Subscription, members and usage for the support drawer."""
        workspace = await self._workspace(workspace_id)
        await self.billing.ensure_renewal_invoice(workspace_id)
        subscription = await self.billing.get_subscription(workspace_id)
        access = await self.billing.access(workspace_id)
        members = await AccountService(self.session).list_members(workspace_id)
        invoices = await self.billing.invoices(workspace_id)

        # Usage counts come from tenant tables, which are behind RLS — scope
        # this transaction to the one workspace being inspected.
        from app.modules.hr.models import Employee
        from app.modules.inventory.models import Product
        from app.modules.sales.models import Invoice

        await set_tenant_context(self.session, workspace_id)

        async def count(model) -> int:
            return (await self.session.execute(select(func.count(model.id)).where(model.workspace_id == workspace_id))).scalar_one()

        last_invoice = (
            await self.session.execute(select(func.max(Invoice.created_at)).where(Invoice.workspace_id == workspace_id))
        ).scalar_one()
        usage = {
            "products": await count(Product),
            "invoices": await count(Invoice),
            "employees": await count(Employee),
            "members": len(members),
            "last_invoice_at": last_invoice,
        }
        await self.session.commit()  # also persists a newly raised renewal invoice
        return {
            "id": workspace.id,
            "name": workspace.name,
            "subscription": {
                "status": subscription.status.value if subscription else "none",
                "cycle": subscription.cycle.value if subscription else "monthly",
                "trial_ends_at": subscription.trial_ends_at if subscription else None,
                "current_period_end": subscription.current_period_end if subscription else None,
                "notes": subscription.notes if subscription else "",
            },
            "access": access.__dict__,
            "members": members,
            "usage": usage,
            "invoices": invoices,
        }

    async def update_subscription(self, workspace_id: str, changes: dict) -> None:
        workspace = await self._workspace(workspace_id)
        if "status" in changes:
            changes["status"] = SubscriptionStatus(changes["status"])
        if "cycle" in changes:
            changes["cycle"] = BillingCycle(changes["cycle"])
        await self._audit("subscription.updated", workspace, **{k: str(v) for k, v in changes.items()})
        await self.billing.update_subscription(workspace_id, changes)

    async def record_payment(self, invoice_id: str, method: str, reference: str):
        invoice = await self.billing.record_payment(invoice_id, method=method, reference=reference, recorded_by=self.admin.id)
        await self._audit("payment.recorded", await self._workspace(invoice.workspace_id), invoice=invoice.number, amount=str(invoice.amount), method=method, reference=reference)
        await self.session.commit()
        return invoice

    async def void_invoice(self, invoice_id: str):
        invoice = await self.billing.void_invoice(invoice_id)
        await self._audit("invoice.voided", await self._workspace(invoice.workspace_id), invoice=invoice.number)
        await self.session.commit()
        return invoice

    async def impersonate(self, workspace_id: str) -> dict:
        """A 30-minute session as the workspace's owner, for support. There is
        no refresh token, so it can't be quietly kept alive, and it is always
        recorded."""
        workspace = await self._workspace(workspace_id)
        owner = (
            await self.session.execute(
                select(User)
                .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
                .where(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.role == WorkspaceRole.owner)
                .order_by(WorkspaceMember.created_at)
            )
        ).scalars().first()
        if owner is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "this workspace has no owner yet (invitation not accepted)")
        await self._audit("support.impersonated", workspace, as_user=owner.email)
        await self.session.commit()
        return {
            "access_token": create_access_token(owner.id, owner.token_version, impersonator=self.admin.id),
            "workspace_id": workspace.id,
            "workspace_name": workspace.name,
            "as_user": owner.email,
        }

    async def reset_link(self, workspace_id: str, user_id: str) -> str:
        workspace = await self._workspace(workspace_id)
        member = (
            await self.session.execute(
                select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id)
            )
        ).scalar_one_or_none()
        if member is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "that user isn't in this workspace")
        link = await AccountService(self.session).admin_reset_link(user_id)
        await self._audit("support.reset_link", workspace, user_id=user_id)
        await self.session.commit()
        return link

    async def create_workspace(self, name: str, owner_email: str, package_id: str) -> dict:
        """Sets a business up for a customer and invites them as its owner."""
        package = (await self.session.execute(select(Package).where(Package.id == package_id))).scalar_one_or_none()
        if package is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "package not found")
        workspace = Workspace(name=name.strip(), package_id=package.id)
        self.session.add(workspace)
        await self.session.flush()
        await self.billing.start_for_new_workspace(workspace, package)
        await set_tenant_context(self.session, workspace.id)
        await events.publish(events.WorkspaceCreated(workspace_id=workspace.id), self.session)
        await self._audit("workspace.created", workspace, owner=owner_email, package=package.key)
        invitation = await AccountService(self.session).invite(workspace.id, owner_email, WorkspaceRole.owner, self.admin, "owner")
        return {"workspace_id": workspace.id, "invite_link": invitation["invite_link"], "email_delivered": invitation["email_delivered"]}

    # ------------------------------------------------ announcements / audit

    async def list_announcements(self) -> list[Announcement]:
        return list((await self.session.execute(select(Announcement).order_by(Announcement.created_at.desc()))).scalars())

    async def save_announcement(self, announcement_id: str | None, data: dict) -> Announcement:
        if announcement_id is None:
            announcement = Announcement(**data)
            self.session.add(announcement)
        else:
            announcement = (await self.session.execute(select(Announcement).where(Announcement.id == announcement_id))).scalar_one_or_none()
            if announcement is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "announcement not found")
            for key, value in data.items():
                setattr(announcement, key, value)
        await self._audit("announcement.saved", title=data.get("title", ""))
        await self.session.commit()
        await self.session.refresh(announcement)
        return announcement

    async def audit_log(self, limit: int = 200) -> list[AdminAuditLog]:
        return list((await self.session.execute(select(AdminAuditLog).order_by(AdminAuditLog.created_at.desc()).limit(limit))).scalars())

    async def billing_summary(self) -> dict:
        """Headline numbers for the operator: recurring revenue and what's owed."""
        from app.modules.billing.models import Subscription, SubscriptionInvoice, SubscriptionInvoiceStatus

        rows = (
            await self.session.execute(
                select(Subscription, Package)
                .join(Workspace, Workspace.id == Subscription.workspace_id)
                .join(Package, Package.id == Workspace.package_id)
                .where(Workspace.is_active.is_(True))
            )
        ).all()
        today = date.today()
        grace = (await self.billing.settings()).grace_days
        from app.modules.billing.service import access_for

        mrr = 0
        states: dict[str, int] = {}
        for subscription, package in rows:
            access = access_for(subscription, today, grace)
            states[access.state] = states.get(access.state, 0) + 1
            if subscription.status == SubscriptionStatus.active and access.level != "locked":
                mrr += float(package.price_yearly / 12 if subscription.cycle == BillingCycle.yearly and package.price_yearly else package.price_monthly)
        open_total = (
            await self.session.execute(
                select(func.coalesce(func.sum(SubscriptionInvoice.amount), 0), func.count(SubscriptionInvoice.id)).where(
                    SubscriptionInvoice.status == SubscriptionInvoiceStatus.open
                )
            )
        ).one()
        return {"mrr": round(mrr, 2), "states": states, "open_invoices": open_total[1], "open_amount": open_total[0]}
