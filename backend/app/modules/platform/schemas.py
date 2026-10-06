from pydantic import BaseModel, EmailStr, Field

from app.modules.platform.models import WorkspaceRole


class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str = ""
    workspace_name: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class WorkspaceOut(BaseModel):
    id: str
    name: str
    currency: str
    role: WorkspaceRole

    class Config:
        from_attributes = True


class MemberInvite(BaseModel):
    email: EmailStr
    role: WorkspaceRole = WorkspaceRole.staff


class MemberOut(BaseModel):
    id: str
    user_id: str
    email: str
    role: WorkspaceRole

    class Config:
        from_attributes = True


class BrandingUpdate(BaseModel):
    name: str | None = None
    logo_url: str | None = None
    address: str | None = None
    phone: str | None = None
    billing_email: str | None = None
    invoice_footer_note: str | None = None
    tax_pin: str | None = None
    website: str | None = None
    brand_color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    invoice_template: str | None = Field(default=None, pattern=r"^(modern|bold|classic)$")
    bank_details: str | None = None
    mpesa_paybill: str | None = None
    mpesa_till: str | None = None
    default_payment_terms_days: int | None = Field(default=None, ge=0, le=365)
    invoice_terms: str | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)


class BrandingOut(BaseModel):
    name: str
    logo_url: str | None
    address: str
    phone: str
    billing_email: str
    invoice_footer_note: str
    currency: str
    tax_pin: str
    website: str
    brand_color: str
    invoice_template: str
    bank_details: str
    mpesa_paybill: str
    mpesa_till: str
    default_payment_terms_days: int
    invoice_terms: str

    class Config:
        from_attributes = True
