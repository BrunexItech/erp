import os
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.modules.accounting.service import AccountingService
from app.modules.hr import documents
from app.modules.hr.models import LeaveStatus, PayItemKind, PayrollRunStatus
from app.modules.hr.payroll import PayrollService
from app.modules.hr.schemas import DepartmentCreate, EmployeeCreate, LeaveRequestCreate, PayItemCreate
from app.modules.hr.service import HrService, working_days
from app.modules.platform.service import PlatformService

# September 2025: 22 working days (Mon 1st .. Tue 30th).
YEAR, MONTH = 2025, 9


async def _staff(session, workspace_id):
    await AccountingService(session, workspace_id).seed_default_accounts()
    hr = HrService(session, workspace_id)
    ops = await hr.create_department(DepartmentCreate(name="Operations"))
    wanjiru = await hr.create_employee(
        EmployeeCreate(
            first_name="Wanjiru", last_name="Kamau", kra_pin="A012345678B", nssf_no="NS1001",
            department_id=ops.id, job_title="Store Manager", hire_date=date(2024, 1, 15),
            basic_salary=Decimal("50000"), bank_name="Equity", bank_account="0170123456",
        )
    )
    await hr.add_pay_item(wanjiru.id, PayItemCreate(kind=PayItemKind.earning, name="House allowance", amount=Decimal("10000")))
    await hr.add_pay_item(wanjiru.id, PayItemCreate(kind=PayItemKind.deduction, name="SACCO", amount=Decimal("2000")))
    # Joins mid-month: 16th–30th = 11 of 22 working days.
    otieno = await hr.create_employee(
        EmployeeCreate(
            first_name="Otieno", last_name="Odhiambo", hire_date=date(YEAR, MONTH, 16),
            basic_salary=Decimal("44000"), payment_method="mpesa", mpesa_phone="0712345678",
        )
    )
    return hr, wanjiru, otieno


def test_working_days():
    assert working_days(date(2025, 9, 1), date(2025, 9, 30)) == 22
    assert working_days(date(2025, 9, 6), date(2025, 9, 7)) == 0  # weekend


async def test_payroll_run_accrues_and_pays_through_gl(session, workspace_id):
    hr, wanjiru, otieno = await _staff(session, workspace_id)
    payroll = PayrollService(session, workspace_id)
    accounting = AccountingService(session, workspace_id)

    run = await payroll.create_run(year=YEAR, month=MONTH, pay_date=None, notes="")
    assert run.run_no.startswith("PR-")
    assert run.pay_date == date(YEAR, MONTH, 30)
    slips = {p.employee_id: p for p in await payroll.run_payslips(run.id)}
    assert set(slips) == {wanjiru.id, otieno.id}

    w = slips[wanjiru.id]
    assert w.gross_pay == Decimal("60000.00")
    assert w.paye == Decimal("8538.35")  # see test_kenya_payroll.test_mid_income_payslip
    assert w.net_pay == Decimal("43311.65")
    assert w.department == "Operations"

    o = slips[otieno.id]
    assert (o.days_worked, o.days_in_period) == (11, 22)
    assert o.basic_salary == Decimal("22000.00")  # half of 44,000

    # One-off overtime on a draft run.
    updated = await payroll.set_adjustments(
        o.id, [{"kind": "earning", "name": "Overtime", "amount": "3000", "taxable": True}]
    )
    assert updated.gross_pay == Decimal("25000.00")
    await session.refresh(run)
    assert run.gross_pay == Decimal("85000.00")

    # Adjustments survive a recalculation.
    run = await payroll.recalculate(run.id)
    assert run.gross_pay == Decimal("85000.00")

    run = await payroll.approve(run.id, "tester")
    assert run.status == PayrollRunStatus.approved
    assert await accounting.balance_for_key("SALARIES_EXPENSE") == run.gross_pay
    assert await accounting.balance_for_key("PAYE_PAYABLE") == run.paye
    assert await accounting.balance_for_key("NSSF_PAYABLE") == run.nssf_employee + run.nssf_employer
    assert await accounting.balance_for_key("NET_PAY_PAYABLE") == run.net_pay
    assert await accounting.balance_for_key("OTHER_DEDUCTIONS_PAYABLE") == Decimal("2000.00")
    assert await accounting.balance_for_key("NITA_PAYABLE") == Decimal("100.00")

    with pytest.raises(HTTPException):
        await payroll.set_adjustments(o.id, [])  # approved runs are frozen

    run = await payroll.mark_paid(run.id, None)
    assert await accounting.balance_for_key("NET_PAY_PAYABLE") == Decimal("0")
    assert await accounting.balance_for_key("CASH") == -run.net_pay

    tb = await accounting.trial_balance()
    assert sum(r["debit"] for r in tb) == sum(r["credit"] for r in tb)

    # Statutory schedules tie back to the run totals.
    paye = await payroll.statutory_report(run.id, "paye")
    assert paye["totals"]["paye"] == run.paye
    payments = await payroll.statutory_report(run.id, "payments")
    assert payments["totals"]["net_pay"] == run.net_pay
    csv_text = await payroll.statutory_csv(run.id, "nssf")
    assert "NS1001" in csv_text

    p9 = await payroll.p9(wanjiru.id, YEAR)
    assert p9["totals"]["paye"] == Decimal("8538.35")
    assert p9["months"][MONTH - 1]["gross_pay"] == Decimal("60000.00")

    workspace = await PlatformService(session).get_workspace(workspace_id)
    payslips_pdf = documents.render_payslips(workspace, run, await payroll.run_payslips(run.id))
    p9_pdf = documents.render_p9(workspace, p9)
    assert payslips_pdf[:4] == b"%PDF" and p9_pdf[:4] == b"%PDF"
    out_dir = os.environ.get("ERP_PDF_OUT")
    if out_dir:
        open(os.path.join(out_dir, "payslips.pdf"), "wb").write(payslips_pdf)
        open(os.path.join(out_dir, "p9.pdf"), "wb").write(p9_pdf)


