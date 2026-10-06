"""Platform-side commerce: what each customer workspace pays, and the
operator's own records (audit log, announcements, settings).

None of these are tenant tables: they belong to the platform operator and are
read across workspaces, so they are not behind Row-Level Security.
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class SubscriptionStatus(str, enum.Enum):
    trialing = "trialing"
    active = "active"
    complimentary = "complimentary"  # never billed, never expires (your own/partner accounts)
    cancelled = "cancelled"


class BillingCycle(str, enum.Enum):
    monthly = "monthly"
    yearly = "yearly"


class Subscription(Base):
    """One per workspace. "Past due" and "locked" are not stored — they follow
    from the dates (see billing.service.access_for), so there is no nightly job
    whose failure could leave an account in the wrong state."""

    __tablename__ = "subscriptions"

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), unique=True, index=True)
    status: Mapped[SubscriptionStatus] = mapped_column(default=SubscriptionStatus.trialing)
    cycle: Mapped[BillingCycle] = mapped_column(default=BillingCycle.monthly)
    trial_ends_at: Mapped[date | None] = mapped_column(nullable=True)
    current_period_start: Mapped[date | None] = mapped_column(nullable=True)
    current_period_end: Mapped[date | None] = mapped_column(nullable=True)  # None on an active plan = open-ended
    notes: Mapped[str] = mapped_column(String(500), default="")


class SubscriptionInvoiceStatus(str, enum.Enum):
    open = "open"
    paid = "paid"
    void = "void"


class SubscriptionInvoice(Base):
    __tablename__ = "subscription_invoices"

    number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    package_name: Mapped[str] = mapped_column(String(100))
    cycle: Mapped[BillingCycle]
    period_start: Mapped[date]
    period_end: Mapped[date]
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="KES")
    status: Mapped[SubscriptionInvoiceStatus] = mapped_column(default=SubscriptionInvoiceStatus.open)
    due_date: Mapped[date]
    paid_at: Mapped[datetime | None] = mapped_column(nullable=True)
    payment_method: Mapped[str] = mapped_column(String(32), default="")
    payment_reference: Mapped[str] = mapped_column(String(64), default="")
    recorded_by: Mapped[str | None] = mapped_column(String(36), nullable=True)


class PlatformSettings(Base):
    """Singleton: who the operator is and how customers pay them."""

    __tablename__ = "platform_settings"

    product_name: Mapped[str] = mapped_column(String(100), default="Business Suite")
    support_email: Mapped[str] = mapped_column(String(255), default="")
    support_phone: Mapped[str] = mapped_column(String(32), default="")
    currency: Mapped[str] = mapped_column(String(3), default="KES")
    mpesa_paybill: Mapped[str] = mapped_column(String(20), default="")
    mpesa_till: Mapped[str] = mapped_column(String(20), default="")
    bank_details: Mapped[str] = mapped_column(String(1000), default="")
    grace_days: Mapped[int] = mapped_column(default=7)  # after a period ends, before the account locks
    invoice_lead_days: Mapped[int] = mapped_column(default=7)  # how early the renewal invoice appears


class AdminAuditLog(Base):
    """Everything a platform admin does to a customer's account — especially
    signing in as them — is written here and never edited."""

    __tablename__ = "admin_audit_log"

    actor_user_id: Mapped[str] = mapped_column(String(36), index=True)
    actor_email: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    workspace_name: Mapped[str] = mapped_column(String(200), default="")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class Announcement(Base):
    """A banner shown to every signed-in user (maintenance windows, new features)."""

    __tablename__ = "announcements"

    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    level: Mapped[str] = mapped_column(String(16), default="info")  # info | warning
    starts_at: Mapped[datetime | None] = mapped_column(nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
