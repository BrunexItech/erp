from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

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


class PartyUpdate(BaseModel):
    name: str | None = None
    kind: PartyKind | None = None
    is_company: bool | None = None
    tax_id: str | None = None
    email: str | None = None
    phone: str | None = None
    billing_address: str | None = None
    shipping_address: str | None = None


class PartyOut(BaseModel):
    id: str
    name: str
    kind: PartyKind
    is_company: bool
    tax_id: str | None
    email: str | None
    phone: str | None
    billing_address: str
    shipping_address: str
    created_at: datetime

    class Config:
        from_attributes = True


class DealCreate(BaseModel):
    party_id: str
    title: str
    stage: DealStage = DealStage.new
    amount: Decimal = Decimal("0")
    expected_close_date: date | None = None
    owner_user_id: str | None = None


class DealUpdate(BaseModel):
    title: str | None = None
    stage: DealStage | None = None
    amount: Decimal | None = None
    expected_close_date: date | None = None


class TermsUpdate(BaseModel):
    """Customer credit terms: how long they have to pay, and how much they may owe."""

    payment_terms_days: int = Field(ge=0, le=365)
    credit_limit: Decimal = Field(default=Decimal("0"), ge=0)


class TaskUpdate(BaseModel):
    done: bool | None = None
    title: str | None = None
    due_date: date | None = None


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


class FollowUpDone(BaseModel):
    done: bool = True


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
