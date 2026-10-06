from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.billing.models import (
    AdminAuditLog,
    Announcement,
    BillingCycle,
    PlatformSettings,
    Subscription,
    SubscriptionInvoice,
    SubscriptionInvoiceStatus,
    SubscriptionStatus,
)
from app.modules.platform.models import Package, Workspace

ZERO = Decimal("0")


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def add_period(start: date, cycle: BillingCycle) -> date:
    """One month or one year later, clamped to the month's last day
    (31 Jan + 1 month = 28/29 Feb)."""
    months = 12 if cycle == BillingCycle.yearly else 1
    index = start.month - 1 + months
    year, month = start.year + index // 12, index % 12 + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


@dataclass(frozen=True)
class Access:
    """What a workspace may do right now.

    level: "ok"     — full access
           "grace"  — the paid period has ended; full access, with a warning
           "locked" — trial over or grace run out; modules are blocked until
                      payment, but nothing is deleted
    """

    level: str
    state: str  # trialing | active | past_due | trial_ended | cancelled | complimentary | none
    days_left: int | None  # until the trial / period / grace ends
    message: str


def access_for(subscription: Subscription | None, today: date, grace_days: int) -> Access:
    """Pure function of the subscription and the date — the single rule for
    whether a customer can use the system."""
    if subscription is None or subscription.status == SubscriptionStatus.complimentary:
        return Access("ok", "complimentary" if subscription else "none", None, "")
    if subscription.status == SubscriptionStatus.cancelled:
        return Access("locked", "cancelled", None, "This subscription has been cancelled.")
    if subscription.status == SubscriptionStatus.trialing:
        end = subscription.trial_ends_at
        if end is None or today <= end:
            days = (end - today).days if end else None
            return Access("ok", "trialing", days, f"Free trial — {days} day(s) left." if days is not None else "Free trial.")
        return Access("locked", "trial_ended", 0, "Your free trial has ended. Subscribe to keep using your account.")

    end = subscription.current_period_end
    if end is None or today <= end:
        return Access("ok", "active", (end - today).days if end else None, "")
    overdue = (today - end).days
    if overdue <= grace_days:
        left = grace_days - overdue
        return Access("grace", "past_due", left, f"Your subscription payment is overdue. Access will pause in {left} day(s).")
    return Access("locked", "past_due", 0, "Your subscription payment is overdue. Pay to restore access — your data is safe.")


