from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor, get_actor, get_current_user, get_tenant_session, require_permission
from app.core import media, ratelimit
from app.core.db import get_session
from app.modules.platform.models import User
from app.modules.platform.accounts import AccountService
from app.modules.platform.schemas import (
    AcceptInvite,
    BrandingOut,
    BrandingUpdate,
    ChangePassword,
    ForgotPassword,
    InvitationInfo,
    InvitationOut,
    InviteResult,
    LoginRequest,
    MemberInvite,
    MemberOut,
    RefreshRequest,
    PasswordConfirm,
    ResetPassword,
    RoleUpdate,
    SignupRequest,
    TokenResponse,
    TotpCode,
    WorkspaceOut,
)
from app.modules.platform.service import PlatformService

router = APIRouter(prefix="/api/v1", tags=["platform"])


@router.post("/auth/signup", response_model=TokenResponse)
async def signup(payload: SignupRequest, session: AsyncSession = Depends(get_session)):
    return await PlatformService(session).signup(payload)


@router.post("/auth/login", response_model=TokenResponse)
async def login(payload: LoginRequest, request: Request, session: AsyncSession = Depends(get_session)):
    # 10 tries per 15 minutes per account-and-address: slows password guessing
    # to a crawl without locking out someone who mistypes a few times.
    await ratelimit.hit(f"login:{payload.email.lower()}:{ratelimit.client_ip(request)}", limit=10, window_seconds=900)
    return await PlatformService(session).login(payload)


@router.post("/auth/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest, session: AsyncSession = Depends(get_session)):
    return await PlatformService(session).refresh(payload.refresh_token)


@router.get("/workspaces", response_model=list[WorkspaceOut])
async def list_my_workspaces(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await PlatformService(session).list_workspaces_for_user(user.id)


@router.get("/auth/user")
async def current_user(user: User = Depends(get_current_user)):
    """Identity without a workspace context — used by the platform admin console."""
    return {
        "user_id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "is_platform_admin": user.is_platform_admin,
        "totp_enabled": user.totp_enabled,
    }


@router.get("/auth/me")
async def me(actor: Actor = Depends(get_actor)):
    """Resolves the active workspace's effective feature set (Package.modules +
    per-user overrides + dependency expansion) so the frontend can gate nav/routes
    without guessing — the backend still enforces this independently via
    require_feature on every gated router."""
    return {
        "user_id": actor.user_id,
        "workspace_id": actor.workspace_id,
        "role": actor.role,
        "permissions": sorted(actor.permissions),
        "features": sorted(actor.features),
        "billing": {"level": actor.billing_level, "message": actor.billing_message},
    }


@router.get("/workspaces/billing")
async def workspace_billing(actor: Actor = Depends(get_actor), session: AsyncSession = Depends(get_session)):
    """The customer's own subscription: plan, status, invoices and how to pay."""
    from app.modules.billing.service import BillingService

    return await BillingService(session).overview(actor.workspace_id)


@router.get("/announcements")
async def announcements(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    from app.modules.billing.service import BillingService

    return [
        {"id": a.id, "title": a.title, "body": a.body, "level": a.level}
        for a in await BillingService(session).active_announcements()
    ]


@router.get("/workspaces/branding", response_model=BrandingOut)
async def get_branding(
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await PlatformService(session).get_workspace(actor.workspace_id)


@router.patch("/workspaces/branding", response_model=BrandingOut)
async def update_branding(
    payload: BrandingUpdate,
    actor: Actor = Depends(require_permission("*")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await PlatformService(session).update_branding(actor.workspace_id, payload)


@router.post("/workspaces/branding/logo", response_model=BrandingOut)
async def upload_logo(
    file: UploadFile,
    actor: Actor = Depends(require_permission("*")),
    session: AsyncSession = Depends(get_tenant_session),
):
    data = await file.read(media.MAX_UPLOAD_BYTES + 1)
    logo_url = media.save_logo(actor.workspace_id, data)
    return await PlatformService(session).update_branding(actor.workspace_id, BrandingUpdate(logo_url=logo_url))


@router.delete("/workspaces/branding/logo", response_model=BrandingOut)
async def remove_logo(
    actor: Actor = Depends(require_permission("*")),
    session: AsyncSession = Depends(get_tenant_session),
):
    media.delete_logos(actor.workspace_id)
    return await PlatformService(session).update_branding(actor.workspace_id, BrandingUpdate(logo_url=None))


@router.get("/media/logos/{filename}")
async def serve_logo(filename: str):
    """Public on purpose: a logo appears on invoices sent to customers and in
    <img> tags, which can't send an Authorization header."""
    path = media.local_logo_path(media.LOGO_URL_PREFIX + filename)
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "logo not found")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "public, max-age=31536000, immutable"})


@router.get("/media/products/{filename}")
async def serve_product_image(filename: str):
    path = media.local_image_path(f"/api/v1/media/products/{filename}")
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "image not found")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "public, max-age=31536000, immutable"})


