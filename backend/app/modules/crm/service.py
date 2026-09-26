from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import TenantRepository
from app.modules.crm.models import Deal, Interaction, Party, PartyKind, Task
from app.modules.crm.schemas import DealCreate, InteractionCreate, PartyCreate, TaskCreate


class CrmService:
    def __init__(self, session: AsyncSession, workspace_id: str):
        self.session = session
        self.workspace_id = workspace_id
        self.parties = TenantRepository(session, workspace_id, Party)
        self.deals = TenantRepository(session, workspace_id, Deal)
        self.interactions = TenantRepository(session, workspace_id, Interaction)
        self.tasks = TenantRepository(session, workspace_id, Task)

    async def create_party(self, payload: PartyCreate) -> Party:
        party = Party(**payload.model_dump())
        await self.parties.add(party)
        await self.session.commit()
        await self.session.refresh(party)
        return party

    async def create_deal(self, payload: DealCreate) -> Deal:
        deal = Deal(**payload.model_dump())
        await self.deals.add(deal)
        await self.session.commit()
        await self.session.refresh(deal)
        return deal

    async def log_interaction(self, payload: InteractionCreate) -> Interaction:
        interaction = Interaction(**payload.model_dump())
        await self.interactions.add(interaction)
        await self.session.commit()
        await self.session.refresh(interaction)
        return interaction

    async def create_task(self, payload: TaskCreate) -> Task:
        task = Task(**payload.model_dump())
        await self.tasks.add(task)
        await self.session.commit()
        await self.session.refresh(task)
        return task

    async def timeline_for_party(self, party_id: str) -> list[Interaction]:
        return list(
            await self.interactions.list(Interaction.party_id == party_id)
        )

    async def get_or_create_walk_in_customer(self) -> Party:
        """POS checkout needs a party to bill even when no specific customer is
        picked — a single 'Walk-in Customer' record per workspace, created on
        first use."""
        existing = await self.parties.list(Party.name == "Walk-in Customer")
        if existing:
            return existing[0]
        party = Party(name="Walk-in Customer", kind=PartyKind.customer)
        await self.parties.add(party)
        await self.session.flush()
        return party

    async def needs_follow_up(self) -> list[Interaction]:
        now = datetime.now(timezone.utc)
        return list(
            await self.interactions.list(
                Interaction.follow_up_at.is_not(None),
                Interaction.follow_up_at <= now,
                Interaction.is_follow_up_done.is_(False),
            )
        )
