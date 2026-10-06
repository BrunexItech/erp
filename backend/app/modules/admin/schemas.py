from datetime import datetime

from pydantic import BaseModel


class ModuleInfo(BaseModel):
    key: str
    name: str
    depends_on: list[str]


class PackageOut(BaseModel):
    id: str
    key: str
    name: str
    modules: list[str]

    class Config:
        from_attributes = True


class WorkspaceAdminOut(BaseModel):
    id: str
    name: str
    is_active: bool
    created_at: datetime
    package_id: str
    package_name: str
    package_modules: list[str]
    module_overrides: dict[str, bool]
    effective_modules: list[str]
    owner_email: str | None
    member_count: int


class WorkspaceAdminUpdate(BaseModel):
    """module_overrides: {"hr": false} switches HR off for this customer,
    {"manufacturing": true} switches on something their package lacks, and
    {"hr": null} clears the override so the package decides again."""

    package_id: str | None = None
    module_overrides: dict[str, bool | None] | None = None
    is_active: bool | None = None


# ---------------------------------------------------------------- phase 2

from datetime import date  # noqa: E402
from decimal import Decimal  # noqa: E402

from pydantic import EmailStr, Field  # noqa: E402


class PackageDetail(BaseModel):
    id: str
    key: str
    name: str
    description: str
    modules: list[str]
    limits: dict
    price_monthly: Decimal
    price_yearly: Decimal
    trial_days: int
    is_default: bool
    is_active: bool
    sort_order: int

    class Config:
        from_attributes = True


class PackageWrite(BaseModel):
    key: str | None = Field(default=None, pattern=r"^[a-z0-9_-]{2,50}$")
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    modules: list[str] | None = None
    max_users: int | None = Field(default=None, ge=1)
    max_sku: int | None = Field(default=None, ge=1)
    unlimited_users: bool = False
    unlimited_sku: bool = False
    price_monthly: Decimal | None = Field(default=None, ge=0)
    price_yearly: Decimal | None = Field(default=None, ge=0)
    trial_days: int | None = Field(default=None, ge=0, le=365)
    is_default: bool | None = None
    is_active: bool | None = None
    sort_order: int | None = None


class SubscriptionUpdate(BaseModel):
    status: str | None = Field(default=None, pattern="^(trialing|active|complimentary|cancelled)$")
    cycle: str | None = Field(default=None, pattern="^(monthly|yearly)$")
    trial_ends_at: date | None = None
    current_period_end: date | None = None
    notes: str | None = None


class PaymentRecord(BaseModel):
    method: str = "mpesa"
    reference: str = ""


class WorkspaceCreateByAdmin(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    owner_email: EmailStr
    package_id: str


class AnnouncementWrite(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = ""
    level: str = Field(default="info", pattern="^(info|warning)$")
    is_active: bool = True


class PlatformSettingsWrite(BaseModel):
    product_name: str | None = None
    support_email: str | None = None
    support_phone: str | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    mpesa_paybill: str | None = None
    mpesa_till: str | None = None
    bank_details: str | None = None
    grace_days: int | None = Field(default=None, ge=0, le=90)
    invoice_lead_days: int | None = Field(default=None, ge=0, le=60)
