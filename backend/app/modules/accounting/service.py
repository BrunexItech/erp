from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import TenantRepository
from app.core.numbering import next_number
from app.modules.accounting.models import (
    SYSTEM_ACCOUNT_SUBTYPES,
    SYSTEM_ACCOUNTS,
    Account,
    AccountingSettings,
    AccountType,
    BudgetLine,
    JournalEntry,
    JournalLine,
)

CENT = Decimal("0.01")
ZERO = Decimal("0")

# Types whose natural balance is a debit; everything else is credit-natured.
DEBIT_NATURED = {AccountType.asset, AccountType.expense}


def q2(value: Decimal) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class JournalLineInput:
    account_key_or_id: str  # either a SYSTEM_ACCOUNTS key ("AR", "COGS", ...) or an Account.id
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    memo: str = ""


class AccountingService:
    def __init__(self, session: AsyncSession, workspace_id: str):
        self.session = session
        self.workspace_id = workspace_id
        self.accounts = TenantRepository(session, workspace_id, Account)
        self.entries = TenantRepository(session, workspace_id, JournalEntry)
        self.lines = TenantRepository(session, workspace_id, JournalLine)
        self.settings_repo = TenantRepository(session, workspace_id, AccountingSettings)
        self.budgets = TenantRepository(session, workspace_id, BudgetLine)
        self._account_cache: dict[str, Account] = {}

    # ------------------------------------------------------------------ setup

    async def seed_default_accounts(self) -> None:
        """Idempotent: creates any missing system account and back-fills the
        reporting subtype on ones created before subtypes existed. Safe to call
        on every workspace at any time — it's also how workspaces created before
        a new system account was added (e.g. PAYE Payable) pick it up."""
        existing = {a.code: a for a in await self.accounts.list()}
        for key, (code, name, acc_type) in SYSTEM_ACCOUNTS.items():
            subtype = SYSTEM_ACCOUNT_SUBTYPES.get(key, "")
            account = existing.get(code)
            if account is None:
                await self.accounts.add(
                    Account(code=code, name=name, type=acc_type, is_system=True, subtype=subtype)
                )
            elif account.is_system and not account.subtype:
                account.subtype = subtype
        await self.session.flush()

    async def _resolve_account(self, key_or_id: str) -> Account:
        cached = self._account_cache.get(key_or_id)
        if cached is not None:
            return cached

        async def lookup() -> Account | None:
            if key_or_id in SYSTEM_ACCOUNTS:
                code = SYSTEM_ACCOUNTS[key_or_id][0]
                found = await self.accounts.list(Account.code == code)
            else:
                found = await self.accounts.list(Account.id == key_or_id)
            return found[0] if found else None

        account = await lookup()
        if account is None and key_or_id in SYSTEM_ACCOUNTS:
            # A system account added in a later release — seed it on first use
            # instead of failing the business transaction that needs it.
            await self.seed_default_accounts()
            account = await lookup()
        if account is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"account not found for '{key_or_id}'",
            )
        self._account_cache[key_or_id] = account
        return account

    async def get_settings(self) -> AccountingSettings:
        rows = await self.settings_repo.list()
        if rows:
            return rows[0]
        settings = AccountingSettings()
        try:
            async with self.session.begin_nested():
                await self.settings_repo.add(settings)
        except IntegrityError:
            # Two first-ever postings raced to create the row — use the winner's.
            settings = (await self.settings_repo.list())[0]
        return settings

    async def update_settings(self, *, lock_date: date | None, fiscal_year_start_month: int | None) -> AccountingSettings:
        settings = await self.get_settings()
        settings.lock_date = lock_date
        if fiscal_year_start_month is not None:
            if not 1 <= fiscal_year_start_month <= 12:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "fiscal_year_start_month must be 1-12")
            settings.fiscal_year_start_month = fiscal_year_start_month
        await self.session.commit()
        await self.session.refresh(settings)
        return settings

    # --------------------------------------------------------------- accounts

    async def create_account(self, *, code: str, name: str, type: AccountType, subtype: str, description: str) -> Account:
        if await self.accounts.list(Account.code == code):
            raise HTTPException(status.HTTP_409_CONFLICT, f"account code {code} already exists")
        account = Account(code=code, name=name, type=type, subtype=subtype, description=description)
        await self.accounts.add(account)
        await self.session.commit()
        await self.session.refresh(account)
        return account

    async def update_account(self, account_id: str, changes: dict) -> Account:
        account = await self.accounts.get(account_id)
        if account is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "account not found")
        if account.is_system and ("code" in changes or "type" in changes):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "system accounts are posted to automatically — their code and type can't change",
            )
        if account.is_system and changes.get("is_active") is False:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "system accounts can't be deactivated")
        for field, value in changes.items():
            setattr(account, field, value)
        await self.session.commit()
        await self.session.refresh(account)
        return account

    # ---------------------------------------------------------------- posting

    async def post_journal_entry(
        self,
        *,
        entry_date: date,
        memo: str,
        source_type: str,
        source_id: str,
        lines: list[JournalLineInput],
        reversal_of_id: str | None = None,
    ) -> JournalEntry:
        lines = [
            JournalLineInput(l.account_key_or_id, q2(l.debit), q2(l.credit), l.memo)
            for l in lines
            if l.debit or l.credit
        ]
        for line in lines:
            if line.debit < 0 or line.credit < 0:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "journal amounts must be positive")
            if line.debit and line.credit:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "a journal line cannot have both a debit and a credit",
                )

        total_debit = sum((l.debit for l in lines), ZERO)
        total_credit = sum((l.credit for l in lines), ZERO)
        if total_debit != total_credit:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"journal entry does not balance: debit={total_debit} credit={total_credit} "
                f"(source={source_type}:{source_id})",
            )
        if total_debit == 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "journal entry has zero total")

        settings = await self.get_settings()
        if settings.lock_date is not None and entry_date <= settings.lock_date:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"the books are locked through {settings.lock_date.isoformat()} — "
                f"post this entry in an open period",
            )

        entry = JournalEntry(
            workspace_id=self.workspace_id,
            entry_no=await next_number(self.session, self.workspace_id, "journal"),
            date=entry_date,
            memo=memo,
            source_type=source_type,
            source_id=source_id,
            reversal_of_id=reversal_of_id,
        )
        self.session.add(entry)
        await self.session.flush()

        for line in lines:
            account = await self._resolve_account(line.account_key_or_id)
            if not account.is_active:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"account {account.code} is inactive")
            self.session.add(
                JournalLine(
                    workspace_id=self.workspace_id,
                    entry_id=entry.id,
                    account_id=account.id,
                    debit=line.debit,
                    credit=line.credit,
                    memo=line.memo,
                )
            )
        await self.session.flush()
        return entry

    async def reverse_entry(self, entry_id: str, reversal_date: date, memo: str = "") -> JournalEntry:
        entry = await self.entries.get_for_update(entry_id)
        if entry is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "journal entry not found")
        if entry.reversed_by_id:
            raise HTTPException(status.HTTP_409_CONFLICT, "entry has already been reversed")
        if entry.reversal_of_id:
            raise HTTPException(status.HTTP_409_CONFLICT, "a reversing entry can't itself be reversed")

        original_lines = await self.lines.list(JournalLine.entry_id == entry.id)
        reversal = await self.post_journal_entry(
            entry_date=reversal_date,
            memo=memo or f"Reversal of {entry.entry_no or entry.id[:8]}",
            source_type="reversal",
            source_id=entry.id,
            reversal_of_id=entry.id,
            lines=[
                JournalLineInput(l.account_id, debit=l.credit, credit=l.debit, memo=l.memo)
                for l in original_lines
            ],
        )
        entry.reversed_by_id = reversal.id
        await self.session.flush()
        return reversal

    async def reverse_by_source(self, source_type: str, source_id: str, reversal_date: date, memo: str = "") -> int:
        """Reverses every not-yet-reversed entry a document produced (e.g. a
        voided invoice's revenue posting). Returns how many were reversed."""
        entries = await self.entries.list(
            JournalEntry.source_type == source_type,
            JournalEntry.source_id == source_id,
            JournalEntry.reversed_by_id.is_(None),
        )
        for entry in entries:
            await self.reverse_entry(entry.id, reversal_date, memo)
        return len(entries)

    # --------------------------------------------------------------- balances

    async def _sums_by_account(
        self, start: date | None = None, end: date | None = None
    ) -> dict[str, tuple[Decimal, Decimal]]:
        stmt = (
            select(
                JournalLine.account_id,
                func.coalesce(func.sum(JournalLine.debit), 0),
                func.coalesce(func.sum(JournalLine.credit), 0),
            )
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .where(JournalLine.workspace_id == self.workspace_id)
            .group_by(JournalLine.account_id)
        )
        if start is not None:
            stmt = stmt.where(JournalEntry.date >= start)
        if end is not None:
            stmt = stmt.where(JournalEntry.date <= end)
        rows = (await self.session.execute(stmt)).all()
        return {account_id: (Decimal(d), Decimal(c)) for account_id, d, c in rows}

    @staticmethod
    def natural_balance(account: Account, debit: Decimal, credit: Decimal) -> Decimal:
        return debit - credit if account.type in DEBIT_NATURED else credit - debit

    async def account_balance(self, account_id: str) -> Decimal:
        """Signed debit-minus-credit balance (kept for existing callers)."""
        stmt = select(
            func.coalesce(func.sum(JournalLine.debit), 0)
            - func.coalesce(func.sum(JournalLine.credit), 0)
        ).where(JournalLine.workspace_id == self.workspace_id, JournalLine.account_id == account_id)
        return Decimal((await self.session.execute(stmt)).scalar_one())

    async def balance_for_key(self, key: str, as_of: date | None = None) -> Decimal:
        """Natural-sign balance of a system account (e.g. "CASH")."""
        account = await self._resolve_account(key)
        sums = await self._sums_by_account(end=as_of)
        debit, credit = sums.get(account.id, (ZERO, ZERO))
        return self.natural_balance(account, debit, credit)

    # ---------------------------------------------------------------- reports

    async def trial_balance(self, as_of: date | None = None) -> list[dict]:
        accounts = sorted(await self.accounts.list(), key=lambda a: a.code)
        sums = await self._sums_by_account(end=as_of)
        rows = []
        for account in accounts:
            debit, credit = sums.get(account.id, (ZERO, ZERO))
            balance = debit - credit
            rows.append(
                {
                    "account_id": account.id,
                    "code": account.code,
                    "name": account.name,
                    "type": account.type,
                    "debit": balance if balance > 0 else ZERO,
                    "credit": -balance if balance < 0 else ZERO,
                }
            )
        return rows

    async def profit_and_loss(self, start: date, end: date) -> dict:
        accounts = await self.accounts.list(
            Account.type.in_([AccountType.revenue, AccountType.expense])
        )
        sums = await self._sums_by_account(start=start, end=end)

        sections: dict[str, list[dict]] = defaultdict(list)
        for account in sorted(accounts, key=lambda a: a.code):
            debit, credit = sums.get(account.id, (ZERO, ZERO))
            amount = self.natural_balance(account, debit, credit)
            if amount == 0:
                continue
            if account.type == AccountType.revenue:
                section = "other_income" if account.subtype == "other_income" else "revenue"
            else:
                section = "cost_of_sales" if account.subtype == "cost_of_sales" else "operating_expenses"
            sections[section].append(
                {"account_id": account.id, "code": account.code, "name": account.name, "amount": q2(amount)}
            )

        def total(section: str) -> Decimal:
            return sum((r["amount"] for r in sections[section]), ZERO)

        revenue = total("revenue")
        cost_of_sales = total("cost_of_sales")
        gross_profit = revenue - cost_of_sales
        operating_expenses = total("operating_expenses")
        operating_profit = gross_profit - operating_expenses
        other_income = total("other_income")
        return {
            "start": start,
            "end": end,
            "revenue": sections["revenue"],
            "cost_of_sales": sections["cost_of_sales"],
            "operating_expenses": sections["operating_expenses"],
            "other_income": sections["other_income"],
            "total_revenue": revenue,
            "total_cost_of_sales": cost_of_sales,
            "gross_profit": gross_profit,
            "gross_margin_pct": q2(gross_profit / revenue * 100) if revenue else ZERO,
            "total_operating_expenses": operating_expenses,
            "operating_profit": operating_profit,
            "total_other_income": other_income,
            "net_profit": operating_profit + other_income,
        }

    async def balance_sheet(self, as_of: date) -> dict:
        accounts = sorted(await self.accounts.list(), key=lambda a: a.code)
        sums = await self._sums_by_account(end=as_of)

        groups: dict[str, list[dict]] = defaultdict(list)
        earnings = ZERO
        for account in accounts:
            debit, credit = sums.get(account.id, (ZERO, ZERO))
            amount = self.natural_balance(account, debit, credit)
            if account.type == AccountType.revenue:
                earnings += amount
                continue
            if account.type == AccountType.expense:
                earnings -= amount
                continue
            if amount == 0:
                continue
            if account.type == AccountType.asset:
                group = "fixed_assets" if account.subtype == "fixed_asset" else "current_assets"
            elif account.type == AccountType.liability:
                group = "long_term_liabilities" if account.subtype == "long_term_liability" else "current_liabilities"
            else:
                group = "equity"
            groups[group].append(
                {"account_id": account.id, "code": account.code, "name": account.name, "amount": q2(amount)}
            )

        # There's no year-end close yet, so every period's profit still sits in
        # the P&L accounts — surface it as an equity line so the sheet balances.
        if earnings:
            groups["equity"].append(
                {"account_id": None, "code": "", "name": "Current & prior period earnings", "amount": q2(earnings)}
            )

        def total(group: str) -> Decimal:
            return sum((r["amount"] for r in groups[group]), ZERO)

        total_assets = total("current_assets") + total("fixed_assets")
        total_liabilities = total("current_liabilities") + total("long_term_liabilities")
        total_equity = total("equity")
        return {
            "as_of": as_of,
            "current_assets": groups["current_assets"],
            "fixed_assets": groups["fixed_assets"],
            "current_liabilities": groups["current_liabilities"],
            "long_term_liabilities": groups["long_term_liabilities"],
            "equity": groups["equity"],
            "total_assets": total_assets,
            "total_liabilities": total_liabilities,
            "total_equity": total_equity,
            "balanced": total_assets == total_liabilities + total_equity,
        }

    async def general_ledger(self, account_id: str, start: date, end: date) -> dict:
        account = await self.accounts.get(account_id)
        if account is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "account not found")

        opening_stmt = (
            select(
                func.coalesce(func.sum(JournalLine.debit), 0),
                func.coalesce(func.sum(JournalLine.credit), 0),
            )
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .where(
                JournalLine.workspace_id == self.workspace_id,
                JournalLine.account_id == account_id,
                JournalEntry.date < start,
            )
        )
        od, oc = (await self.session.execute(opening_stmt)).one()
        opening = self.natural_balance(account, Decimal(od), Decimal(oc))

        stmt = (
            select(JournalLine, JournalEntry)
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .where(
                JournalLine.workspace_id == self.workspace_id,
                JournalLine.account_id == account_id,
                JournalEntry.date >= start,
                JournalEntry.date <= end,
            )
            .order_by(JournalEntry.date, JournalEntry.created_at, JournalEntry.entry_no)
        )
        running = opening
        rows = []
        for line, entry in (await self.session.execute(stmt)).all():
            running += self.natural_balance(account, line.debit, line.credit)
            rows.append(
                {
                    "entry_id": entry.id,
                    "entry_no": entry.entry_no,
                    "date": entry.date,
                    "memo": line.memo or entry.memo,
                    "source_type": entry.source_type,
                    "debit": line.debit,
                    "credit": line.credit,
                    "balance": running,
                }
            )
        return {
            "account_id": account.id,
            "code": account.code,
            "name": account.name,
            "type": account.type,
            "start": start,
            "end": end,
            "opening_balance": opening,
            "closing_balance": running,
            "lines": rows,
        }

    async def list_entries(
        self,
        *,
        start: date | None = None,
        end: date | None = None,
        source_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        stmt = self.entries.query()
        if start is not None:
            stmt = stmt.where(JournalEntry.date >= start)
        if end is not None:
            stmt = stmt.where(JournalEntry.date <= end)
        if source_type:
            stmt = stmt.where(JournalEntry.source_type == source_type)
        stmt = stmt.order_by(JournalEntry.date.desc(), JournalEntry.created_at.desc()).limit(limit).offset(offset)
        entries = (await self.session.execute(stmt)).scalars().all()
        if not entries:
            return []

        accounts = {a.id: a for a in await self.accounts.list()}
        lines = await self.lines.list(JournalLine.entry_id.in_([e.id for e in entries]))
        by_entry: dict[str, list[dict]] = defaultdict(list)
        for line in lines:
            account = accounts.get(line.account_id)
            by_entry[line.entry_id].append(
                {
                    "account_id": line.account_id,
                    "account_code": account.code if account else "",
                    "account_name": account.name if account else "",
                    "debit": line.debit,
                    "credit": line.credit,
                    "memo": line.memo,
                }
            )
        return [
            {
                "id": e.id,
                "entry_no": e.entry_no,
                "date": e.date,
                "memo": e.memo,
                "source_type": e.source_type,
                "source_id": e.source_id,
                "reversal_of_id": e.reversal_of_id,
                "reversed_by_id": e.reversed_by_id,
                "total": sum((l["debit"] for l in by_entry[e.id]), ZERO),
                "lines": by_entry[e.id],
            }
            for e in entries
        ]

    # ---------------------------------------------------------------- budgets

    async def set_budget(self, account_id: str, year: int, monthly_amounts: list[Decimal]) -> None:
        if len(monthly_amounts) != 12:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "provide exactly 12 monthly amounts")
        if await self.accounts.get(account_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "account not found")
        existing = {
            b.month: b
            for b in await self.budgets.list(BudgetLine.account_id == account_id, BudgetLine.year == year)
        }
        for month, amount in enumerate(monthly_amounts, start=1):
            if month in existing:
                existing[month].amount = amount
            else:
                await self.budgets.add(BudgetLine(account_id=account_id, year=year, month=month, amount=amount))
        await self.session.commit()

    async def budget_vs_actual(self, year: int) -> list[dict]:
        budgets = await self.budgets.list(BudgetLine.year == year)
        if not budgets:
            return []
        by_account: dict[str, dict[int, Decimal]] = defaultdict(dict)
        for b in budgets:
            by_account[b.account_id][b.month] = b.amount

        stmt = (
            select(
                JournalLine.account_id,
                func.extract("month", JournalEntry.date).label("month"),
                func.coalesce(func.sum(JournalLine.debit), 0),
                func.coalesce(func.sum(JournalLine.credit), 0),
            )
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .where(
                JournalLine.workspace_id == self.workspace_id,
                JournalLine.account_id.in_(list(by_account)),
                func.extract("year", JournalEntry.date) == year,
            )
            .group_by(JournalLine.account_id, "month")
        )
        actual_sums: dict[tuple[str, int], tuple[Decimal, Decimal]] = {
            (acc, int(m)): (Decimal(d), Decimal(c)) for acc, m, d, c in (await self.session.execute(stmt)).all()
        }

        rows = []
        for account_id, months in by_account.items():
            account = await self.accounts.get(account_id)
            if account is None:
                continue
            monthly = []
            for month in range(1, 13):
                d, c = actual_sums.get((account_id, month), (ZERO, ZERO))
                actual = self.natural_balance(account, d, c)
                budget = months.get(month, ZERO)
                monthly.append({"month": month, "budget": budget, "actual": actual, "variance": actual - budget})
            total_budget = sum((m["budget"] for m in monthly), ZERO)
            total_actual = sum((m["actual"] for m in monthly), ZERO)
            rows.append(
                {
                    "account_id": account.id,
                    "code": account.code,
                    "name": account.name,
                    "type": account.type,
                    "months": monthly,
                    "total_budget": total_budget,
                    "total_actual": total_actual,
                    "variance": total_actual - total_budget,
                }
            )
        return sorted(rows, key=lambda r: r["code"])

    # -------------------------------------------------------------- dashboard

    async def monthly_trend(self, months: int = 12, today: date | None = None) -> list[dict]:
        """Revenue / expense / profit per month for the last `months` months —
        feeds the dashboard chart."""
        today = today or date.today()
        year, month = today.year, today.month
        periods = []
        for _ in range(months):
            periods.append((year, month))
            month -= 1
            if month == 0:
                year, month = year - 1, 12
        periods.reverse()
        start = date(periods[0][0], periods[0][1], 1)

        stmt = (
            select(
                Account.type,
                func.extract("year", JournalEntry.date),
                func.extract("month", JournalEntry.date),
                func.coalesce(func.sum(JournalLine.debit), 0),
                func.coalesce(func.sum(JournalLine.credit), 0),
            )
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .join(Account, Account.id == JournalLine.account_id)
            .where(
                JournalLine.workspace_id == self.workspace_id,
                JournalEntry.date >= start,
                Account.type.in_([AccountType.revenue, AccountType.expense]),
            )
            .group_by(Account.type, func.extract("year", JournalEntry.date), func.extract("month", JournalEntry.date))
        )
        data: dict[tuple[int, int], dict[str, Decimal]] = defaultdict(lambda: {"revenue": ZERO, "expenses": ZERO})
        for acc_type, y, m, d, c in (await self.session.execute(stmt)).all():
            d, c = Decimal(d), Decimal(c)
            if acc_type == AccountType.revenue:
                data[(int(y), int(m))]["revenue"] += c - d
            else:
                data[(int(y), int(m))]["expenses"] += d - c
        return [
            {
                "period": f"{y}-{m:02d}",
                "revenue": q2(data[(y, m)]["revenue"]),
                "expenses": q2(data[(y, m)]["expenses"]),
                "profit": q2(data[(y, m)]["revenue"] - data[(y, m)]["expenses"]),
            }
            for y, m in periods
        ]
