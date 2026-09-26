from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor, get_tenant_session, require_permission
from app.modules.hr import documents
from app.modules.hr.kenya_payroll import PayItem, PayslipInput, compute_payslip, rules_for
from app.modules.hr.models import Employee, EmployeePayItem, EmployeeStatus, LeaveRequest, LeaveStatus
from app.modules.hr.payroll import PayrollService
from app.modules.hr.schemas import (
    DepartmentCreate,
    DepartmentOut,
    EmployeeCreate,
    EmployeeOut,
    EmployeeUpdate,
    LeaveDecision,
    LeaveRequestCreate,
    LeaveRequestOut,
    LeaveTypeCreate,
    LeaveTypeOut,
    MarkPaidRequest,
    PayItemCreate,
    PayItemOut,
    PayrollRunCreate,
    PayrollRunOut,
    PayslipAdjustmentsSet,
    PayslipOut,
)
from app.modules.hr.service import HrService

router = APIRouter(prefix="/api/v1/hr", tags=["hr"])

hr_read = require_permission("hr.read")
hr_write = require_permission("hr.write")
payroll_read = require_permission("payroll.read")
payroll_write = require_permission("payroll.write")

SENSITIVE_FIELDS = ("basic_salary", "bank_name", "bank_branch", "bank_account", "mpesa_phone")


def _can(actor: Actor, permission: str) -> bool:
    return "*" in actor.permissions or permission in actor.permissions


def _employee_out(employee: Employee, actor: Actor) -> EmployeeOut:
    out = EmployeeOut.model_validate(employee)
    if not _can(actor, "payroll.read"):
        out = out.model_copy(update={f: (None if f == "basic_salary" else "") for f in SENSITIVE_FIELDS})
    return out


async def _workspace(session: AsyncSession, workspace_id: str):
    from app.modules.platform.service import PlatformService

    return await PlatformService(session).get_workspace(workspace_id)


def _pdf(content: bytes, filename: str) -> Response:
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}.pdf"'},
    )


# ------------------------------------------------------------- departments


@router.get("/departments", response_model=list[DepartmentOut])
async def list_departments(actor: Actor = Depends(hr_read), session: AsyncSession = Depends(get_tenant_session)):
    return sorted(await HrService(session, actor.workspace_id).departments.list(), key=lambda d: d.name)


@router.post("/departments", response_model=DepartmentOut)
async def create_department(
    payload: DepartmentCreate, actor: Actor = Depends(hr_write), session: AsyncSession = Depends(get_tenant_session)
):
    return await HrService(session, actor.workspace_id).create_department(payload)


# --------------------------------------------------------------- employees


@router.get("/employees", response_model=list[EmployeeOut])
async def list_employees(
    status_filter: EmployeeStatus | None = Query(None, alias="status"),
    department_id: str | None = None,
    actor: Actor = Depends(hr_read),
    session: AsyncSession = Depends(get_tenant_session),
):
    filters = []
    if status_filter:
        filters.append(Employee.status == status_filter)
    if department_id:
        filters.append(Employee.department_id == department_id)
    employees = await HrService(session, actor.workspace_id).employees.list(*filters)
    return [_employee_out(e, actor) for e in sorted(employees, key=lambda e: e.employee_no)]


@router.post("/employees", response_model=EmployeeOut)
async def create_employee(
    payload: EmployeeCreate, actor: Actor = Depends(hr_write), session: AsyncSession = Depends(get_tenant_session)
):
    return _employee_out(await HrService(session, actor.workspace_id).create_employee(payload), actor)


@router.get("/employees/{employee_id}", response_model=EmployeeOut)
async def get_employee(employee_id: str, actor: Actor = Depends(hr_read), session: AsyncSession = Depends(get_tenant_session)):
    return _employee_out(await HrService(session, actor.workspace_id).get_employee(employee_id), actor)


@router.patch("/employees/{employee_id}", response_model=EmployeeOut)
async def update_employee(
    employee_id: str,
    payload: EmployeeUpdate,
    actor: Actor = Depends(hr_write),
    session: AsyncSession = Depends(get_tenant_session),
):
    changes = payload.model_dump(exclude_unset=True)
    if any(f in changes for f in SENSITIVE_FIELDS) and not _can(actor, "payroll.write"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "changing salary or bank details needs payroll.write")
    employee = await HrService(session, actor.workspace_id).update_employee(employee_id, changes)
    return _employee_out(employee, actor)


@router.get("/employees/{employee_id}/pay-items", response_model=list[PayItemOut])
async def list_pay_items(employee_id: str, actor: Actor = Depends(payroll_read), session: AsyncSession = Depends(get_tenant_session)):
    items = await HrService(session, actor.workspace_id).pay_items.list(EmployeePayItem.employee_id == employee_id)
    return sorted(items, key=lambda i: (not i.is_active, i.kind.value, i.name))


