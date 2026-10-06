from datetime import datetime

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
    totp_code: str | None = None  # 6-digit authenticator code, or a recovery code


class TotpCode(BaseModel):
    code: str


class PasswordConfirm(BaseModel):
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
    full_name: str = ""
    role: WorkspaceRole
    is_active: bool = True
    joined_at: datetime | None = None

    class Config:
        from_attributes = True


class InviteResult(BaseModel):
    email: str
    role: WorkspaceRole
    invite_link: str  # shown to the inviter so it can also be shared by WhatsApp/SMS
    email_delivered: bool


class InvitationOut(BaseModel):
    id: str
    email: str
    role: str | None
    expires_at: datetime
    created_at: datetime

    class Config:
        from_attributes = True


class RoleUpdate(BaseModel):
    role: WorkspaceRole


class InvitationInfo(BaseModel):
    email: str
    workspace_name: str
    role: str | None
    has_account: bool


class AcceptInvite(BaseModel):
    token: str
    full_name: str = ""
    password: str


class ForgotPassword(BaseModel):
    email: EmailStr


class ResetPassword(BaseModel):
    token: str
    password: str


class ChangePassword(BaseModel):
    current_password: str
    new_password: str


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
    etims_mode: str | None = Field(default=None, pattern=r"^(off|test|live)$")
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
    etims_mode: str
    bank_details: str
    mpesa_paybill: str
    mpesa_till: str
    default_payment_terms_days: int
    invoice_terms: str

    class Config:
        from_attributes = True
