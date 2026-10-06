from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor, get_actor, get_tenant_session
from app.modules.crm import importer
from app.modules.crm.schemas import (
    DealUpdate,
    FollowUpDone,
    PartyUpdate,
    TaskUpdate,
    TermsUpdate,
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


# ------------------------------------------------------- import / export
# (declared with fixed paths; FastAPI matches them before /parties/{party_id})


@router.get("/parties-template")
async def parties_template(actor: Actor = Depends(get_actor)):
    return importer.template()


@router.get("/parties-export")
async def export_parties(actor: Actor = Depends(get_actor), session: AsyncSession = Depends(get_tenant_session)):
    return await importer.export_parties(CrmService(session, actor.workspace_id))


@router.post("/parties-import")
async def import_parties(file: UploadFile, actor: Actor = Depends(get_actor), session: AsyncSession = Depends(get_tenant_session)):
    return await importer.import_parties(CrmService(session, actor.workspace_id), file)


# ------------------------------------------------------------------ edits


@router.get("/parties/{party_id}", response_model=PartyOut)
async def get_party(party_id: str, actor: Actor = Depends(get_actor), session: AsyncSession = Depends(get_tenant_session)):
    service = CrmService(session, actor.workspace_id)
    return await service._get(service.parties, party_id, "contact")


@router.patch("/parties/{party_id}", response_model=PartyOut)
async def update_party(
    party_id: str, payload: PartyUpdate, actor: Actor = Depends(get_actor), session: AsyncSession = Depends(get_tenant_session)
):
    return await CrmService(session, actor.workspace_id).update_party(party_id, payload.model_dump(exclude_unset=True))


@router.get("/parties/{party_id}/terms")
async def get_terms(party_id: str, actor: Actor = Depends(get_actor), session: AsyncSession = Depends(get_tenant_session)):
    return await CrmService(session, actor.workspace_id).get_terms(party_id)


@router.put("/parties/{party_id}/terms")
async def set_terms(
    party_id: str, payload: TermsUpdate, actor: Actor = Depends(get_actor), session: AsyncSession = Depends(get_tenant_session)
):
    return await CrmService(session, actor.workspace_id).set_terms(party_id, payload.payment_terms_days, payload.credit_limit)


@router.patch("/deals/{deal_id}", response_model=DealOut)
async def update_deal(
    deal_id: str, payload: DealUpdate, actor: Actor = Depends(get_actor), session: AsyncSession = Depends(get_tenant_session)
):
    return await CrmService(session, actor.workspace_id).update_deal(deal_id, payload.model_dump(exclude_unset=True))


@router.patch("/tasks/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: str, payload: TaskUpdate, actor: Actor = Depends(get_actor), session: AsyncSession = Depends(get_tenant_session)
):
    return await CrmService(session, actor.workspace_id).update_task(task_id, payload.model_dump(exclude_unset=True))


@router.post("/interactions/{interaction_id}/follow-up", response_model=InteractionOut)
async def set_follow_up_done(
    interaction_id: str, payload: FollowUpDone, actor: Actor = Depends(get_actor), session: AsyncSession = Depends(get_tenant_session)
):
    return await CrmService(session, actor.workspace_id).set_follow_up_done(interaction_id, payload.done)
