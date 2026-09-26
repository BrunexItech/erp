from __future__ import annotations

import enum
from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import TenantModel


class AccountType(str, enum.Enum):
    asset = "asset"
    liability = "liability"
    equity = "equity"
    revenue = "revenue"
    expense = "expense"


class Account(TenantModel):
    __tablename__ = "accounts"

    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[AccountType]
    is_system: Mapped[bool] = mapped_column(default=False)  # protects auto-posted accounts
    # Finer reporting group inside `type`: "bank", "current_asset", "fixed_asset",
    # "cost_of_sales", "operating_expense", "other_income", ... — drives how the
    # P&L / balance sheet split a type into sections. Free-form on purpose so a
    # workspace can add its own groups without a migration.
    subtype: Mapped[str] = mapped_column(String(32), default="")
    description: Mapped[str] = mapped_column(String(500), default="")
    is_active: Mapped[bool] = mapped_column(default=True)

    __table_args__ = (UniqueConstraint("workspace_id", "code", name="uq_account_code"),)


class JournalEntry(TenantModel):
    __tablename__ = "journal_entries"

    entry_no: Mapped[str] = mapped_column(String(32), default="", index=True)
    date: Mapped[date]
    memo: Mapped[str] = mapped_column(String(500), default="")
    source_type: Mapped[str] = mapped_column(String(64))  # "sales_invoice" | "goods_receipt" | "payment" | "manual"
    source_id: Mapped[str] = mapped_column(String(36))
    posted: Mapped[bool] = mapped_column(default=True)  # MVP: post immediately, no draft workflow
    # Posted entries are never edited or deleted — a correction is a mirror-image
    # reversing entry, linked both ways so the audit trail shows what undid what.
    reversal_of_id: Mapped[str | None] = mapped_column(
        ForeignKey("journal_entries.id"), nullable=True
    )
    reversed_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class JournalLine(TenantModel):
    __tablename__ = "journal_lines"

    entry_id: Mapped[str] = mapped_column(ForeignKey("journal_entries.id"), index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True)
    debit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    credit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    memo: Mapped[str] = mapped_column(String(500), default="")

    __table_args__ = (
        CheckConstraint("debit = 0 OR credit = 0", name="ck_journal_line_debit_xor_credit"),
    )


class AccountingSettings(TenantModel):
    """One row per workspace. `lock_date` closes the books: no journal entry
    dated on or before it can be posted (Sage's "period locked" guard), so
    reports already sent to the auditor/KRA can't silently change."""

    __tablename__ = "accounting_settings"

    lock_date: Mapped[date | None] = mapped_column(nullable=True)
    fiscal_year_start_month: Mapped[int] = mapped_column(default=1)

    __table_args__ = (UniqueConstraint("workspace_id", name="uq_accounting_settings_ws"),)


class BudgetLine(TenantModel):
    """Monthly budget per account — compared against actuals in the
    budget-vs-actual report."""

    __tablename__ = "budget_lines"

    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True)
    year: Mapped[int]
    month: Mapped[int]
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)

    __table_args__ = (
        UniqueConstraint("workspace_id", "account_id", "year", "month", name="uq_budget_line"),
    )