# ----------------------------------------------------------------- team


@router.get("/workspaces/members", response_model=list[MemberOut])
async def list_members(actor: Actor = Depends(get_actor), session: AsyncSession = Depends(get_tenant_session)):
    return await AccountService(session).list_members(actor.workspace_id)


@router.post("/workspaces/members", response_model=InviteResult)
async def invite_member(
    payload: MemberInvite,
    actor: Actor = Depends(require_permission("*")),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await AccountService(session).invite(actor.workspace_id, payload.email, payload.role, user, actor.role)


@router.patch("/workspaces/members/{member_id}", response_model=MemberOut)
async def change_member_role(
    member_id: str,
    payload: RoleUpdate,
    actor: Actor = Depends(require_permission("*")),
    session: AsyncSession = Depends(get_tenant_session),
):
    service = AccountService(session)
    await service.change_role(actor.workspace_id, member_id, payload.role, actor.role)
    return next(m for m in await service.list_members(actor.workspace_id) if m["id"] == member_id)


@router.delete("/workspaces/members/{member_id}")
async def remove_member(
    member_id: str,
    actor: Actor = Depends(require_permission("*")),
    session: AsyncSession = Depends(get_tenant_session),
):
    await AccountService(session).remove_member(actor.workspace_id, member_id, actor.role)
    return {"ok": True}


@router.get("/workspaces/invitations", response_model=list[InvitationOut])
async def list_invitations(actor: Actor = Depends(require_permission("*")), session: AsyncSession = Depends(get_tenant_session)):
    return await AccountService(session).list_invitations(actor.workspace_id)


@router.delete("/workspaces/invitations/{invitation_id}")
async def revoke_invitation(
    invitation_id: str,
    actor: Actor = Depends(require_permission("*")),
    session: AsyncSession = Depends(get_tenant_session),
):
    await AccountService(session).revoke_invitation(actor.workspace_id, invitation_id)
    return {"ok": True}


@router.get("/auth/invitations/{token}", response_model=InvitationInfo)
async def invitation_info(token: str, session: AsyncSession = Depends(get_session)):
    return await AccountService(session).invitation_info(token)


@router.post("/auth/accept-invite", response_model=TokenResponse)
async def accept_invitation(payload: AcceptInvite, session: AsyncSession = Depends(get_session)):
    return await AccountService(session).accept_invitation(payload.token, payload.full_name, payload.password)


# ------------------------------------------------------------- passwords


@router.post("/auth/forgot-password")
async def forgot_password(payload: ForgotPassword, request: Request, session: AsyncSession = Depends(get_session)):
    await ratelimit.hit(f"forgot:{payload.email.lower()}", limit=3, window_seconds=3600)
    await ratelimit.hit(f"forgot-ip:{ratelimit.client_ip(request)}", limit=20, window_seconds=3600)
    await AccountService(session).forgot_password(payload.email)
    # Same answer whether or not the address exists.
    return {"ok": True}


@router.post("/auth/reset-password")
async def reset_password(payload: ResetPassword, session: AsyncSession = Depends(get_session)):
    await AccountService(session).reset_password(payload.token, payload.password)
    return {"ok": True}


@router.post("/auth/change-password", response_model=TokenResponse)
async def change_password(
    payload: ChangePassword,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await AccountService(session).change_password(user, payload.current_password, payload.new_password)


# ------------------------------------------------------------ two-factor


@router.post("/auth/2fa/setup")
async def totp_setup(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    from app.modules.billing.service import BillingService

    issuer = (await BillingService(session).settings()).product_name
    return await AccountService(session).totp_begin(user, issuer)


@router.post("/auth/2fa/enable")
async def totp_enable(payload: TotpCode, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    return {"recovery_codes": await AccountService(session).totp_enable(user, payload.code)}


@router.post("/auth/2fa/disable")
async def totp_disable(payload: PasswordConfirm, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    await AccountService(session).totp_disable(user, payload.password)
    return {"ok": True}


@router.get("/workspaces/activity")
async def activity_log(
    area: str | None = None,
    limit: int = 200,
    actor: Actor = Depends(require_permission("*")),
    session: AsyncSession = Depends(get_tenant_session),
):
    """Who changed what in this workspace — owners and admins only."""
    from sqlalchemy import select

    from app.core.activity import ActivityLog

    stmt = select(ActivityLog).where(ActivityLog.workspace_id == actor.workspace_id).order_by(ActivityLog.created_at.desc())
    if area:
        stmt = stmt.where(ActivityLog.area == area)
    rows = (await session.execute(stmt.limit(min(limit, 500)))).scalars()
    return [
        {"id": r.id, "at": r.created_at, "user": r.user_email, "action": r.action, "area": r.area, "via_support": r.via_support}
        for r in rows
    ]


# ------------------------------------------------------------ attachments


@router.get("/attachments")
async def list_attachments(
    entity_type: str, entity_id: str, actor: Actor = Depends(get_actor), session: AsyncSession = Depends(get_tenant_session)
):
    from app.core.attachments import AttachmentService

    return [
        {"id": a.id, "filename": a.filename, "content_type": a.content_type, "size": a.size, "created_at": a.created_at}
        for a in await AttachmentService(session, actor.workspace_id).list(entity_type, entity_id)
    ]


@router.post("/attachments")
async def upload_attachment(
    entity_type: str,
    entity_id: str,
    file: UploadFile,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    from app.core.attachments import AttachmentService

    if "*" not in actor.permissions and not any(p.endswith(".write") for p in actor.permissions):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "your role can't add files")
    a = await AttachmentService(session, actor.workspace_id).add(entity_type, entity_id, file, actor.user_id)
    return {"id": a.id, "filename": a.filename, "content_type": a.content_type, "size": a.size, "created_at": a.created_at}


@router.get("/attachments/{attachment_id}/download")
async def download_attachment(attachment_id: str, actor: Actor = Depends(get_actor), session: AsyncSession = Depends(get_tenant_session)):
    from app.core.attachments import AttachmentService

    attachment, path = await AttachmentService(session, actor.workspace_id).path(attachment_id)
    return FileResponse(
        path,
        media_type=attachment.content_type,
        filename=attachment.filename,
        # "nosniff": the browser must not second-guess the type we chose.
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )


@router.delete("/attachments/{attachment_id}")
async def delete_attachment(attachment_id: str, actor: Actor = Depends(get_actor), session: AsyncSession = Depends(get_tenant_session)):
    from app.core.attachments import AttachmentService

    if "*" not in actor.permissions and not any(p.endswith(".write") for p in actor.permissions):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "your role can't remove files")
    await AttachmentService(session, actor.workspace_id).delete(attachment_id)
    return {"ok": True}
