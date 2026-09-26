from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor, get_actor, get_tenant_session, require_permission
from app.modules.accounting.schemas import (
    AccountCreate,
    AccountingSettingsOut,
    AccountingSettingsUpdate,
    AccountOut,
    AccountUpdate,
    BudgetSet,
    JournalEntryOut,
    ManualJournalEntryCreate,
    ReverseEntryRequest,
    TrialBalanceRow,
)
from app.modules.accounting.service import AccountingService, JournalLineInput

router = APIRouter(prefix="/api/v1/accounting", tags=["accounting"])

write = require_permission("accounting.write")


def _year_start(today: date) -> date:
    return date(today.year, 1, 1)


@router.get("/accounts", response_model=list[AccountOut])
async def list_accounts(
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    accounts = await AccountingService(session, actor.workspace_id).accounts.list()
    return sorted(accounts, key=lambda a: a.code)


@router.post("/accounts", response_model=AccountOut)
async def create_account(
    payload: AccountCreate,
    actor: Actor = Depends(write),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await AccountingService(session, actor.workspace_id).create_account(**payload.model_dump())


@router.patch("/accounts/{account_id}", response_model=AccountOut)
async def update_account(
    account_id: str,
    payload: AccountUpdate,
    actor: Actor = Depends(write),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await AccountingService(session, actor.workspace_id).update_account(
        account_id, payload.model_dump(exclude_unset=True)
    )


@router.get("/trial-balance", response_model=list[TrialBalanceRow])
async def trial_balance(
    as_of: date | None = None,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await AccountingService(session, actor.workspace_id).trial_balance(as_of)


@router.get("/reports/profit-and-loss")
async def profit_and_loss(
    start: date | None = None,
    end: date | None = None,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    end = end or date.today()
    start = start or _year_start(end)
    return await AccountingService(session, actor.workspace_id).profit_and_loss(start, end)


@router.get("/reports/balance-sheet")
async def balance_sheet(
    as_of: date | None = None,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await AccountingService(session, actor.workspace_id).balance_sheet(as_of or date.today())


@router.get("/reports/general-ledger/{account_id}")
async def general_ledger(
    account_id: str,
    start: date | None = None,
    end: date | None = None,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    end = end or date.today()
    start = start or _year_start(end)
    return await AccountingService(session, actor.workspace_id).general_ledger(account_id, start, end)


@router.get("/reports/monthly-trend")
async def monthly_trend(
    months: int = Query(12, ge=1, le=36),
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await AccountingService(session, actor.workspace_id).monthly_trend(months)


@router.get("/reports/budget-vs-actual")
async def budget_vs_actual(
    year: int | None = None,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await AccountingService(session, actor.workspace_id).budget_vs_actual(year or date.today().year)


@router.put("/budgets")
async def set_budget(
    payload: BudgetSet,
    actor: Actor = Depends(write),
    session: AsyncSession = Depends(get_tenant_session),
):
    await AccountingService(session, actor.workspace_id).set_budget(
        payload.account_id, payload.year, payload.monthly_amounts
    )
    return {"ok": True}


@router.get("/journal-entries")
async def list_journal_entries(
    start: date | None = None,
    end: date | None = None,
    source_type: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await AccountingService(session, actor.workspace_id).list_entries(
        start=start, end=end, source_type=source_type, limit=limit, offset=offset
    )


@router.post("/journal-entries", response_model=JournalEntryOut)
async def post_manual_journal_entry(
    payload: ManualJournalEntryCreate,
    actor: Actor = Depends(write),
    session: AsyncSession = Depends(get_tenant_session),
):
    service = AccountingService(session, actor.workspace_id)
    entry = await service.post_journal_entry(
        entry_date=payload.date,
        memo=payload.memo,
        source_type="manual",
        source_id=actor.user_id,
        lines=[
            JournalLineInput(l.account_id, debit=l.debit, credit=l.credit, memo=l.memo)
            for l in payload.lines
        ],
    )
    await session.commit()
    await session.refresh(entry)
    return entry


@router.post("/journal-entries/{entry_id}/reverse", response_model=JournalEntryOut)
async def reverse_journal_entry(
    entry_id: str,
    payload: ReverseEntryRequest,
    actor: Actor = Depends(write),
    session: AsyncSession = Depends(get_tenant_session),
):
    service = AccountingService(session, actor.workspace_id)
    reversal = await service.reverse_entry(entry_id, payload.date, payload.memo)
    await session.commit()
    await session.refresh(reversal)
    return reversal


@router.get("/settings", response_model=AccountingSettingsOut)
async def get_settings(
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    service = AccountingService(session, actor.workspace_id)
    settings = await service.get_settings()
    await session.commit()
    return settings


@router.put("/settings", response_model=AccountingSettingsOut)
async def update_settings(
    payload: AccountingSettingsUpdate,
    actor: Actor = Depends(require_permission("*")),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await AccountingService(session, actor.workspace_id).update_settings(
        lock_date=payload.lock_date, fiscal_year_start_month=payload.fiscal_year_start_month
    )
