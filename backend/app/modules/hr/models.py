from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import TenantModel


class Department(TenantModel):
    __tablename__ = "departments"

    name: Mapped[str] = mapped_column(String(120))
    code: Mapped[str] = mapped_column(String(20), default="")
    head_employee_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_department_name"),)


class EmploymentType(str, enum.Enum):
    permanent = "permanent"
    contract = "contract"
    casual = "casual"
    intern = "intern"


class EmployeeStatus(str, enum.Enum):
    active = "active"
    suspended = "suspended"
    terminated = "terminated"


class PaymentMethod(str, enum.Enum):
    bank = "bank"
    mpesa = "mpesa"
    cash = "cash"


class Employee(TenantModel):
    __tablename__ = "employees"

    employee_no: Mapped[str] = mapped_column(String(32), index=True)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    other_names: Mapped[str] = mapped_column(String(100), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    phone: Mapped[str] = mapped_column(String(32), default="")
    gender: Mapped[str] = mapped_column(String(16), default="")
    date_of_birth: Mapped[date | None] = mapped_column(nullable=True)
    national_id: Mapped[str] = mapped_column(String(32), default="")
    kra_pin: Mapped[str] = mapped_column(String(32), default="")
    nssf_no: Mapped[str] = mapped_column(String(32), default="")
    shif_no: Mapped[str] = mapped_column(String(32), default="")

    department_id: Mapped[str | None] = mapped_column(ForeignKey("departments.id"), nullable=True, index=True)
    job_title: Mapped[str] = mapped_column(String(120), default="")
    employment_type: Mapped[EmploymentType] = mapped_column(default=EmploymentType.permanent)
    status: Mapped[EmployeeStatus] = mapped_column(default=EmployeeStatus.active)
    hire_date: Mapped[date]
    termination_date: Mapped[date | None] = mapped_column(nullable=True)

    basic_salary: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    payment_method: Mapped[PaymentMethod] = mapped_column(default=PaymentMethod.bank)
    bank_name: Mapped[str] = mapped_column(String(120), default="")
    bank_branch: Mapped[str] = mapped_column(String(120), default="")
    bank_account: Mapped[str] = mapped_column(String(64), default="")
    mpesa_phone: Mapped[str] = mapped_column(String(32), default="")

    has_disability_exemption: Mapped[bool] = mapped_column(default=False)
    nssf_exempt: Mapped[bool] = mapped_column(default=False)
    housing_levy_exempt: Mapped[bool] = mapped_column(default=False)

    __table_args__ = (UniqueConstraint("workspace_id", "employee_no", name="uq_employee_no"),)

    @property
    def full_name(self) -> str:
        return " ".join(p for p in [self.first_name, self.other_names, self.last_name] if p)


class PayItemKind(str, enum.Enum):
    earning = "earning"
    deduction = "deduction"


class EmployeePayItem(TenantModel):
    """A recurring monthly allowance or deduction on top of basic salary —
    house allowance, commuter allowance, SACCO, HELB, loan repayment, pension."""

    __tablename__ = "employee_pay_items"

    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), index=True)
    kind: Mapped[PayItemKind]
    name: Mapped[str] = mapped_column(String(120))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    taxable: Mapped[bool] = mapped_column(default=True)  # earnings only
    pre_tax: Mapped[bool] = mapped_column(default=False)  # deductions only: pension relief
    is_active: Mapped[bool] = mapped_column(default=True)


class PayrollRunStatus(str, enum.Enum):
    draft = "draft"
    approved = "approved"
    paid = "paid"


class PayrollRun(TenantModel):
    __tablename__ = "payroll_runs"

    run_no: Mapped[str] = mapped_column(String(32), index=True)
    period_year: Mapped[int]
    period_month: Mapped[int]
    pay_date: Mapped[date]
    status: Mapped[PayrollRunStatus] = mapped_column(default=PayrollRunStatus.draft)
    notes: Mapped[str] = mapped_column(String(500), default="")

    employee_count: Mapped[int] = mapped_column(default=0)
    gross_pay: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    paye: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    nssf_employee: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    nssf_employer: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    shif: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    housing_levy_employee: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    housing_levy_employer: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    nita: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    other_deductions: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    net_pay: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    employer_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)

    approved_at: Mapped[datetime | None] = mapped_column(nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        UniqueConstraint("workspace_id", "period_year", "period_month", name="uq_payroll_run_period"),
    )


