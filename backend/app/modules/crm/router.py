from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor, get_actor, get_tenant_session
from app.modules.crm.schemas import (
    DealCreate,
    DealOut,
    InteractionCreate,
    InteractionOut,
    PartyCreate,
    PartyOut,
    TaskCreate,
    TaskOut,
)
from app.modules.crm.service import CrmService

router = APIRouter(prefix="/api/v1/crm", tags=["crm"])


@router.post("/parties", response_model=PartyOut)
async def create_party(
    payload: PartyCreate,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await CrmService(session, actor.workspace_id).create_party(payload)


@router.get("/parties", response_model=list[PartyOut])
async def list_parties(
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await CrmService(session, actor.workspace_id).parties.list()


@router.post("/deals", response_model=DealOut)
async def create_deal(
    payload: DealCreate,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await CrmService(session, actor.workspace_id).create_deal(payload)


@router.get("/deals", response_model=list[DealOut])
async def list_deals(
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await CrmService(session, actor.workspace_id).deals.list()


@router.post("/interactions", response_model=InteractionOut)
async def log_interaction(
    payload: InteractionCreate,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await CrmService(session, actor.workspace_id).log_interaction(payload)


@router.get("/parties/{party_id}/timeline", response_model=list[InteractionOut])
async def party_timeline(
    party_id: str,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await CrmService(session, actor.workspace_id).timeline_for_party(party_id)


@router.get("/interactions/needs-follow-up", response_model=list[InteractionOut])
async def needs_follow_up(
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await CrmService(session, actor.workspace_id).needs_follow_up()


@router.post("/tasks", response_model=TaskOut)
async def create_task(
    payload: TaskCreate,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await CrmService(session, actor.workspace_id).create_task(payload)


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await CrmService(session, actor.workspace_id).tasks.list()