async def test_one_run_per_period_and_terminated_staff_excluded(session, workspace_id):
    hr, wanjiru, otieno = await _staff(session, workspace_id)
    await hr.update_employee(otieno.id, {"status": "terminated", "termination_date": date(YEAR, MONTH - 1, 30)})
    payroll = PayrollService(session, workspace_id)
    run = await payroll.create_run(year=YEAR, month=MONTH, pay_date=None, notes="")
    assert run.employee_count == 1
    with pytest.raises(HTTPException):
        await payroll.create_run(year=YEAR, month=MONTH, pay_date=None, notes="")


async def test_leave_balances_overlap_and_unpaid_leave_deduction(session, workspace_id):
    hr, wanjiru, _ = await _staff(session, workspace_id)
    types = {t.name: t for t in await hr.list_leave_types()}
    annual, unpaid = types["Annual Leave"], types["Unpaid Leave"]

    request = await hr.request_leave(
        LeaveRequestCreate(employee_id=wanjiru.id, leave_type_id=annual.id,
                           start_date=date(YEAR, MONTH, 1), end_date=date(YEAR, MONTH, 5))
    )
    assert request.days == Decimal("5")
    await hr.decide_leave(request.id, LeaveStatus.approved, "enjoy", "manager")

    with pytest.raises(HTTPException):  # overlaps the approved request
        await hr.request_leave(
            LeaveRequestCreate(employee_id=wanjiru.id, leave_type_id=annual.id,
                               start_date=date(YEAR, MONTH, 4), end_date=date(YEAR, MONTH, 8))
        )
    with pytest.raises(HTTPException):  # 17 days left, asking for 20
        await hr.request_leave(
            LeaveRequestCreate(employee_id=wanjiru.id, leave_type_id=annual.id,
                               start_date=date(YEAR, 10, 1), end_date=date(YEAR, 10, 28))
        )

    balances = {b["leave_type"]: b for b in await hr.leave_balances(wanjiru.id, YEAR)}
    assert balances["Annual Leave"]["remaining"] == Decimal("16")

    # 2 approved unpaid days -> 20/22 of basic.
    unpaid_request = await hr.request_leave(
        LeaveRequestCreate(employee_id=wanjiru.id, leave_type_id=unpaid.id,
                           start_date=date(YEAR, MONTH, 22), end_date=date(YEAR, MONTH, 23))
    )
    await hr.decide_leave(unpaid_request.id, LeaveStatus.approved, "", "manager")
    run = await PayrollService(session, workspace_id).create_run(year=YEAR, month=MONTH, pay_date=None, notes="")
    slip = next(p for p in await PayrollService(session, workspace_id).run_payslips(run.id) if p.employee_id == wanjiru.id)
    assert slip.days_worked == 20
    assert slip.basic_salary == Decimal("45454.55")  # 50,000 x 20/22
