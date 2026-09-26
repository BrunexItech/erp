from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor, get_tenant_session, require_permission
from app.modules.assets.schemas import (
    AssetCategoryCreate,
    AssetCategoryOut,
    AssetCreate,
    AssetOut,
    DepreciationRunRequest,
    DisposalRequest,
)
from app.modules.assets.service import AssetService

router = APIRouter(prefix="/api/v1/assets", tags=["assets"])

read = require_permission("assets.read")
write = require_permission("assets.write")


@router.get("/categories", response_model=list[AssetCategoryOut])
async def list_categories(actor: Actor = Depends(read), session: AsyncSession = Depends(get_tenant_session)):
    return sorted(await AssetService(session, actor.workspace_id).categories.list(), key=lambda c: c.name)


@router.post("/categories", response_model=AssetCategoryOut)
async def create_category(
    payload: AssetCategoryCreate, actor: Actor = Depends(write), session: AsyncSession = Depends(get_tenant_session)
):
    return await AssetService(session, actor.workspace_id).create_category(payload)


@router.get("", response_model=list[AssetOut])
async def list_assets(actor: Actor = Depends(read), session: AsyncSession = Depends(get_tenant_session)):
    return (await AssetService(session, actor.workspace_id).register())["assets"]


@router.get("/register")
async def asset_register(actor: Actor = Depends(read), session: AsyncSession = Depends(get_tenant_session)):
    register = await AssetService(session, actor.workspace_id).register()
    return {"assets": [AssetOut.model_validate(a) for a in register["assets"]], "totals": register["totals"]}


@router.post("", response_model=AssetOut)
async def create_asset(payload: AssetCreate, actor: Actor = Depends(write), session: AsyncSession = Depends(get_tenant_session)):
    return await AssetService(session, actor.workspace_id).create_asset(payload)


@router.get("/{asset_id}", response_model=AssetOut)
async def get_asset(asset_id: str, actor: Actor = Depends(read), session: AsyncSession = Depends(get_tenant_session)):
    return await AssetService(session, actor.workspace_id).get_asset(asset_id)


@router.get("/{asset_id}/schedule")
async def depreciation_schedule(asset_id: str, actor: Actor = Depends(read), session: AsyncSession = Depends(get_tenant_session)):
    return await AssetService(session, actor.workspace_id).schedule(asset_id)


@router.post("/depreciation-runs")
async def run_depreciation(
    payload: DepreciationRunRequest, actor: Actor = Depends(write), session: AsyncSession = Depends(get_tenant_session)
):
    return await AssetService(session, actor.workspace_id).run_depreciation(payload.year, payload.month)


@router.post("/{asset_id}/dispose", response_model=AssetOut)
async def dispose_asset(
    asset_id: str,
    payload: DisposalRequest,
    actor: Actor = Depends(write),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await AssetService(session, actor.workspace_id).dispose(asset_id, payload.disposal_date, payload.proceeds)
