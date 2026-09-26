from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.modules.hr.models import (
    EmployeeStatus,
    EmploymentType,
    LeaveStatus,
    PaymentMethod,
    PayItemKind,
    PayrollRunStatus,
)


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    code: str = ""
    head_employee_id: str | None = None


class DepartmentOut(BaseModel):
    id: str
    name: str
    code: str
    head_employee_id: str | None

    class Config:
        from_attributes = True


class EmployeeBase(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    other_names: str = ""
    email: str = ""
    phone: str = ""
    gender: str = ""
    date_of_birth: date | None = None
    national_id: str = ""
    kra_pin: str = ""
    nssf_no: str = ""
    shif_no: str = ""
    department_id: str | None = None
    job_title: str = ""
    employment_type: EmploymentType = EmploymentType.permanent
    hire_date: date
    basic_salary: Decimal = Field(default=Decimal("0"), ge=0)
    payment_method: PaymentMethod = PaymentMethod.bank
    bank_name: str = ""
    bank_branch: str = ""
    bank_account: str = ""
    mpesa_phone: str = ""
    has_disability_exemption: bool = False
    nssf_exempt: bool = False
    housing_levy_exempt: bool = False


class EmployeeCreate(EmployeeBase):
    employee_no: str | None = None  # auto-numbered (EMP-000001) when omitted


class EmployeeUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    other_names: str | None = None
    email: str | None = None
    phone: str | None = None
    gender: str | None = None
    date_of_birth: date | None = None
    national_id: str | None = None
    kra_pin: str | None = None
    nssf_no: str | None = None
    shif_no: str | None = None
    department_id: str | None = None
    job_title: str | None = None
    employment_type: EmploymentType | None = None
    status: EmployeeStatus | None = None
    termination_date: date | None = None
    basic_salary: Decimal | None = Field(default=None, ge=0)
    payment_method: PaymentMethod | None = None
    bank_name: str | None = None
    bank_branch: str | None = None
    bank_account: str | None = None
    mpesa_phone: str | None = None
    has_disability_exemption: bool | None = None
    nssf_exempt: bool | None = None
    housing_levy_exempt: bool | None = None


class EmployeeOut(EmployeeBase):
    id: str
    employee_no: str
    full_name: str
    status: EmployeeStatus
    termination_date: date | None
    # Salary and bank fields are blanked for callers without payroll.read.
    basic_salary: Decimal | None = None  # type: ignore[assignment]

    class Config:
        from_attributes = True


class PayItemCreate(BaseModel):
    kind: PayItemKind
    name: str = Field(min_length=1, max_length=120)
    amount: Decimal = Field(gt=0)
    taxable: bool = True
    pre_tax: bool = False


class PayItemOut(BaseModel):
    id: str
    employee_id: str
    kind: PayItemKind
    name: str
    amount: Decimal
    taxable: bool
    pre_tax: bool
    is_active: bool

    class Config:
        from_attributes = True


class PayrollRunCreate(BaseModel):
    period_year: int = Field(ge=2000, le=2100)
    period_month: int = Field(ge=1, le=12)
    pay_date: date | None = None
    notes: str = ""


class PayrollRunOut(BaseModel):
    id: str
    run_no: str
    period_year: int
    period_month: int
    pay_date: date
    status: PayrollRunStatus
    notes: str
    employee_count: int
    gross_pay: Decimal
    paye: Decimal
    nssf_employee: Decimal
    nssf_employer: Decimal
    shif: Decimal
    housing_levy_employee: Decimal
    housing_levy_employer: Decimal
    nita: Decimal
    other_deductions: Decimal
    net_pay: Decimal
    employer_cost: Decimal
    approved_at: datetime | None
    paid_at: datetime | None

    class Config:
        from_attributes = True


class PayslipOut(BaseModel):
    id: str
    run_id: str
    employee_id: str
    employee_no: str
    employee_name: str
    kra_pin: str
    nssf_no: str
    shif_no: str
    department: str
    job_title: str
    payment_method: str
    bank_name: str
    bank_account: str
    mpesa_phone: str
    days_worked: int
    days_in_period: int
    basic_salary: Decimal
    earnings: list
    deductions: list
    adjustments: list
    gross_pay: Decimal
    taxable_earnings: Decimal
    nssf_tier1: Decimal
    nssf_tier2: Decimal
    nssf_employee: Decimal
    nssf_employer: Decimal
    shif: Decimal
    housing_levy_employee: Decimal
    housing_levy_employer: Decimal
    pension_relief: Decimal
    taxable_pay: Decimal
    paye_before_relief: Decimal
    personal_relief: Decimal
    paye: Decimal
    other_deductions: Decimal
    total_deductions: Decimal
    net_pay: Decimal
    nita: Decimal
    employer_cost: Decimal

    class Config:
        from_attributes = True


class PayslipAdjustment(BaseModel):
    kind: PayItemKind
    name: str = Field(min_length=1, max_length=120)
    amount: Decimal = Field(gt=0)
    taxable: bool = True
    pre_tax: bool = False


class PayslipAdjustmentsSet(BaseModel):
    """Replaces this payslip's one-off items (overtime, bonus, advance
    recovery...) and recomputes it. Draft runs only."""

    adjustments: list[PayslipAdjustment]


class MarkPaidRequest(BaseModel):
    paid_on: date | None = None


class LeaveTypeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    days_per_year: Decimal = Field(default=Decimal("0"), ge=0)
    is_paid: bool = True


class LeaveTypeOut(BaseModel):
    id: str
    name: str
    days_per_year: Decimal
    is_paid: bool
    is_active: bool

    class Config:
        from_attributes = True


class LeaveRequestCreate(BaseModel):
    employee_id: str
    leave_type_id: str
    start_date: date
    end_date: date
    reason: str = ""


class LeaveRequestOut(BaseModel):
    id: str
    employee_id: str
    leave_type_id: str
    start_date: date
    end_date: date
    days: Decimal
    reason: str
    status: LeaveStatus
    decided_at: datetime | None
    decision_note: str

    class Config:
        from_attributes = True


class LeaveDecision(BaseModel):
    status: LeaveStatus
    note: str = ""
