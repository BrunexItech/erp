from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import require_platform_admin
from app.core.db import get_session
from app.modules.admin.schemas import ModuleInfo, PackageOut, WorkspaceAdminOut, WorkspaceAdminUpdate
from app.modules.admin.service import AdminService

# Every route here is platform-operator only; no X-Workspace-Id needed.
router = APIRouter(prefix="/api/v1/admin", tags=["admin"], dependencies=[Depends(require_platform_admin)])


@router.get("/overview")
async def overview(session: AsyncSession = Depends(get_session)):
    return await AdminService(session).overview()


@router.get("/modules", response_model=list[ModuleInfo])
async def modules():
    return AdminService.modules()


@router.get("/packages", response_model=list[PackageOut])
async def packages(session: AsyncSession = Depends(get_session)):
    return await AdminService(session).packages()


@router.get("/workspaces", response_model=list[WorkspaceAdminOut])
async def list_workspaces(search: str | None = None, session: AsyncSession = Depends(get_session)):
    return await AdminService(session).list_workspaces(search)


@router.patch("/workspaces/{workspace_id}", response_model=WorkspaceAdminOut)
async def update_workspace(
    workspace_id: str, payload: WorkspaceAdminUpdate, session: AsyncSession = Depends(get_session)
):
    return await AdminService(session).update_workspace(
        workspace_id,
        package_id=payload.package_id,
        module_overrides=payload.module_overrides,
        is_active=payload.is_active,
    )