@router.post("/employees/{employee_id}/pay-items", response_model=PayItemOut)
async def add_pay_item(
    employee_id: str,
    payload: PayItemCreate,
    actor: Actor = Depends(payroll_write),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await HrService(session, actor.workspace_id).add_pay_item(employee_id, payload)


@router.delete("/pay-items/{item_id}", response_model=PayItemOut)
async def deactivate_pay_item(item_id: str, actor: Actor = Depends(payroll_write), session: AsyncSession = Depends(get_tenant_session)):
    return await HrService(session, actor.workspace_id).deactivate_pay_item(item_id)


@router.get("/employees/{employee_id}/leave-balances")
async def leave_balances(
    employee_id: str,
    year: int | None = None,
    actor: Actor = Depends(hr_read),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await HrService(session, actor.workspace_id).leave_balances(employee_id, year or date.today().year)


# ------------------------------------------------------------------- leave


@router.get("/leave-types", response_model=list[LeaveTypeOut])
async def list_leave_types(actor: Actor = Depends(hr_read), session: AsyncSession = Depends(get_tenant_session)):
    return await HrService(session, actor.workspace_id).list_leave_types()


@router.post("/leave-types", response_model=LeaveTypeOut)
async def create_leave_type(
    payload: LeaveTypeCreate, actor: Actor = Depends(hr_write), session: AsyncSession = Depends(get_tenant_session)
):
    return await HrService(session, actor.workspace_id).create_leave_type(payload)


@router.get("/leave-requests", response_model=list[LeaveRequestOut])
async def list_leave_requests(
    status_filter: LeaveStatus | None = Query(None, alias="status"),
    employee_id: str | None = None,
    actor: Actor = Depends(hr_read),
    session: AsyncSession = Depends(get_tenant_session),
):
    filters = []
    if status_filter:
        filters.append(LeaveRequest.status == status_filter)
    if employee_id:
        filters.append(LeaveRequest.employee_id == employee_id)
    requests = await HrService(session, actor.workspace_id).leave_requests.list(*filters)
    return sorted(requests, key=lambda r: r.start_date, reverse=True)


@router.post("/leave-requests", response_model=LeaveRequestOut)
async def request_leave(
    payload: LeaveRequestCreate, actor: Actor = Depends(hr_write), session: AsyncSession = Depends(get_tenant_session)
):
    return await HrService(session, actor.workspace_id).request_leave(payload)


@router.post("/leave-requests/{request_id}/decision", response_model=LeaveRequestOut)
async def decide_leave(
    request_id: str,
    payload: LeaveDecision,
    actor: Actor = Depends(hr_write),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await HrService(session, actor.workspace_id).decide_leave(request_id, payload.status, payload.note, actor.user_id)


# ----------------------------------------------------------------- payroll


class PayCalculatorRequest(BaseModel):
    basic_salary: Decimal = Field(ge=0)
    taxable_allowances: Decimal = Field(default=Decimal("0"), ge=0)
    non_taxable_allowances: Decimal = Field(default=Decimal("0"), ge=0)
    pension_contribution: Decimal = Field(default=Decimal("0"), ge=0)
    period: date | None = None


@router.post("/payroll/calculator")
async def pay_calculator(payload: PayCalculatorRequest, actor: Actor = Depends(hr_read)):
    """Gross-to-net calculator for offers and salary reviews — no data saved."""
    earnings = []
    if payload.taxable_allowances:
        earnings.append(PayItem("Allowances", payload.taxable_allowances))
    if payload.non_taxable_allowances:
        earnings.append(PayItem("Non-taxable allowances", payload.non_taxable_allowances, taxable=False))
    deductions = [PayItem("Pension", payload.pension_contribution, pre_tax=True)] if payload.pension_contribution else []
    result = compute_payslip(
        PayslipInput(basic_salary=payload.basic_salary, earnings=earnings, deductions=deductions),
        rules_for(payload.period or date.today()),
    )
    return result.__dict__


@router.get("/payroll/runs", response_model=list[PayrollRunOut])
async def list_runs(actor: Actor = Depends(payroll_read), session: AsyncSession = Depends(get_tenant_session)):
    runs = await PayrollService(session, actor.workspace_id).runs.list()
    return sorted(runs, key=lambda r: (r.period_year, r.period_month), reverse=True)


@router.post("/payroll/runs", response_model=PayrollRunOut)
async def create_run(
    payload: PayrollRunCreate, actor: Actor = Depends(payroll_write), session: AsyncSession = Depends(get_tenant_session)
):
    return await PayrollService(session, actor.workspace_id).create_run(
        year=payload.period_year, month=payload.period_month, pay_date=payload.pay_date, notes=payload.notes
    )


@router.get("/payroll/runs/{run_id}", response_model=PayrollRunOut)
async def get_run(run_id: str, actor: Actor = Depends(payroll_read), session: AsyncSession = Depends(get_tenant_session)):
    return await PayrollService(session, actor.workspace_id).get_run(run_id)


@router.delete("/payroll/runs/{run_id}")
async def delete_run(run_id: str, actor: Actor = Depends(payroll_write), session: AsyncSession = Depends(get_tenant_session)):
    await PayrollService(session, actor.workspace_id).delete_draft(run_id)
    return {"ok": True}


@router.get("/payroll/runs/{run_id}/payslips", response_model=list[PayslipOut])
async def run_payslips(run_id: str, actor: Actor = Depends(payroll_read), session: AsyncSession = Depends(get_tenant_session)):
    return await PayrollService(session, actor.workspace_id).run_payslips(run_id)


@router.post("/payroll/runs/{run_id}/recalculate", response_model=PayrollRunOut)
async def recalculate_run(run_id: str, actor: Actor = Depends(payroll_write), session: AsyncSession = Depends(get_tenant_session)):
    return await PayrollService(session, actor.workspace_id).recalculate(run_id)


@router.post("/payroll/runs/{run_id}/approve", response_model=PayrollRunOut)
async def approve_run(run_id: str, actor: Actor = Depends(payroll_write), session: AsyncSession = Depends(get_tenant_session)):
    return await PayrollService(session, actor.workspace_id).approve(run_id, actor.user_id)


@router.post("/payroll/runs/{run_id}/mark-paid", response_model=PayrollRunOut)
async def mark_run_paid(
    run_id: str,
    payload: MarkPaidRequest,
    actor: Actor = Depends(payroll_write),
    session: AsyncSession = Depends(get_tenant_session),
):
    return await PayrollService(session, actor.workspace_id).mark_paid(run_id, payload.paid_on)


@router.get("/payroll/runs/{run_id}/reports/{kind}")
async def statutory_report(
    run_id: str, kind: str, actor: Actor = Depends(payroll_read), session: AsyncSession = Depends(get_tenant_session)
):
    return await PayrollService(session, actor.workspace_id).statutory_report(run_id, kind)


@router.get("/payroll/runs/{run_id}/reports/{kind}/csv")
async def statutory_report_csv(
    run_id: str, kind: str, actor: Actor = Depends(payroll_read), session: AsyncSession = Depends(get_tenant_session)
):
    service = PayrollService(session, actor.workspace_id)
    run = await service.get_run(run_id)
    content = await service.statutory_csv(run_id, kind)
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{kind}-{run.period_year}-{run.period_month:02d}.csv"'},
    )


@router.get("/payroll/runs/{run_id}/payslips/pdf")
async def run_payslips_pdf(run_id: str, actor: Actor = Depends(payroll_read), session: AsyncSession = Depends(get_tenant_session)):
    service = PayrollService(session, actor.workspace_id)
    run = await service.get_run(run_id)
    pdf = documents.render_payslips(await _workspace(session, actor.workspace_id), run, await service.run_payslips(run_id))
    return _pdf(pdf, f"payslips-{run.period_year}-{run.period_month:02d}")


@router.put("/payroll/payslips/{payslip_id}/adjustments", response_model=PayslipOut)
async def set_payslip_adjustments(
    payslip_id: str,
    payload: PayslipAdjustmentsSet,
    actor: Actor = Depends(payroll_write),
    session: AsyncSession = Depends(get_tenant_session),
):
    adjustments = [
        {"kind": a.kind.value, "name": a.name, "amount": str(a.amount), "taxable": a.taxable, "pre_tax": a.pre_tax}
        for a in payload.adjustments
    ]
    return await PayrollService(session, actor.workspace_id).set_adjustments(payslip_id, adjustments)


@router.get("/payroll/payslips/{payslip_id}/pdf")
async def payslip_pdf(payslip_id: str, actor: Actor = Depends(payroll_read), session: AsyncSession = Depends(get_tenant_session)):
    service = PayrollService(session, actor.workspace_id)
    payslip = await service.payslips.get(payslip_id)
    if payslip is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "payslip not found")
    run = await service.get_run(payslip.run_id)
    pdf = documents.render_payslips(await _workspace(session, actor.workspace_id), run, [payslip])
    return _pdf(pdf, f"payslip-{payslip.employee_no}-{run.period_year}-{run.period_month:02d}")


@router.get("/employees/{employee_id}/p9")
async def p9(
    employee_id: str, year: int | None = None, actor: Actor = Depends(payroll_read), session: AsyncSession = Depends(get_tenant_session)
):
    return await PayrollService(session, actor.workspace_id).p9(employee_id, year or date.today().year)


@router.get("/employees/{employee_id}/p9/pdf")
async def p9_pdf(
    employee_id: str, year: int | None = None, actor: Actor = Depends(payroll_read), session: AsyncSession = Depends(get_tenant_session)
):
    data = await PayrollService(session, actor.workspace_id).p9(employee_id, year or date.today().year)
    pdf = documents.render_p9(await _workspace(session, actor.workspace_id), data)
    return _pdf(pdf, f"P9-{data['employee_no']}-{data['year']}")

