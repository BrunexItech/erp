from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from app.modules.accounting.models import AccountType


class AccountOut(BaseModel):
    id: str
    code: str
    name: str
    type: AccountType
    subtype: str
    description: str
    is_system: bool
    is_active: bool

    class Config:
        from_attributes = True


class AccountCreate(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=200)
    type: AccountType
    subtype: str = ""
    description: str = ""


class AccountUpdate(BaseModel):
    name: str | None = None
    subtype: str | None = None
    description: str | None = None
    is_active: bool | None = None


class ManualJournalLine(BaseModel):
    account_id: str
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    memo: str = ""


class ManualJournalEntryCreate(BaseModel):
    date: date
    memo: str = ""
    lines: list[ManualJournalLine]


class JournalEntryOut(BaseModel):
    id: str
    entry_no: str
    date: date
    memo: str
    source_type: str
    source_id: str

    class Config:
        from_attributes = True


class ReverseEntryRequest(BaseModel):
    date: date
    memo: str = ""


class TrialBalanceRow(BaseModel):
    account_id: str
    code: str
    name: str
    type: AccountType
    debit: Decimal
    credit: Decimal


class AccountingSettingsOut(BaseModel):
    lock_date: date | None
    fiscal_year_start_month: int
    payment_accounts: dict[str, str] = {}

    class Config:
        from_attributes = True


class AccountingSettingsUpdate(BaseModel):
    lock_date: date | None = None
    fiscal_year_start_month: int | None = None


class PaymentAccountsUpdate(BaseModel):
    """{"mpesa": "<account id>", "bank": "<account id>", ...}; an empty value
    returns that method to its default account."""

    payment_accounts: dict[str, str]


class MatchRequest(BaseModel):
    journal_line_id: str


class StatementEntryRequest(BaseModel):
    account_id: str  # the other side: bank charges, interest income, a customer's AR…
    memo: str = ""


class BudgetSet(BaseModel):
    account_id: str
    year: int
    monthly_amounts: list[Decimal]
