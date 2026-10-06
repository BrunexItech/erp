"""Bank and M-Pesa reconciliation.

Import the statement the bank (or Safaricom) gives you, and pair every line
with the ledger entry it corresponds to. What's left unpaired on either side
is exactly what needs attention: a deposit nobody recorded, a bank charge, a
payment entered twice, a cheque that hasn't cleared.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import csvio
from app.core.db import TenantRepository
from app.modules.accounting.models import (
    Account,
    AccountType,
    BankStatementLine,
    JournalEntry,
    JournalLine,
    StatementLineStatus,
)
from app.modules.accounting.service import AccountingService, JournalLineInput

ZERO = Decimal("0")
DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d %b %Y", "%d-%b-%Y", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S")
MATCH_WINDOW_DAYS = 5


def parse_date(value: str) -> date:
    value = value.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"date '{value}' isn't in a recognised format (try 2026-03-31 or 31/03/2026)")


def _amount(row: dict[str, str]) -> Decimal:
    """Statements come as one signed "amount" column, or as separate
    money-in / money-out columns (bank: credit/debit; M-Pesa: paid in/withdrawn)."""
    def number(*names: str) -> Decimal | None:
        for name in names:
            text = (row.get(name) or "").replace(",", "").replace("KES", "").strip()
            if text and text not in ("-", "0", "0.00"):
                negative = text.startswith("(") or text.startswith("-")
                value = Decimal(text.strip("()-+ "))
                return -value if negative else value
        return None

    signed = number("amount")
    if signed is not None:
        return signed
    money_in = number("credit", "paid_in", "deposit", "money_in", "deposits")
    money_out = number("debit", "withdrawn", "withdrawal", "money_out", "withdrawals")
    if money_in is None and money_out is None:
        raise ValueError("no amount found (expected an 'amount' column, or 'credit'/'debit', or 'paid in'/'withdrawn')")
    return abs(money_in or ZERO) - abs(money_out or ZERO)


class BankingService:
    def __init__(self, session: AsyncSession, workspace_id: str):
        self.session = session
        self.workspace_id = workspace_id
        self.accounting = AccountingService(session, workspace_id)
        self.lines = TenantRepository(session, workspace_id, BankStatementLine)

    async def _bank_account(self, account_id: str) -> Account:
        account = await self.accounting.accounts.get(account_id)
        if account is None or account.type != AccountType.asset:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "bank account not found")
        return account

    async def accounts(self) -> list[dict]:
        """Every cash/bank/M-Pesa ledger account with its book balance and
        how much of its statement is still unreconciled."""
        await self.accounting.seed_default_accounts()
        accounts = [a for a in await self.accounting.accounts.list(Account.subtype == "bank") if a.is_active]
        sums = await self.accounting._sums_by_account()
        pending = dict(
            (
                await self.session.execute(
                    select(BankStatementLine.account_id, func.count(BankStatementLine.id))
                    .where(BankStatementLine.workspace_id == self.workspace_id, BankStatementLine.status == StatementLineStatus.unmatched)
                    .group_by(BankStatementLine.account_id)
                )
            ).all()
        )
        last = dict(
            (
                await self.session.execute(
                    select(BankStatementLine.account_id, func.max(BankStatementLine.date))
                    .where(BankStatementLine.workspace_id == self.workspace_id)
                    .group_by(BankStatementLine.account_id)
                )
            ).all()
        )
        await self.session.commit()
        return [
            {
                "id": a.id, "code": a.code, "name": a.name,
                "book_balance": sums.get(a.id, (ZERO, ZERO))[0] - sums.get(a.id, (ZERO, ZERO))[1],
                "unmatched": pending.get(a.id, 0), "last_statement_date": last.get(a.id),
            }
            for a in sorted(accounts, key=lambda a: a.code)
        ]

    async def import_statement(self, account_id: str, file: UploadFile) -> dict:
        await self._bank_account(account_id)
        rows = await csvio.read_rows(file, required=["date"])
        report = csvio.ImportReport()
        batch = str(uuid4())
        # Re-importing an overlapping statement must not duplicate lines.
        existing = {
            (l.date, l.amount, l.reference, l.description)
            for l in await self.lines.list(BankStatementLine.account_id == account_id)
        }
        for number, row in rows:
            try:
                when = parse_date(row.get("date") or row.get("completion_time") or "")
                amount = _amount(row)
                if amount == 0:
                    raise ValueError("amount is zero")
                description = (row.get("description") or row.get("details") or row.get("narration") or "")[:500]
                reference = (row.get("reference") or row.get("receipt_no") or row.get("receipt_no.") or row.get("ref") or "")[:64]
                key = (when, amount, reference, description)
                if key in existing:
                    report.skipped += 1
                    continue
                existing.add(key)
                await self.lines.add(
                    BankStatementLine(account_id=account_id, batch_id=batch, date=when, description=description, reference=reference, amount=amount)
                )
                report.created += 1
            except (ValueError, ArithmeticError) as exc:
                report.fail(number, str(exc))
        await self.session.flush()
        matched = await self._auto_match(account_id)
        await self.session.commit()
        return {**report.as_dict(), "auto_matched": matched}

    async def _unreconciled_book_lines(self, account_id: str) -> list[tuple[JournalLine, JournalEntry]]:
        matched_ids = select(BankStatementLine.matched_line_id).where(
            BankStatementLine.workspace_id == self.workspace_id, BankStatementLine.matched_line_id.is_not(None)
        )
        rows = (
            await self.session.execute(
                select(JournalLine, JournalEntry)
                .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
                .where(
                    JournalLine.workspace_id == self.workspace_id,
                    JournalLine.account_id == account_id,
                    JournalLine.id.not_in(matched_ids),
                )
                .order_by(JournalEntry.date)
            )
        ).all()
        return [(line, entry) for line, entry in rows]

    async def _auto_match(self, account_id: str) -> int:
        """Pairs a statement line with a ledger line of the same amount within
        a few days — but only when that pairing is unambiguous. Two candidate
        ledger lines for one statement line are left for a person to decide."""
        statement = await self.lines.list(
            BankStatementLine.account_id == account_id, BankStatementLine.status == StatementLineStatus.unmatched
        )
        by_amount: dict[Decimal, list[tuple[JournalLine, JournalEntry]]] = defaultdict(list)
        for line, entry in await self._unreconciled_book_lines(account_id):
            by_amount[line.debit - line.credit].append((line, entry))

        matched = 0
        for s in sorted(statement, key=lambda l: l.date):
            candidates = [
                (line, entry) for line, entry in by_amount.get(s.amount, [])
                if abs((entry.date - s.date).days) <= MATCH_WINDOW_DAYS
            ]
            if len(candidates) != 1:
                continue
            line, _ = candidates[0]
            s.matched_line_id = line.id
            s.status = StatementLineStatus.matched
            by_amount[s.amount].remove(candidates[0])
            matched += 1
        await self.session.flush()
        return matched

    async def auto_match(self, account_id: str) -> int:
        await self._bank_account(account_id)
        matched = await self._auto_match(account_id)
        await self.session.commit()
        return matched

    async def workspace(self, account_id: str) -> dict:
        """Both sides of a reconciliation: statement lines, and ledger lines
        not yet seen on any statement."""
        account = await self._bank_account(account_id)
        statement = sorted(await self.lines.list(BankStatementLine.account_id == account_id), key=lambda l: (l.date, l.created_at), reverse=True)
        book = await self._unreconciled_book_lines(account_id)
        sums = await self.accounting._sums_by_account()
        debit, credit = sums.get(account_id, (ZERO, ZERO))
        book_balance = debit - credit

        unmatched_statement = sum((l.amount for l in statement if l.status == StatementLineStatus.unmatched), ZERO)
        unmatched_book = sum((line.debit - line.credit for line, _ in book), ZERO)
        return {
            "account": {"id": account.id, "code": account.code, "name": account.name},
            "book_balance": book_balance,
            # What the bank should show once everything outstanding clears.
            "expected_statement_balance": book_balance - unmatched_book + unmatched_statement,
            "unmatched_statement_total": unmatched_statement,
            "unmatched_book_total": unmatched_book,
            "statement_lines": [
                {
                    "id": l.id, "date": l.date, "description": l.description, "reference": l.reference,
                    "amount": l.amount, "status": l.status.value, "matched_line_id": l.matched_line_id,
                }
                for l in statement[:500]
            ],
            "book_lines": [
                {
                    "id": line.id, "date": entry.date, "entry_no": entry.entry_no, "memo": line.memo or entry.memo,
                    "amount": line.debit - line.credit, "source_type": entry.source_type,
                }
                for line, entry in book[-500:]
            ],
        }

    async def _statement_line(self, line_id: str) -> BankStatementLine:
        line = await self.lines.get_for_update(line_id)
        if line is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "statement line not found")
        return line

    async def match(self, statement_line_id: str, journal_line_id: str) -> None:
        s = await self._statement_line(statement_line_id)
        if s.status == StatementLineStatus.matched:
            raise HTTPException(status.HTTP_409_CONFLICT, "that statement line is already matched")
        line = await self.accounting.lines.get(journal_line_id)
        if line is None or line.account_id != s.account_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "ledger line not found on this account")
        if line.debit - line.credit != s.amount:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"amounts differ: statement {s.amount}, ledger {line.debit - line.credit}",
            )
        taken = await self.lines.list(BankStatementLine.matched_line_id == journal_line_id)
        if taken:
            raise HTTPException(status.HTTP_409_CONFLICT, "that ledger line is already matched to another statement line")
        s.matched_line_id = journal_line_id
        s.status = StatementLineStatus.matched
        await self.session.commit()

    async def set_status(self, statement_line_id: str, new_status: StatementLineStatus) -> None:
        """Unmatch (back to unmatched) or ignore (a line that isn't ours to book)."""
        s = await self._statement_line(statement_line_id)
        s.matched_line_id = None
        s.status = new_status
        await self.session.commit()

    async def create_entry(self, statement_line_id: str, offset_account_id: str, memo: str) -> None:
        """For something on the statement that was never recorded — a bank
        charge, interest, a direct deposit: post it and match it in one step."""
        s = await self._statement_line(statement_line_id)
        if s.status == StatementLineStatus.matched:
            raise HTTPException(status.HTTP_409_CONFLICT, "that statement line is already matched")
        amount = abs(s.amount)
        bank = JournalLineInput(s.account_id, debit=amount) if s.amount > 0 else JournalLineInput(s.account_id, credit=amount)
        offset = JournalLineInput(offset_account_id, credit=amount) if s.amount > 0 else JournalLineInput(offset_account_id, debit=amount)
        entry = await self.accounting.post_journal_entry(
            entry_date=s.date,
            memo=memo or s.description or "Bank statement entry",
            source_type="bank_statement",
            source_id=s.id,
            lines=[bank, offset],
        )
        created = await self.accounting.lines.list(JournalLine.entry_id == entry.id, JournalLine.account_id == s.account_id)
        s.matched_line_id = created[0].id
        s.status = StatementLineStatus.matched
        await self.session.commit()

