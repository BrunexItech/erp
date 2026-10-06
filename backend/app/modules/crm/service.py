from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import TenantRepository
from fastapi import HTTPException, status

from app.modules.crm.models import CustomerProfile, Deal, Interaction, Party, PartyKind, Task, VendorProfile
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

    @staticmethod
    def _naive_utc(value: datetime | None) -> datetime | None:
        """Timestamp columns are timezone-free UTC; browsers send offsets."""
        if value is None or value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    async def log_interaction(self, payload: InteractionCreate) -> Interaction:
        data = payload.model_dump()
        data["occurred_at"] = self._naive_utc(data["occurred_at"])
        data["follow_up_at"] = self._naive_utc(data["follow_up_at"])
        interaction = Interaction(**data)
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
        interactions = await self.interactions.list(Interaction.party_id == party_id)
        return sorted(interactions, key=lambda i: i.occurred_at, reverse=True)

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
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        return list(
            await self.interactions.list(
                Interaction.follow_up_at.is_not(None),
                Interaction.follow_up_at <= now,
                Interaction.is_follow_up_done.is_(False),
            )
        )

    # ---------------------------------------------------------------- edits

    async def _get(self, repo, id: str, what: str):
        obj = await repo.get(id)
        if obj is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found")
        return obj

    async def _apply(self, obj, changes: dict):
        for key, value in changes.items():
            setattr(obj, key, value)
        await self.session.commit()
        await self.session.refresh(obj)
        return obj

    async def update_party(self, party_id: str, changes: dict) -> Party:
        party = await self._get(self.parties, party_id, "contact")
        if changes.get("name") == "":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "name can't be empty")
        return await self._apply(party, changes)

    async def update_deal(self, deal_id: str, changes: dict) -> Deal:
        return await self._apply(await self._get(self.deals, deal_id, "deal"), changes)

    async def update_task(self, task_id: str, changes: dict) -> Task:
        return await self._apply(await self._get(self.tasks, task_id, "task"), changes)

    async def set_follow_up_done(self, interaction_id: str, done: bool) -> Interaction:
        interaction = await self._get(self.interactions, interaction_id, "interaction")
        return await self._apply(interaction, {"is_follow_up_done": done})

    async def get_terms(self, party_id: str) -> dict:
        await self._get(self.parties, party_id, "contact")
        customers = TenantRepository(self.session, self.workspace_id, CustomerProfile)
        profile = (await customers.list(CustomerProfile.party_id == party_id) or [None])[0]
        return {
            "payment_terms_days": profile.payment_terms_days if profile else None,
            "credit_limit": profile.credit_limit if profile else 0,
        }

    async def set_terms(self, party_id: str, payment_terms_days: int, credit_limit) -> dict:
        """Stored for both roles a contact can play, so the same terms drive
        invoice due dates (customer) and bill due dates (vendor)."""
        party = await self._get(self.parties, party_id, "contact")
        customers = TenantRepository(self.session, self.workspace_id, CustomerProfile)
        vendors = TenantRepository(self.session, self.workspace_id, VendorProfile)
        if party.kind != PartyKind.vendor:
            profile = (await customers.list(CustomerProfile.party_id == party_id) or [None])[0]
            if profile is None:
                await customers.add(CustomerProfile(party_id=party_id, payment_terms_days=payment_terms_days, credit_limit=credit_limit))
            else:
                profile.payment_terms_days, profile.credit_limit = payment_terms_days, credit_limit
        if party.kind in (PartyKind.vendor, PartyKind.both):
            vendor = (await vendors.list(VendorProfile.party_id == party_id) or [None])[0]
            if vendor is None:
                await vendors.add(VendorProfile(party_id=party_id, payment_terms_days=payment_terms_days))
            else:
                vendor.payment_terms_days = payment_terms_days
        await self.session.commit()
        return {"payment_terms_days": payment_terms_days, "credit_limit": credit_limit}