class BillingService:
    def __init__(self, session: AsyncSession):
        self.session = session

    # -------------------------------------------------------------- settings

    async def settings(self) -> PlatformSettings:
        row = (await self.session.execute(select(PlatformSettings))).scalars().first()
        if row is None:
            row = PlatformSettings()
            self.session.add(row)
            await self.session.flush()
        return row

    async def update_settings(self, changes: dict) -> PlatformSettings:
        row = await self.settings()
        for key, value in changes.items():
            setattr(row, key, value)
        await self.session.commit()
        await self.session.refresh(row)
        return row

    # --------------------------------------------------------- subscriptions

    async def get_subscription(self, workspace_id: str) -> Subscription | None:
        return (
            await self.session.execute(select(Subscription).where(Subscription.workspace_id == workspace_id))
        ).scalar_one_or_none()

    async def start_for_new_workspace(self, workspace: Workspace, package: Package) -> Subscription:
        """Called at sign-up: a free package is simply active; a paid one
        starts its trial."""
        today = date.today()
        if package.price_monthly <= 0 and package.price_yearly <= 0:
            subscription = Subscription(workspace_id=workspace.id, status=SubscriptionStatus.active, current_period_start=today)
        else:
            subscription = Subscription(
                workspace_id=workspace.id,
                status=SubscriptionStatus.trialing,
                trial_ends_at=today + timedelta(days=package.trial_days),
            )
        self.session.add(subscription)
        await self.session.flush()
        return subscription

    async def access(self, workspace_id: str, today: date | None = None) -> Access:
        subscription = await self.get_subscription(workspace_id)
        if subscription is None:
            return access_for(None, today or date.today(), 0)
        return access_for(subscription, today or date.today(), (await self.settings()).grace_days)

    async def _package(self, workspace_id: str) -> Package | None:
        return (
            await self.session.execute(
                select(Package).join(Workspace, Workspace.package_id == Package.id).where(Workspace.id == workspace_id)
            )
        ).scalar_one_or_none()

    @staticmethod
    def price(package: Package, cycle: BillingCycle) -> Decimal:
        if cycle == BillingCycle.yearly:
            return package.price_yearly or package.price_monthly * 12
        return package.price_monthly

    async def _next_number(self) -> str:
        value = (await self.session.execute(text("SELECT nextval('subscription_invoice_seq')"))).scalar_one()
        return f"SUB-{value:06d}"

    async def ensure_renewal_invoice(self, workspace_id: str, today: date | None = None) -> SubscriptionInvoice | None:
        """Raises the next invoice once the trial/period is about to end (or
        has ended). Idempotent: at most one open invoice per workspace."""
        today = today or date.today()
        subscription = await self.get_subscription(workspace_id)
        if subscription is None or subscription.status in (SubscriptionStatus.complimentary, SubscriptionStatus.cancelled):
            return None
        package = await self._package(workspace_id)
        if package is None:
            return None
        amount = self.price(package, subscription.cycle)
        if amount <= 0:
            return None

        open_invoice = (
            await self.session.execute(
                select(SubscriptionInvoice).where(
                    SubscriptionInvoice.workspace_id == workspace_id,
                    SubscriptionInvoice.status == SubscriptionInvoiceStatus.open,
                )
            )
        ).scalars().first()
        if open_invoice is not None:
            return open_invoice

        boundary = subscription.trial_ends_at if subscription.status == SubscriptionStatus.trialing else subscription.current_period_end
        if boundary is None:
            return None  # open-ended plan: nothing to renew
        lead = (await self.settings()).invoice_lead_days
        if today < boundary - timedelta(days=lead):
            return None

        start = boundary + timedelta(days=1) if subscription.status == SubscriptionStatus.active else boundary
        invoice = SubscriptionInvoice(
            number=await self._next_number(),
            workspace_id=workspace_id,
            package_name=package.name,
            cycle=subscription.cycle,
            period_start=start,
            period_end=add_period(start, subscription.cycle) - timedelta(days=1),
            amount=amount,
            currency=(await self.settings()).currency,
            due_date=boundary,
        )
        self.session.add(invoice)
        await self.session.flush()
        return invoice

    async def invoices(self, workspace_id: str | None = None, status_filter: str | None = None) -> list[SubscriptionInvoice]:
        stmt = select(SubscriptionInvoice).order_by(SubscriptionInvoice.created_at.desc())
        if workspace_id:
            stmt = stmt.where(SubscriptionInvoice.workspace_id == workspace_id)
        if status_filter:
            stmt = stmt.where(SubscriptionInvoice.status == SubscriptionInvoiceStatus(status_filter))
        return list((await self.session.execute(stmt.limit(500))).scalars())

    async def record_payment(self, invoice_id: str, *, method: str, reference: str, recorded_by: str, today: date | None = None) -> SubscriptionInvoice:
        today = today or date.today()
        invoice = (
            await self.session.execute(select(SubscriptionInvoice).where(SubscriptionInvoice.id == invoice_id).with_for_update())
        ).scalar_one_or_none()
        if invoice is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "invoice not found")
        if invoice.status != SubscriptionInvoiceStatus.open:
            raise HTTPException(status.HTTP_409_CONFLICT, f"invoice is already {invoice.status.value}")
        subscription = await self.get_subscription(invoice.workspace_id)
        if subscription is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "workspace has no subscription")

        # Paying after the account locked shouldn't charge for the days it was
        # locked: the paid period starts today instead.
        grace = (await self.settings()).grace_days
        if today > invoice.period_start + timedelta(days=grace):
            invoice.period_start = today
            invoice.period_end = add_period(today, invoice.cycle) - timedelta(days=1)

        invoice.status = SubscriptionInvoiceStatus.paid
        invoice.paid_at = utcnow()
        invoice.payment_method = method
        invoice.payment_reference = reference
        invoice.recorded_by = recorded_by
        subscription.status = SubscriptionStatus.active
        subscription.current_period_start = invoice.period_start
        subscription.current_period_end = invoice.period_end
        await self.session.commit()
        await self.session.refresh(invoice)
        return invoice

    async def void_invoice(self, invoice_id: str) -> SubscriptionInvoice:
        invoice = (await self.session.execute(select(SubscriptionInvoice).where(SubscriptionInvoice.id == invoice_id))).scalar_one_or_none()
        if invoice is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "invoice not found")
        if invoice.status != SubscriptionInvoiceStatus.open:
            raise HTTPException(status.HTTP_409_CONFLICT, "only an open invoice can be voided")
        invoice.status = SubscriptionInvoiceStatus.void
        await self.session.commit()
        await self.session.refresh(invoice)
        return invoice

    async def update_subscription(self, workspace_id: str, changes: dict) -> Subscription:
        subscription = await self.get_subscription(workspace_id)
        if subscription is None:
            subscription = Subscription(workspace_id=workspace_id, status=SubscriptionStatus.active)
            self.session.add(subscription)
        for key, value in changes.items():
            setattr(subscription, key, value)
        await self.session.commit()
        await self.session.refresh(subscription)
        return subscription

    async def overview(self, workspace_id: str) -> dict:
        """What a workspace owner sees on their Billing page."""
        await self.ensure_renewal_invoice(workspace_id)
        await self.session.commit()
        subscription = await self.get_subscription(workspace_id)
        package = await self._package(workspace_id)
        access = await self.access(workspace_id)
        settings = await self.settings()
        return {
            "access": access.__dict__,
            "package": {
                "name": package.name if package else "",
                "description": package.description if package else "",
                "price_monthly": package.price_monthly if package else ZERO,
                "price_yearly": package.price_yearly if package else ZERO,
                "limits": package.limits if package else {},
            },
            "subscription": {
                "status": subscription.status.value if subscription else "none",
                "cycle": subscription.cycle.value if subscription else "monthly",
                "trial_ends_at": subscription.trial_ends_at if subscription else None,
                "current_period_end": subscription.current_period_end if subscription else None,
            },
            "invoices": await self.invoices(workspace_id),
            "pay_to": {
                "product_name": settings.product_name, "mpesa_paybill": settings.mpesa_paybill, "mpesa_till": settings.mpesa_till,
                "bank_details": settings.bank_details, "support_email": settings.support_email, "support_phone": settings.support_phone,
                "currency": settings.currency,
            },
        }

    # ------------------------------------------------------- audit + notices

    async def audit(self, *, actor_id: str, actor_email: str, action: str, workspace: Workspace | None = None, detail: dict | None = None) -> None:
        self.session.add(
            AdminAuditLog(
                actor_user_id=actor_id, actor_email=actor_email, action=action,
                workspace_id=workspace.id if workspace else None, workspace_name=workspace.name if workspace else "",
                detail=detail or {},
            )
        )
        await self.session.flush()

    async def active_announcements(self) -> list[Announcement]:
        now = utcnow()
        rows = (await self.session.execute(select(Announcement).where(Announcement.is_active.is_(True)).order_by(Announcement.created_at.desc()))).scalars()
        return [a for a in rows if (a.starts_at is None or a.starts_at <= now) and (a.ends_at is None or a.ends_at >= now)]
