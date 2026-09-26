from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import TenantModel


class PartyKind(str, enum.Enum):
    lead = "lead"
    customer = "customer"
    vendor = "vendor"
    both = "both"


class Party(TenantModel):
    """Unified contact record instead of separate Customer/Lead/Vendor tables — an
    SME's contact often plays multiple roles over its lifetime (a lead becomes a
    customer; a small vendor is sometimes also a customer). Role-specific data
    lives in the thin CustomerProfile/VendorProfile extensions below, keyed by
    party_id, so this table stays lean."""

    __tablename__ = "parties"

    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[PartyKind] = mapped_column(default=PartyKind.lead)
    is_company: Mapped[bool] = mapped_column(default=False)
    parent_party_id: Mapped[str | None] = mapped_column(
        ForeignKey("parties.id"), nullable=True
    )  # individual contact's employer, if any
    tax_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    billing_address: Mapped[str] = mapped_column(String(500), default="")
    shipping_address: Mapped[str] = mapped_column(String(500), default="")


class CustomerProfile(TenantModel):
    __tablename__ = "customer_profiles"

    party_id: Mapped[str] = mapped_column(ForeignKey("parties.id"), unique=True)
    credit_limit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    payment_terms_days: Mapped[int] = mapped_column(default=0)


class VendorProfile(TenantModel):
    __tablename__ = "vendor_profiles"

    party_id: Mapped[str] = mapped_column(ForeignKey("parties.id"), unique=True)
    payment_terms_days: Mapped[int] = mapped_column(default=0)


class DealStage(str, enum.Enum):
    new = "new"
    qualified = "qualified"
    proposal = "proposal"
    won = "won"
    lost = "lost"


class Deal(TenantModel):
    __tablename__ = "deals"

    party_id: Mapped[str] = mapped_column(ForeignKey("parties.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    stage: Mapped[DealStage] = mapped_column(default=DealStage.new)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    expected_close_date: Mapped[date | None] = mapped_column(nullable=True)
    owner_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class InteractionType(str, enum.Enum):
    call = "call"
    email = "email"
    meeting = "meeting"
    note = "note"


class Interaction(TenantModel):
    """Direct port of Tolkyn's CustomerInteraction — timeline + needs-follow-up."""

    __tablename__ = "interactions"

    party_id: Mapped[str] = mapped_column(ForeignKey("parties.id"), index=True)
    type: Mapped[InteractionType] = mapped_column(default=InteractionType.note)
    summary: Mapped[str] = mapped_column(String(2000), default="")
    occurred_at: Mapped[datetime]
    follow_up_at: Mapped[datetime | None] = mapped_column(nullable=True)
    is_follow_up_done: Mapped[bool] = mapped_column(default=False)


class Task(TenantModel):
    __tablename__ = "tasks"

    party_id: Mapped[str | None] = mapped_column(ForeignKey("parties.id"), nullable=True)
    deal_id: Mapped[str | None] = mapped_column(ForeignKey("deals.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    due_date: Mapped[date | None] = mapped_column(nullable=True)
    assigned_to_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    done: Mapped[bool] = mapped_column(default=False)
