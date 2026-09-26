from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.db import set_tenant_context
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.modules.platform.models import Package, User, Workspace, WorkspaceMember, WorkspaceRole
from app.modules.platform.schemas import (
    BrandingUpdate,
    LoginRequest,
    MemberInvite,
    SignupRequest,
    TokenResponse,
)


class PlatformService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def signup(self, payload: SignupRequest) -> TokenResponse:
        existing = (
            await self.session.execute(select(User).where(User.email == payload.email))
        ).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "email already registered")

        default_package = (
            await self.session.execute(select(Package).where(Package.is_default == True))  # noqa: E712
        ).scalar_one_or_none()
        if default_package is None:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "no default package configured — run seed data",
            )

        user = User(
            email=payload.email,
            hashed_password=hash_password(payload.password),
            full_name=payload.full_name,
        )
        self.session.add(user)
        await self.session.flush()

        workspace = Workspace(name=payload.workspace_name, package_id=default_package.id)
        self.session.add(workspace)
        await self.session.flush()

        # WorkspaceMember and every module's seed data (e.g. accounting's default
        # chart of accounts, triggered below) are RLS-protected tenant tables — set
        # the session's tenant context now so inserts for this brand-new workspace
        # pass the policy for the rest of this transaction.
        await set_tenant_context(self.session, workspace.id)

        membership = WorkspaceMember(
            workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.owner
        )
        self.session.add(membership)
        await self.session.flush()

        await events.publish(events.WorkspaceCreated(workspace_id=workspace.id), self.session)
        await self.session.commit()

        return TokenResponse(
            access_token=create_access_token(user.id),
            refresh_token=create_refresh_token(user.id),
        )

    async def login(self, payload: LoginRequest) -> TokenResponse:
        user = (
            await self.session.execute(select(User).where(User.email == payload.email))
        ).scalar_one_or_none()
        if user is None or not verify_password(payload.password, user.hashed_password):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
        if not user.is_active:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "account disabled")

        return TokenResponse(
            access_token=create_access_token(user.id),
            refresh_token=create_refresh_token(user.id),
        )

    async def refresh(self, refresh_token: str) -> TokenResponse:
        try:
            user_id = decode_token(refresh_token, expected_type="refresh")
        except Exception:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid refresh token")

        user = (
            await self.session.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if user is None or not user.is_active:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user not found or inactive")

        return TokenResponse(
            access_token=create_access_token(user.id),
            refresh_token=create_refresh_token(user.id),
        )

    async def list_workspaces_for_user(self, user_id: str) -> list[dict]:
        rows = await self.session.execute(
            select(WorkspaceMember, Workspace)
            .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
            .where(WorkspaceMember.user_id == user_id)
        )
        return [
            {
                "id": workspace.id,
                "name": workspace.name,
                "currency": workspace.currency,
                "role": member.role,
            }
            for member, workspace in rows.all()
        ]

    async def invite_member(self, workspace_id: str, payload: MemberInvite) -> WorkspaceMember:
        user = (
            await self.session.execute(select(User).where(User.email == payload.email))
        ).scalar_one_or_none()
        if user is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                "no user with that email — they must sign up first",
            )

        existing = (
            await self.session.execute(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.user_id == user.id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "already a member")

        membership = WorkspaceMember(
            workspace_id=workspace_id, user_id=user.id, role=payload.role
        )
        self.session.add(membership)
        await self.session.commit()
        await self.session.refresh(membership)
        return membership

    async def get_workspace(self, workspace_id: str) -> Workspace:
        workspace = (
            await self.session.execute(select(Workspace).where(Workspace.id == workspace_id))
        ).scalar_one_or_none()
        if workspace is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "workspace not found")
        return workspace

    async def update_branding(self, workspace_id: str, payload: BrandingUpdate) -> Workspace:
        workspace = await self.get_workspace(workspace_id)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(workspace, field, value)
        await self.session.commit()
        await self.session.refresh(workspace)
        return workspace