# System account codes — seeded per workspace on creation (WorkspaceCreated event),
# referenced by key from posting.py so auto-postings always have a target without
# requiring the SME to configure a chart of accounts before their first sale.
SYSTEM_ACCOUNTS: dict[str, tuple[str, str, AccountType]] = {
    "CASH": ("1000", "Cash & Bank", AccountType.asset),
    "AR": ("1100", "Accounts Receivable", AccountType.asset),
    "INVENTORY": ("1200", "Inventory", AccountType.asset),
    "INPUT_VAT": ("1300", "Input VAT Recoverable", AccountType.asset),
    "FIXED_ASSETS": ("1500", "Property, Plant & Equipment", AccountType.asset),
    "ACCUM_DEPRECIATION": ("1590", "Accumulated Depreciation", AccountType.asset),
    "AP": ("2100", "Accounts Payable", AccountType.liability),
    "TAX_PAYABLE": ("2200", "Output VAT Payable", AccountType.liability),
    "PAYE_PAYABLE": ("2310", "PAYE Payable", AccountType.liability),
    "NSSF_PAYABLE": ("2320", "NSSF Payable", AccountType.liability),
    "SHIF_PAYABLE": ("2330", "SHIF Payable", AccountType.liability),
    "HOUSING_LEVY_PAYABLE": ("2340", "Housing Levy Payable", AccountType.liability),
    "NITA_PAYABLE": ("2350", "NITA Levy Payable", AccountType.liability),
    "OTHER_DEDUCTIONS_PAYABLE": ("2360", "Other Payroll Deductions Payable", AccountType.liability),
    "NET_PAY_PAYABLE": ("2390", "Net Salaries Payable", AccountType.liability),
    "OPENING_EQUITY": ("3000", "Opening Balance Equity", AccountType.equity),
    "RETAINED_EARNINGS": ("3100", "Retained Earnings", AccountType.equity),
    "REVENUE": ("4000", "Sales Revenue", AccountType.revenue),
    "SALES_RETURNS": ("4100", "Sales Returns & Allowances", AccountType.revenue),
    "OTHER_INCOME": ("4900", "Other Income", AccountType.revenue),
    "GAIN_ON_DISPOSAL": ("4910", "Gain/Loss on Asset Disposal", AccountType.revenue),
    "COGS": ("5000", "Cost of Goods Sold", AccountType.expense),
    "SHRINKAGE": ("5100", "Inventory Adjustments & Shrinkage", AccountType.expense),
    "PURCHASE_PRICE_VARIANCE": ("5150", "Purchase Price Variance", AccountType.expense),
    "PRODUCTION_COSTS_APPLIED": ("5200", "Production Labour & Overhead Applied", AccountType.expense),
    "GENERAL_EXPENSE": ("6000", "General & Administrative Expenses", AccountType.expense),
    "SALARIES_EXPENSE": ("6100", "Salaries & Wages", AccountType.expense),
    "EMPLOYER_STATUTORY_EXPENSE": ("6110", "Employer Statutory Contributions", AccountType.expense),
    "DEPRECIATION_EXPENSE": ("6500", "Depreciation Expense", AccountType.expense),
}

# Reporting group for each system account (see Account.subtype).
SYSTEM_ACCOUNT_SUBTYPES: dict[str, str] = {
    "CASH": "bank",
    "AR": "current_asset",
    "INVENTORY": "current_asset",
    "INPUT_VAT": "current_asset",
    "FIXED_ASSETS": "fixed_asset",
    "ACCUM_DEPRECIATION": "fixed_asset",
    "AP": "current_liability",
    "TAX_PAYABLE": "current_liability",
    "PAYE_PAYABLE": "current_liability",
    "NSSF_PAYABLE": "current_liability",
    "SHIF_PAYABLE": "current_liability",
    "HOUSING_LEVY_PAYABLE": "current_liability",
    "NITA_PAYABLE": "current_liability",
    "OTHER_DEDUCTIONS_PAYABLE": "current_liability",
    "NET_PAY_PAYABLE": "current_liability",
    "OPENING_EQUITY": "equity",
    "RETAINED_EARNINGS": "equity",
    "REVENUE": "operating_revenue",
    "SALES_RETURNS": "operating_revenue",
    "OTHER_INCOME": "other_income",
    "GAIN_ON_DISPOSAL": "other_income",
    "COGS": "cost_of_sales",
    "SHRINKAGE": "cost_of_sales",
    "PURCHASE_PRICE_VARIANCE": "cost_of_sales",
    "PRODUCTION_COSTS_APPLIED": "cost_of_sales",
    "GENERAL_EXPENSE": "operating_expense",
    "SALARIES_EXPENSE": "operating_expense",
    "EMPLOYER_STATUTORY_EXPENSE": "operating_expense",
    "DEPRECIATION_EXPENSE": "operating_expense",
}
