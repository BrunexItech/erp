from __future__ import annotations

from collections import Counter

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import features
from app.modules.platform.models import Package, User, Workspace, WorkspaceMember, WorkspaceRole


class AdminService:
    """Platform-operator view across every customer workspace. Only touches
    platform tables (workspaces, packages, users, workspace_members), none of
    which are RLS-scoped — no customer business data is read here."""

    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def modules() -> list[dict]:
        return [
            {"key": key, "name": name, "depends_on": features.MODULE_DEPENDENCIES.get(key, [])}
            for key, name in features.MODULES.items()
        ]

    async def packages(self) -> list[Package]:
        return list((await self.session.execute(select(Package).order_by(Package.name))).scalars())

    async def overview(self) -> dict:
        workspaces = (await self.session.execute(select(Workspace))).scalars().all()
        users = (await self.session.execute(select(func.count(User.id)))).scalar_one()
        packages = {p.id: p.name for p in await self.packages()}
        return {
            "workspaces": len(workspaces),
            "active_workspaces": sum(1 for w in workspaces if w.is_active),
            "users": users,
            "by_package": dict(Counter(packages.get(w.package_id, "?") for w in workspaces)),
        }

    async def _describe(self, workspace: Workspace, packages: dict[str, Package]) -> dict:
        package = packages.get(workspace.package_id)
        members = (
            await self.session.execute(
                select(WorkspaceMember, User)
                .join(User, User.id == WorkspaceMember.user_id)
                .where(WorkspaceMember.workspace_id == workspace.id)
            )
        ).all()
        owner = next((u.email for m, u in members if m.role == WorkspaceRole.owner), None)
        package_modules = package.modules if package else []
        return {
            "id": workspace.id,
            "name": workspace.name,
            "is_active": workspace.is_active,
            "created_at": workspace.created_at,
            "package_id": workspace.package_id,
            "package_name": package.name if package else "",
            "package_modules": package_modules,
            "module_overrides": workspace.module_overrides or {},
            "effective_modules": sorted(
                features.effective_workspace_modules(package_modules, workspace.module_overrides)
            ),
            "owner_email": owner,
            "member_count": len(members),
        }

    async def list_workspaces(self, search: str | None) -> list[dict]:
        stmt = select(Workspace).order_by(Workspace.created_at.desc())
        if search:
            like = f"%{search.lower()}%"
            owner_ids = select(WorkspaceMember.workspace_id).join(User, User.id == WorkspaceMember.user_id).where(
                func.lower(User.email).like(like)
            )
            stmt = stmt.where(or_(func.lower(Workspace.name).like(like), Workspace.id.in_(owner_ids)))
        workspaces = (await self.session.execute(stmt)).scalars().all()
        packages = {p.id: p for p in await self.packages()}
        return [await self._describe(w, packages) for w in workspaces]

    async def update_workspace(
        self,
        workspace_id: str,
        *,
        package_id: str | None,
        module_overrides: dict[str, bool | None] | None,
        is_active: bool | None,
    ) -> dict:
        workspace = (
            await self.session.execute(select(Workspace).where(Workspace.id == workspace_id))
        ).scalar_one_or_none()
        if workspace is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "workspace not found")
        packages = {p.id: p for p in await self.packages()}
        if package_id is not None:
            if package_id not in packages:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "package not found")
            workspace.package_id = package_id
        if module_overrides is not None:
            unknown = set(module_overrides) - set(features.MODULES)
            if unknown:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unknown module(s): {', '.join(sorted(unknown))}")
            merged = dict(workspace.module_overrides or {})
            for key, value in module_overrides.items():
                if value is None:
                    merged.pop(key, None)
                else:
                    merged[key] = value
            # Assign a new dict so SQLAlchemy sees the JSON column change.
            workspace.module_overrides = merged
        if is_active is not None:
            workspace.is_active = is_active
        await self.session.commit()
        await self.session.refresh(workspace)
        return await self._describe(workspace, packages)
