from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor, get_actor, get_tenant_session, require_permission
from app.core import csvio
from app.modules.accounting.banking import BankingService
from app.modules.accounting.models import StatementLineStatus
from app.modules.accounting.schemas import (
    MatchRequest,
    PaymentAccountsUpdate,
    StatementEntryRequest,
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


@router.put("/settings/payment-accounts", response_model=AccountingSettingsOut)
async def set_payment_accounts(
    payload: PaymentAccountsUpdate,
    actor: Actor = Depends(write),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await AccountingService(session, actor.workspace_id).set_payment_accounts(payload.payment_accounts)


# ---------------------------------------------------------------- year end


@router.get("/year-end")
async def year_end_status(actor: Actor = Depends(get_actor), session: AsyncSession = Depends(get_tenant_session)):
    service = AccountingService(session, actor.workspace_id)
    settings = await service.get_settings()
    closed = await service.closed_years()
    await session.commit()
    return {"closed_years": closed, "lock_date": settings.lock_date, "fiscal_year_start_month": settings.fiscal_year_start_month}


@router.post("/year-end/{year}/close")
async def close_year(year: int, actor: Actor = Depends(require_permission("*")), session: AsyncSession = Depends(get_tenant_session)):
    return await AccountingService(session, actor.workspace_id).close_year(year)


@router.post("/year-end/{year}/reopen")
async def reopen_year(year: int, actor: Actor = Depends(require_permission("*")), session: AsyncSession = Depends(get_tenant_session)):
    return await AccountingService(session, actor.workspace_id).reopen_year(year)


# --------------------------------------------------------------------- VAT


async def _vat(actor: Actor, session: AsyncSession, start: date, end: date) -> dict:
    """Output VAT from Sales less input VAT from Purchasing, each through its
    own module's service (and only if the workspace has that module)."""
    report: dict = {"start": start, "end": end, "sales": None, "purchases": None}
    output = input_vat = 0
    if "sales" in actor.features:
        from app.modules.sales.service import SalesService

        report["sales"] = await SalesService(session, actor.workspace_id).vat_output(start, end)
        output = report["sales"]["output_vat"]
    if "purchasing" in actor.features:
        from app.modules.purchasing.service import PurchasingService

        report["purchases"] = await PurchasingService(session, actor.workspace_id).vat_input(start, end)
        input_vat = report["purchases"]["input_vat"]
    report.update(output_vat=output, input_vat=input_vat, net_vat=output - input_vat)
    return report


def _month_bounds(start: date | None, end: date | None) -> tuple[date, date]:
    """Defaults to last month — the return that's due now (by the 20th)."""
    if start and end:
        return start, end
    first_this_month = date.today().replace(day=1)
    last_month_end = first_this_month - timedelta(days=1)
    return last_month_end.replace(day=1), last_month_end


@router.get("/reports/vat")
async def vat_return(
    start: date | None = None,
    end: date | None = None,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await _vat(actor, session, *_month_bounds(start, end))


@router.get("/reports/vat/csv")
async def vat_return_csv(
    start: date | None = None,
    end: date | None = None,
    actor: Actor = Depends(get_actor),
    session: AsyncSession = Depends(get_tenant_session),
):
    start, end = _month_bounds(start, end)
    report = await _vat(actor, session, start, end)
    rows: list[list] = [["SALES (output VAT)", "", "", ""]]
    for r in (report["sales"] or {}).get("by_rate", []):
        rows.append([f"Sales at {r['rate'] * 100:.0f}%", "", r["taxable"], r["vat"]])
    if report["sales"]:
        rows.append(["Less credit notes", "", -report["sales"]["credit_notes_taxable"], -report["sales"]["credit_notes_vat"]])
    rows.append(["Output VAT", "", "", report["output_vat"]])
    rows.append(["", "", "", ""])
    rows.append(["PURCHASES (input VAT)", "Supplier PIN", "", ""])
    for b in (report["purchases"] or {}).get("bills", []):
        rows.append([f"{b['bill_no']} {b['vendor']} {b['vendor_reference']}".strip(), b["vendor_pin"], b["taxable"], b["vat"]])
    rows.append(["Input VAT", "", "", report["input_vat"]])
    rows.append(["", "", "", ""])
    rows.append(["NET VAT PAYABLE" if report["net_vat"] >= 0 else "VAT CREDIT CARRIED FORWARD", "", "", abs(report["net_vat"])])
    return csvio.csv_response(f"vat-return-{start.isoformat()}-{end.isoformat()}.csv", ["Item", "PIN", "Taxable amount", "VAT"], rows)


# ----------------------------------------------------- bank reconciliation


@router.get("/bank/accounts")
async def bank_accounts(actor: Actor = Depends(get_actor), session: AsyncSession = Depends(get_tenant_session)):
    return await BankingService(session, actor.workspace_id).accounts()


@router.get("/bank/{account_id}")
async def bank_workspace(account_id: str, actor: Actor = Depends(get_actor), session: AsyncSession = Depends(get_tenant_session)):
    return await BankingService(session, actor.workspace_id).workspace(account_id)


@router.post("/bank/{account_id}/import")
async def import_statement(
    account_id: str, file: UploadFile, actor: Actor = Depends(write), session: AsyncSession = Depends(get_tenant_session)
):
    return await BankingService(session, actor.workspace_id).import_statement(account_id, file)


@router.get("/bank-statement-template")
async def statement_template(actor: Actor = Depends(get_actor)):
    return csvio.csv_response(
        "statement-template.csv",
        ["date", "description", "reference", "amount"],
        [["2026-03-01", "Deposit - Acme Builders", "FT26060ABC", "54218.40"], ["2026-03-02", "Bank charges", "", "-350.00"]],
    )


@router.post("/bank/{account_id}/auto-match")
async def auto_match(account_id: str, actor: Actor = Depends(write), session: AsyncSession = Depends(get_tenant_session)):
    return {"matched": await BankingService(session, actor.workspace_id).auto_match(account_id)}


@router.post("/bank/lines/{line_id}/match")
async def match_line(
    line_id: str, payload: MatchRequest, actor: Actor = Depends(write), session: AsyncSession = Depends(get_tenant_session)
):
    await BankingService(session, actor.workspace_id).match(line_id, payload.journal_line_id)
    return {"ok": True}


@router.post("/bank/lines/{line_id}/unmatch")
async def unmatch_line(line_id: str, actor: Actor = Depends(write), session: AsyncSession = Depends(get_tenant_session)):
    await BankingService(session, actor.workspace_id).set_status(line_id, StatementLineStatus.unmatched)
    return {"ok": True}


@router.post("/bank/lines/{line_id}/ignore")
async def ignore_line(line_id: str, actor: Actor = Depends(write), session: AsyncSession = Depends(get_tenant_session)):
    await BankingService(session, actor.workspace_id).set_status(line_id, StatementLineStatus.ignored)
    return {"ok": True}


@router.post("/bank/lines/{line_id}/create-entry")
async def create_entry_from_line(
    line_id: str, payload: StatementEntryRequest, actor: Actor = Depends(write), session: AsyncSession = Depends(get_tenant_session)
):
    await BankingService(session, actor.workspace_id).create_entry(line_id, payload.account_id, payload.memo)
    return {"ok": True}
