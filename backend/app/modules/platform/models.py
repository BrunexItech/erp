from __future__ import annotations

import enum

from datetime import datetime

from decimal import Decimal

from sqlalchemy import JSON, Boolean, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantModel


class Package(Base):
    """Global, not tenant-scoped — a Package is a product-catalog row, sold to
    workspaces, not owned by one."""

    __tablename__ = "packages"

    key: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    modules: Mapped[list[str]] = mapped_column(JSON, default=list)
    limits: Mapped[dict] = mapped_column(JSON, default=dict)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str] = mapped_column(String(300), default="")
    price_monthly: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    price_yearly: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    trial_days: Mapped[int] = mapped_column(default=14)
    sort_order: Mapped[int] = mapped_column(default=0)


class Workspace(Base):
    """The tenant root — the "company" in ERP terms. Every TenantModel row's
    workspace_id points here."""

    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String(200))
    package_id: Mapped[str] = mapped_column(ForeignKey("packages.id"))
    currency: Mapped[str] = mapped_column(String(3), default="KES")
    default_tax_rate: Mapped[float] = mapped_column(default=0.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Platform super-admin switches on top of the package, e.g. {"hr": False}
    # for a customer who doesn't want payroll. Disabling never deletes data —
    # switching the module back on restores everything.
    module_overrides: Mapped[dict] = mapped_column(JSON, default=dict)

    # Branding — used to render documents (invoices, receipts) as the
    # organization's own letterhead rather than a generic template.
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    address: Mapped[str] = mapped_column(String(500), default="")
    phone: Mapped[str] = mapped_column(String(32), default="")
    billing_email: Mapped[str] = mapped_column(String(255), default="")
    invoice_footer_note: Mapped[str] = mapped_column(String(500), default="")
    tax_pin: Mapped[str] = mapped_column(String(32), default="")  # KRA PIN, printed on tax invoices
    website: Mapped[str] = mapped_column(String(200), default="")
    brand_color: Mapped[str] = mapped_column(String(7), default="#1a7a8c")
    invoice_template: Mapped[str] = mapped_column(String(16), default="modern")  # modern | bold | classic
    etims_mode: Mapped[str] = mapped_column(String(8), default="off")  # off | test | live (sales/etims.py)
    # Retail convention: the prices you type/scan already include VAT (the shelf
    # price). Off = prices are before VAT and VAT is added on top.
    prices_include_tax: Mapped[bool] = mapped_column(Boolean, default=False)
    # Payment instructions printed on invoices/statements.
    bank_details: Mapped[str] = mapped_column(String(1000), default="")
    mpesa_paybill: Mapped[str] = mapped_column(String(20), default="")
    mpesa_till: Mapped[str] = mapped_column(String(20), default="")
    default_payment_terms_days: Mapped[int] = mapped_column(default=30)
    invoice_terms: Mapped[str] = mapped_column(String(2000), default="")


class User(Base):
    """Global identity — a user may belong to more than one workspace (SME
    consultants/accountants serving multiple clients), unlike Tolkyn's
    1-user-usually-equals-1-workspace default."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(200), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    module_overrides: Mapped[dict] = mapped_column(JSON, default=dict)
    # Platform operator (super admin) — see actor.require_platform_admin.
    # Granted from the command line: `python -m app.cli make-admin <email>`.
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    # Bumped when the password changes: every token issued before then stops
    # working, so a stolen session dies with the old password.
    token_version: Mapped[int] = mapped_column(default=0)
    # Two-factor sign-in (TOTP authenticator app).
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    recovery_codes: Mapped[list] = mapped_column(JSON, default=list)  # SHA-256 hashes, each usable once


class WorkspaceRole(str, enum.Enum):
    owner = "owner"
    admin = "admin"
    manager = "manager"
    staff = "staff"
    viewer = "viewer"


ROLE_PERMISSIONS: dict[WorkspaceRole, set[str]] = {
    WorkspaceRole.owner: {"*"},
    WorkspaceRole.admin: {"*"},
    WorkspaceRole.manager: {
        "crm.write", "crm.read",
        "inventory.write", "inventory.read",
        "sales.write", "sales.read",
        "purchasing.write", "purchasing.read",
        "accounting.read",
        # HR admin (employees, leave) but not pay: salaries and bank details
        # stay visible only to owners/admins via payroll.*.
        "hr.read", "hr.write",
        "assets.read", "assets.write",
        "manufacturing.read", "manufacturing.write",
    },
    WorkspaceRole.staff: {
        "crm.write", "crm.read",
        "inventory.read",
        "sales.write", "sales.read",
        "purchasing.read",
    },
    WorkspaceRole.viewer: {
        "crm.read", "inventory.read", "sales.read", "purchasing.read", "accounting.read",
        "assets.read", "manufacturing.read",
    },
}


class WorkspaceMember(TenantModel):
    """Maps a User to a Workspace with a role. workspace_id (from TenantMixin) is
    the owning workspace; user_id is the member.

    Deliberately NOT protected by the Row-Level Security policy the other
    TenantModel tables get (see migrations — enable_rls() is skipped for this
    table). It's platform/bridge metadata, not business data: a user must be able
    to list every workspace they belong to in one query (PlatformService.
    list_workspaces_for_user), which is inherently a cross-tenant read. Regular
    per-workspace membership lookups still filter by workspace_id as normal.
    """

    __tablename__ = "workspace_members"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[WorkspaceRole] = mapped_column(default=WorkspaceRole.staff)
    permissions: Mapped[dict] = mapped_column(JSON, default=dict)

    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member"),)

    def effective_permissions(self) -> set[str]:
        base = set(ROLE_PERMISSIONS.get(self.role, set()))
        for perm, granted in self.permissions.items():
            if granted:
                base.add(perm)
            else:
                base.discard(perm)
        return base


class AuthTokenPurpose(str, enum.Enum):
    password_reset = "password_reset"
    invitation = "invitation"


class AuthToken(Base):
    """Single-use, expiring token behind a password-reset or invitation link.
    Only a SHA-256 of the token is stored — a leaked database can't be used to
    reset anyone's password or join a workspace."""

    __tablename__ = "auth_tokens"

    purpose: Mapped[AuthTokenPurpose]
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    # Invitations only: where the invitee lands, and as what.
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True, index=True)
    role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    invited_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None] = mapped_column(nullable=True)


class EmailLog(Base):
    """Every email the system tried to send — who to, what, and whether it
    actually left (or was only written to the outbox)."""

    __tablename__ = "email_log"

    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True, index=True)
    to: Mapped[str] = mapped_column(String(500))
    subject: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(32))  # invoice | statement | quote | invitation | password_reset
    reference: Mapped[str] = mapped_column(String(64), default="")
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    backend: Mapped[str] = mapped_column(String(16), default="")
    error: Mapped[str] = mapped_column(String(500), default="")
    sent_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