class Payslip(TenantModel):
    """Frozen snapshot of one employee's pay for one run. Employee details and
    every computed figure are copied in (not joined at read time) so a payslip
    or P9 reprinted years later shows what was actually paid, even after the
    employee's salary, bank or department changes."""

    __tablename__ = "payslips"

    run_id: Mapped[str] = mapped_column(ForeignKey("payroll_runs.id"), index=True)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), index=True)

    employee_no: Mapped[str] = mapped_column(String(32))
    employee_name: Mapped[str] = mapped_column(String(300))
    kra_pin: Mapped[str] = mapped_column(String(32), default="")
    nssf_no: Mapped[str] = mapped_column(String(32), default="")
    shif_no: Mapped[str] = mapped_column(String(32), default="")
    national_id: Mapped[str] = mapped_column(String(32), default="")
    department: Mapped[str] = mapped_column(String(120), default="")
    job_title: Mapped[str] = mapped_column(String(120), default="")
    payment_method: Mapped[str] = mapped_column(String(16), default="")
    bank_name: Mapped[str] = mapped_column(String(120), default="")
    bank_account: Mapped[str] = mapped_column(String(64), default="")
    mpesa_phone: Mapped[str] = mapped_column(String(32), default="")

    days_worked: Mapped[int] = mapped_column(default=0)
    days_in_period: Mapped[int] = mapped_column(default=0)
    basic_salary: Mapped[Decimal] = mapped_column(Numeric(18, 2))  # after proration
    earnings: Mapped[list] = mapped_column(JSON, default=list)  # [{name, amount, taxable, one_off}]
    deductions: Mapped[list] = mapped_column(JSON, default=list)  # [{name, amount, pre_tax, one_off}]
    adjustments: Mapped[list] = mapped_column(JSON, default=list)  # one-off items for this run only

    gross_pay: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    taxable_earnings: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    nssf_tier1: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    nssf_tier2: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    nssf_employee: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    nssf_employer: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    shif: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    housing_levy_employee: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    housing_levy_employer: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    pension_relief: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    taxable_pay: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    paye_before_relief: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    personal_relief: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    paye: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    other_deductions: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    total_deductions: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    net_pay: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    nita: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    employer_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2))

    __table_args__ = (UniqueConstraint("run_id", "employee_id", name="uq_payslip_run_employee"),)


class LeaveType(TenantModel):
    __tablename__ = "leave_types"

    name: Mapped[str] = mapped_column(String(80))
    days_per_year: Mapped[Decimal] = mapped_column(Numeric(6, 1), default=0)  # 0 = unlimited/unmetered
    is_paid: Mapped[bool] = mapped_column(default=True)
    is_active: Mapped[bool] = mapped_column(default=True)

    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_leave_type_name"),)


# Seeded per workspace on first use — minimums under the Employment Act 2007.
DEFAULT_LEAVE_TYPES: list[tuple[str, Decimal, bool]] = [
    ("Annual Leave", Decimal("21"), True),
    ("Sick Leave", Decimal("14"), True),
    ("Maternity Leave", Decimal("90"), True),
    ("Paternity Leave", Decimal("14"), True),
    ("Compassionate Leave", Decimal("5"), True),
    ("Unpaid Leave", Decimal("0"), False),
]


class LeaveStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    cancelled = "cancelled"


class LeaveRequest(TenantModel):
    __tablename__ = "leave_requests"

    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), index=True)
    leave_type_id: Mapped[str] = mapped_column(ForeignKey("leave_types.id"), index=True)
    start_date: Mapped[date]
    end_date: Mapped[date]
    days: Mapped[Decimal] = mapped_column(Numeric(6, 1))  # working days (Mon–Fri)
    reason: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[LeaveStatus] = mapped_column(default=LeaveStatus.pending)
    decided_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(nullable=True)
    decision_note: Mapped[str] = mapped_column(String(500), default="")
