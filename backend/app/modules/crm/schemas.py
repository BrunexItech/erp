from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from app.modules.crm.models import DealStage, InteractionType, PartyKind


class PartyCreate(BaseModel):
    name: str
    kind: PartyKind = PartyKind.lead
    is_company: bool = False
    parent_party_id: str | None = None
    tax_id: str | None = None
    email: str | None = None
    phone: str | None = None
    billing_address: str = ""
    shipping_address: str = ""


class PartyOut(BaseModel):
    id: str
    name: str
    kind: PartyKind
    is_company: bool
    email: str | None
    phone: str | None

    class Config:
        from_attributes = True


class DealCreate(BaseModel):
    party_id: str
    title: str
    stage: DealStage = DealStage.new
    amount: Decimal = Decimal("0")
    expected_close_date: date | None = None
    owner_user_id: str | None = None


class DealOut(BaseModel):
    id: str
    party_id: str
    title: str
    stage: DealStage
    amount: Decimal
    expected_close_date: date | None

    class Config:
        from_attributes = True


class InteractionCreate(BaseModel):
    party_id: str
    type: InteractionType = InteractionType.note
    summary: str = ""
    occurred_at: datetime
    follow_up_at: datetime | None = None


class InteractionOut(BaseModel):
    id: str
    party_id: str
    type: InteractionType
    summary: str
    occurred_at: datetime
    follow_up_at: datetime | None
    is_follow_up_done: bool

    class Config:
        from_attributes = True


class TaskCreate(BaseModel):
    party_id: str | None = None
    deal_id: str | None = None
    title: str
    due_date: date | None = None
    assigned_to_user_id: str | None = None


class TaskOut(BaseModel):
    id: str
    party_id: str | None
    deal_id: str | None
    title: str
    due_date: date | None
    done: bool

    class Config:
        from_attributes = True
