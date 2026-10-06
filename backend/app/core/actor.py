from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import features as feature_defs
from app.core.db import get_session, set_tenant_context
from app.core.security import decode_claims
from app.modules.platform.models import Package, User, Workspace, WorkspaceMember

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Actor:
    user_id: str
    workspace_id: str
    role: str
    permissions: set[str]
    features: set[str]
    billing_level: str = "ok"  # ok | grace | locked (see billing.service.access_for)
    billing_message: str = ""


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    try:
        claims = decode_claims(credentials.credentials, expected_type="access")
    except JWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token")

    user = (
        await session.execute(select(User).where(User.id == claims["sub"]))
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user not found or inactive")
    # Tokens issued before the last password change are dead.
    if claims.get("tv", 0) != user.token_version:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session ended — sign in again")
    return user


async def get_actor(
    x_workspace_id: str | None = Header(default=None, alias="X-Workspace-Id"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Actor:
    if not x_workspace_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-Workspace-Id header required")

    membership = (
        await session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == x_workspace_id,
                WorkspaceMember.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not a member of this workspace")

    workspace = (
        await session.execute(select(Workspace).where(Workspace.id == x_workspace_id))
    ).scalar_one_or_none()
    if workspace is None or not workspace.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "workspace inactive")

    package = (
        await session.execute(select(Package).where(Package.id == workspace.package_id))
    ).scalar_one_or_none()
    package_modules = package.modules if package else []

    effective = feature_defs.effective_workspace_modules(
        package_modules, workspace.module_overrides, user.module_overrides
    )

    from app.modules.billing.service import BillingService

    access = await BillingService(session).access(workspace.id)

    return Actor(
        user_id=user.id,
        workspace_id=workspace.id,
        role=membership.role.value if hasattr(membership.role, "value") else membership.role,
        permissions=membership.effective_permissions(),
        features=effective,
        billing_level=access.level,
        billing_message=access.message,
    )


async def get_tenant_session(
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_session),
) -> AsyncSession:
    """Session pre-scoped for RLS: FastAPI caches get_session's result per request, so
    this is the SAME session instance get_actor used — the SET LOCAL below applies to
    the same transaction every subsequent query in this request runs in."""
    await set_tenant_context(session, actor.workspace_id)
    return session


def require_permission(name: str):
    async def checker(actor: Actor = Depends(get_actor)) -> Actor:
        if "*" in actor.permissions or name in actor.permissions:
            return actor
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"missing permission: {name}")

    return checker


def _require_paid(actor: Actor) -> None:
    """Business modules stop when the subscription has lapsed past its grace
    period. Sign-in, Settings and the Billing page keep working (they don't go
    through this), so the customer can always see why and pay."""
    if actor.billing_level == "locked":
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, actor.billing_message or "subscription required")


def require_feature(*module_keys: str):
    async def checker(actor: Actor = Depends(get_actor)) -> Actor:
        _require_paid(actor)
        if not any(key in actor.features for key in module_keys):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"workspace package does not include: {', '.join(module_keys)}",
            )
        return actor

    return checker


def module_access(feature: str, permission_prefix: str | None = None):
    """Router-level guard: the workspace must have the module, and the member
    must hold `<prefix>.read` to view or `<prefix>.write` to change anything.
    Applied once per router in main.py so no endpoint can forget it — before
    this, a "viewer" could post an invoice because only the feature was checked.
    """
    prefix = permission_prefix or feature

    async def checker(request: Request, actor: Actor = Depends(get_actor)) -> Actor:
        _require_paid(actor)
        if feature not in actor.features:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"workspace package does not include: {feature}")
        if "*" in actor.permissions:
            return actor
        needed = f"{prefix}.read" if request.method in ("GET", "HEAD", "OPTIONS") else f"{prefix}.write"
        # Write access implies read access.
        if needed in actor.permissions or (needed.endswith(".read") and f"{prefix}.write" in actor.permissions):
            return actor
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"your role doesn't allow this (needs {needed})")

    return checker


async def require_platform_admin(user: User = Depends(get_current_user)) -> User:
    """The ERP operator (you), not a customer's owner/admin: manages every
    workspace's package and module switches from /admin."""
    if not user.is_platform_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "platform admin only")
    return user
