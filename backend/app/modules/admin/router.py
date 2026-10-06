from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import require_platform_admin
from app.modules.admin.operations import AdminOperations
from app.modules.billing.service import BillingService
from app.modules.platform.models import User
from app.core.db import get_session
from app.modules.admin.schemas import (
    AnnouncementWrite,
    ModuleInfo,
    PackageDetail,
    PackageOut,
    PackageWrite,
    PaymentRecord,
    PlatformSettingsWrite,
    SubscriptionUpdate,
    WorkspaceAdminOut,
    WorkspaceAdminUpdate,
    WorkspaceCreateByAdmin,
)
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
    workspace_id: str,
    payload: WorkspaceAdminUpdate,
    admin: User = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_session),
):
    ops = AdminOperations(session, admin)
    await ops._audit("workspace.updated", await ops._workspace(workspace_id), **payload.model_dump(exclude_unset=True))
    return await AdminService(session).update_workspace(
        workspace_id,
        package_id=payload.package_id,
        module_overrides=payload.module_overrides,
        is_active=payload.is_active,
    )


# ---------------------------------------------------------------- packages


@router.get("/packages/detail", response_model=list[PackageDetail])
async def packages_detail(admin: User = Depends(require_platform_admin), session: AsyncSession = Depends(get_session)):
    return await AdminOperations(session, admin).list_packages()


@router.post("/packages", response_model=PackageDetail)
async def create_package(payload: PackageWrite, admin: User = Depends(require_platform_admin), session: AsyncSession = Depends(get_session)):
    return await AdminOperations(session, admin).save_package(None, payload.model_dump())


@router.patch("/packages/{package_id}", response_model=PackageDetail)
async def update_package(
    package_id: str, payload: PackageWrite, admin: User = Depends(require_platform_admin), session: AsyncSession = Depends(get_session)
):
    return await AdminOperations(session, admin).save_package(package_id, payload.model_dump(exclude_unset=True))


# ---------------------------------------------------- workspaces: support


@router.post("/workspaces")
async def create_workspace(payload: WorkspaceCreateByAdmin, admin: User = Depends(require_platform_admin), session: AsyncSession = Depends(get_session)):
    return await AdminOperations(session, admin).create_workspace(payload.name, payload.owner_email, payload.package_id)


@router.get("/workspaces/{workspace_id}/detail")
async def workspace_detail(workspace_id: str, admin: User = Depends(require_platform_admin), session: AsyncSession = Depends(get_session)):
    return await AdminOperations(session, admin).workspace_detail(workspace_id)


@router.patch("/workspaces/{workspace_id}/subscription")
async def update_subscription(
    workspace_id: str, payload: SubscriptionUpdate, admin: User = Depends(require_platform_admin), session: AsyncSession = Depends(get_session)
):
    await AdminOperations(session, admin).update_subscription(workspace_id, payload.model_dump(exclude_unset=True))
    return {"ok": True}


@router.post("/workspaces/{workspace_id}/impersonate")
async def impersonate(workspace_id: str, admin: User = Depends(require_platform_admin), session: AsyncSession = Depends(get_session)):
    return await AdminOperations(session, admin).impersonate(workspace_id)


@router.post("/workspaces/{workspace_id}/members/{user_id}/reset-link")
async def reset_link(
    workspace_id: str, user_id: str, admin: User = Depends(require_platform_admin), session: AsyncSession = Depends(get_session)
):
    return {"link": await AdminOperations(session, admin).reset_link(workspace_id, user_id)}


# ----------------------------------------------------------------- billing


@router.get("/billing/summary")
async def billing_summary(admin: User = Depends(require_platform_admin), session: AsyncSession = Depends(get_session)):
    return await AdminOperations(session, admin).billing_summary()


@router.get("/billing/invoices")
async def billing_invoices(status: str | None = None, session: AsyncSession = Depends(get_session)):
    from sqlalchemy import select

    from app.modules.platform.models import Workspace

    invoices = await BillingService(session).invoices(status_filter=status)
    names = dict((await session.execute(select(Workspace.id, Workspace.name))).all())
    return [
        {
            "id": i.id, "number": i.number, "workspace_id": i.workspace_id, "workspace_name": names.get(i.workspace_id, ""),
            "package_name": i.package_name, "cycle": i.cycle.value, "period_start": i.period_start, "period_end": i.period_end,
            "amount": i.amount, "currency": i.currency, "status": i.status.value, "due_date": i.due_date,
            "paid_at": i.paid_at, "payment_method": i.payment_method, "payment_reference": i.payment_reference,
        }
        for i in invoices
    ]


@router.post("/billing/invoices/{invoice_id}/pay")
async def pay_invoice(
    invoice_id: str, payload: PaymentRecord, admin: User = Depends(require_platform_admin), session: AsyncSession = Depends(get_session)
):
    invoice = await AdminOperations(session, admin).record_payment(invoice_id, payload.method, payload.reference)
    return {"number": invoice.number, "status": invoice.status.value, "period_end": invoice.period_end}


@router.post("/billing/invoices/{invoice_id}/void")
async def void_invoice(invoice_id: str, admin: User = Depends(require_platform_admin), session: AsyncSession = Depends(get_session)):
    invoice = await AdminOperations(session, admin).void_invoice(invoice_id)
    return {"number": invoice.number, "status": invoice.status.value}


# ---------------------------------------- settings, announcements, audit


@router.get("/settings")
async def platform_settings(session: AsyncSession = Depends(get_session)):
    row = await BillingService(session).settings()
    await session.commit()
    return {c.name: getattr(row, c.name) for c in row.__table__.columns if c.name not in ("id", "created_at", "updated_at")}


@router.put("/settings")
async def update_platform_settings(
    payload: PlatformSettingsWrite, admin: User = Depends(require_platform_admin), session: AsyncSession = Depends(get_session)
):
    await AdminOperations(session, admin)._audit("settings.updated", changes=sorted(payload.model_dump(exclude_unset=True)))
    row = await BillingService(session).update_settings(payload.model_dump(exclude_unset=True))
    return {c.name: getattr(row, c.name) for c in row.__table__.columns if c.name not in ("id", "created_at", "updated_at")}


@router.get("/announcements")
async def list_announcements(admin: User = Depends(require_platform_admin), session: AsyncSession = Depends(get_session)):
    return [
        {"id": a.id, "title": a.title, "body": a.body, "level": a.level, "is_active": a.is_active, "created_at": a.created_at}
        for a in await AdminOperations(session, admin).list_announcements()
    ]


@router.post("/announcements")
async def create_announcement(payload: AnnouncementWrite, admin: User = Depends(require_platform_admin), session: AsyncSession = Depends(get_session)):
    a = await AdminOperations(session, admin).save_announcement(None, payload.model_dump())
    return {"id": a.id}


@router.patch("/announcements/{announcement_id}")
async def update_announcement(
    announcement_id: str, payload: AnnouncementWrite, admin: User = Depends(require_platform_admin), session: AsyncSession = Depends(get_session)
):
    a = await AdminOperations(session, admin).save_announcement(announcement_id, payload.model_dump())
    return {"id": a.id}


@router.get("/audit-log")
async def audit_log(admin: User = Depends(require_platform_admin), session: AsyncSession = Depends(get_session)):
    return [
        {"id": e.id, "at": e.created_at, "actor": e.actor_email, "action": e.action, "workspace": e.workspace_name, "detail": e.detail}
        for e in await AdminOperations(session, admin).audit_log()
    ]
