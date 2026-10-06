from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor, get_actor, get_current_user, get_tenant_session, require_permission
from app.core import media
from app.core.db import get_session
from app.modules.platform.models import User
from app.modules.platform.schemas import (
    BrandingOut,
    BrandingUpdate,
    LoginRequest,
    MemberInvite,
    MemberOut,
    RefreshRequest,
    SignupRequest,
    TokenResponse,
    WorkspaceOut,
)
from app.modules.platform.service import PlatformService

router = APIRouter(prefix="/api/v1", tags=["platform"])


@router.post("/auth/signup", response_model=TokenResponse)
async def signup(payload: SignupRequest, session: AsyncSession = Depends(get_session)):
    return await PlatformService(session).signup(payload)


@router.post("/auth/login", response_model=TokenResponse)
async def login(payload: LoginRequest, session: AsyncSession = Depends(get_session)):
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
    }


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


@router.post("/workspaces/members", response_model=MemberOut)
async def invite_member(
    payload: MemberInvite,
    actor: Actor = Depends(require_permission("*")),
    session: AsyncSession = Depends(get_tenant_session),
):
    membership = await PlatformService(session).invite_member(actor.workspace_id, payload)
    return MemberOut(
        id=membership.id, user_id=membership.user_id, email=payload.email, role=membership.role
    )
