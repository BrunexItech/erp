from __future__ import annotations

import calendar
import csv
import io
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.db import TenantRepository
from app.core.numbering import next_number
from app.modules.hr.kenya_payroll import PayItem, PayslipInput, compute_payslip, rules_for
from app.modules.hr.models import (
    Department,
    Employee,
    EmployeePayItem,
    EmployeeStatus,
    PayItemKind,
    PayrollRun,
    PayrollRunStatus,
    Payslip,
)
from app.modules.hr.service import HrService, working_days

ZERO = Decimal("0")

# Run totals are the sum of these payslip columns.
TOTAL_FIELDS = (
    "gross_pay", "paye", "nssf_employee", "nssf_employer", "shif",
    "housing_levy_employee", "housing_levy_employer", "nita", "other_deductions",
    "net_pay", "employer_cost",
)

RESULT_FIELDS = (
    "gross_pay", "taxable_earnings", "nssf_tier1", "nssf_tier2", "nssf_employee", "nssf_employer",
    "shif", "housing_levy_employee", "housing_levy_employer", "pension_relief", "taxable_pay",
    "paye_before_relief", "personal_relief", "paye", "other_deductions", "total_deductions",
    "net_pay", "nita", "employer_cost",
)


def _q2(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _period_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


class PayrollService:
    def __init__(self, session: AsyncSession, workspace_id: str):
        self.session = session
        self.workspace_id = workspace_id
        self.runs = TenantRepository(session, workspace_id, PayrollRun)
        self.payslips = TenantRepository(session, workspace_id, Payslip)
        self.hr = HrService(session, workspace_id)

    async def get_run(self, run_id: str, *, for_update: bool = False) -> PayrollRun:
        run = await (self.runs.get_for_update(run_id) if for_update else self.runs.get(run_id))
        if run is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "payroll run not found")
        return run

    async def run_payslips(self, run_id: str) -> list[Payslip]:
        return sorted(await self.payslips.list(Payslip.run_id == run_id), key=lambda p: p.employee_no)

    # ------------------------------------------------------------- computing

    async def _compute(
        self, employee: Employee, run: PayrollRun, adjustments: list[dict], departments: dict[str, str]
    ) -> dict | None:
        start, end = _period_bounds(run.period_year, run.period_month)
        employed_from = max(start, employee.hire_date)
        employed_to = min(end, employee.termination_date) if employee.termination_date else end
        if employed_from > employed_to:
            return None  # not employed during this period

        period_days = working_days(start, end)
        employed_days = working_days(employed_from, employed_to)
        unpaid = await self.hr.unpaid_leave_days(employee.id, employed_from, employed_to)
        days_worked = max(employed_days - unpaid, 0)
        basic = _q2(employee.basic_salary * days_worked / period_days) if period_days else ZERO

        items = await self.hr.pay_items.list(
            EmployeePayItem.employee_id == employee.id, EmployeePayItem.is_active.is_(True)
        )
        earnings = [
            {"name": i.name, "amount": str(i.amount), "taxable": i.taxable, "one_off": False}
            for i in items if i.kind == PayItemKind.earning
        ]
        deductions = [
            {"name": i.name, "amount": str(i.amount), "pre_tax": i.pre_tax, "one_off": False}
            for i in items if i.kind == PayItemKind.deduction
        ]
        for adj in adjustments:
            if adj["kind"] == PayItemKind.earning.value:
                earnings.append({"name": adj["name"], "amount": adj["amount"], "taxable": adj.get("taxable", True), "one_off": True})
            else:
                deductions.append({"name": adj["name"], "amount": adj["amount"], "pre_tax": adj.get("pre_tax", False), "one_off": True})

        result = compute_payslip(
            PayslipInput(
                basic_salary=basic,
                earnings=[PayItem(e["name"], Decimal(e["amount"]), taxable=e["taxable"]) for e in earnings],
                deductions=[PayItem(d["name"], Decimal(d["amount"]), pre_tax=d["pre_tax"]) for d in deductions],
                has_disability_exemption=employee.has_disability_exemption,
                nssf_exempt=employee.nssf_exempt,
                housing_levy_exempt=employee.housing_levy_exempt,
            ),
            rules_for(start),
        )
        return {
            "employee_no": employee.employee_no,
            "employee_name": employee.full_name,
            "kra_pin": employee.kra_pin,
            "nssf_no": employee.nssf_no,
            "shif_no": employee.shif_no,
            "national_id": employee.national_id,
            "department": departments.get(employee.department_id or "", ""),
            "job_title": employee.job_title,
            "payment_method": employee.payment_method.value,
            "bank_name": employee.bank_name,
            "bank_account": employee.bank_account,
            "mpesa_phone": employee.mpesa_phone,
            "days_worked": days_worked,
            "days_in_period": period_days,
            "basic_salary": basic,
            "earnings": earnings,
            "deductions": deductions,
            "adjustments": adjustments,
            **{f: getattr(result, f) for f in RESULT_FIELDS},
        }

    async def _departments(self) -> dict[str, str]:
        return {d.id: d.name for d in await TenantRepository(self.session, self.workspace_id, Department).list()}

    def _retotal(self, run: PayrollRun, payslips: list[Payslip]) -> None:
        run.employee_count = len(payslips)
        for field in TOTAL_FIELDS:
            setattr(run, field, sum((getattr(p, field) for p in payslips), ZERO))

    async def create_run(self, *, year: int, month: int, pay_date: date | None, notes: str) -> PayrollRun:
        if await self.runs.list(PayrollRun.period_year == year, PayrollRun.period_month == month):
            raise HTTPException(status.HTTP_409_CONFLICT, f"a payroll run for {year}-{month:02d} already exists")
        _, end = _period_bounds(year, month)
        run = PayrollRun(
            run_no=await next_number(self.session, self.workspace_id, "payroll_run"),
            period_year=year,
            period_month=month,
            pay_date=pay_date or end,
            notes=notes,
        )
        await self.runs.add(run)
        await self._generate(run, keep_adjustments={})
        await self.session.commit()
        await self.session.refresh(run)
        return run

    async def _generate(self, run: PayrollRun, keep_adjustments: dict[str, list]) -> None:
        departments = await self._departments()
        employees = await self.hr.employees.list(Employee.status != EmployeeStatus.suspended)
        payslips = []
        for employee in sorted(employees, key=lambda e: e.employee_no):
            values = await self._compute(employee, run, keep_adjustments.get(employee.id, []), departments)
            if values is None:
                continue
            payslip = Payslip(run_id=run.id, employee_id=employee.id, **values)
            await self.payslips.add(payslip)
            payslips.append(payslip)
        self._retotal(run, payslips)

    async def recalculate(self, run_id: str) -> PayrollRun:
        """Rebuilds a draft run from current employee data (new hires, salary
        changes, approved unpaid leave) while keeping one-off adjustments."""
        run = await self.get_run(run_id, for_update=True)
        self._require_draft(run)
        existing = await self.run_payslips(run.id)
        keep = {p.employee_id: p.adjustments for p in existing}
        for payslip in existing:
            await self.session.delete(payslip)
        await self.session.flush()
        await self._generate(run, keep)
        await self.session.commit()
        await self.session.refresh(run)
        return run

    async def set_adjustments(self, payslip_id: str, adjustments: list[dict]) -> Payslip:
        payslip = await self.payslips.get_for_update(payslip_id)
        if payslip is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "payslip not found")
        run = await self.get_run(payslip.run_id, for_update=True)
        self._require_draft(run)
        employee = await self.hr.get_employee(payslip.employee_id)
        values = await self._compute(employee, run, adjustments, await self._departments())
        for field, value in (values or {}).items():
            setattr(payslip, field, value)
        await self.session.flush()
        self._retotal(run, await self.run_payslips(run.id))
        await self.session.commit()
        await self.session.refresh(payslip)
        return payslip

    @staticmethod
    def _require_draft(run: PayrollRun) -> None:
        if run.status != PayrollRunStatus.draft:
            raise HTTPException(status.HTTP_409_CONFLICT, f"payroll run is {run.status.value} and can no longer change")

    # -------------------------------------------------------------- lifecycle

    async def approve(self, run_id: str, user_id: str) -> PayrollRun:
        run = await self.get_run(run_id, for_update=True)
        self._require_draft(run)
        if run.employee_count == 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "payroll run has no payslips")
        run.status = PayrollRunStatus.approved
        run.approved_at = datetime.now(timezone.utc).replace(tzinfo=None)
        run.approved_by = user_id
        await events.publish(
            events.PayrollRunApproved(
                workspace_id=self.workspace_id,
                run_id=run.id,
                entry_date=_period_bounds(run.period_year, run.period_month)[1],
                gross_pay=float(run.gross_pay),
                paye=float(run.paye),
                nssf_employee=float(run.nssf_employee),
                nssf_employer=float(run.nssf_employer),
                shif=float(run.shif),
                housing_levy_employee=float(run.housing_levy_employee),
                housing_levy_employer=float(run.housing_levy_employer),
                nita=float(run.nita),
                other_deductions=float(run.other_deductions),
                net_pay=float(run.net_pay),
            ),
            self.session,
        )
        await self.session.commit()
        await self.session.refresh(run)
        return run

    async def mark_paid(self, run_id: str, paid_on: date | None) -> PayrollRun:
        run = await self.get_run(run_id, for_update=True)
        if run.status != PayrollRunStatus.approved:
            raise HTTPException(status.HTTP_409_CONFLICT, "only an approved payroll run can be marked paid")
        run.status = PayrollRunStatus.paid
        run.paid_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await events.publish(
            events.PayrollRunPaid(
                workspace_id=self.workspace_id,
                run_id=run.id,
                entry_date=paid_on or run.pay_date,
                net_pay=float(run.net_pay),
            ),
            self.session,
        )
        await self.session.commit()
        await self.session.refresh(run)
        return run

    async def delete_draft(self, run_id: str) -> None:
        run = await self.get_run(run_id, for_update=True)
        self._require_draft(run)
        for payslip in await self.run_payslips(run.id):
            await self.session.delete(payslip)
        await self.session.flush()
        await self.session.delete(run)
        await self.session.commit()

    # ---------------------------------------------------------------- reports

    async def statutory_report(self, run_id: str, kind: str) -> dict:
        """Per-employee schedules for each remittance: KRA PAYE (P10 data),
        NSSF, SHIF (SHA), Housing Levy, and the net-pay payment schedule."""
        run = await self.get_run(run_id)
        payslips = await self.run_payslips(run.id)
        columns: dict[str, list[tuple[str, str]]] = {
            "paye": [("employee_no", "Emp No"), ("employee_name", "Name"), ("kra_pin", "KRA PIN"),
                     ("gross_pay", "Gross Pay"), ("taxable_pay", "Taxable Pay"),
                     ("paye_before_relief", "Tax Charged"), ("personal_relief", "Personal Relief"), ("paye", "PAYE")],
            "nssf": [("employee_no", "Emp No"), ("employee_name", "Name"), ("national_id", "ID No"),
                     ("nssf_no", "NSSF No"), ("taxable_earnings", "Pensionable Pay"), ("nssf_tier1", "Tier I"),
                     ("nssf_tier2", "Tier II"), ("nssf_employee", "Employee"), ("nssf_employer", "Employer")],
            "shif": [("employee_no", "Emp No"), ("employee_name", "Name"), ("national_id", "ID No"),
                     ("shif_no", "SHIF No"), ("taxable_earnings", "Gross Pay"), ("shif", "SHIF")],
            "housing_levy": [("employee_no", "Emp No"), ("employee_name", "Name"), ("kra_pin", "KRA PIN"),
                             ("taxable_earnings", "Gross Pay"), ("housing_levy_employee", "Employee"),
                             ("housing_levy_employer", "Employer")],
            "payments": [("employee_no", "Emp No"), ("employee_name", "Name"), ("payment_method", "Method"),
                         ("bank_name", "Bank"), ("bank_account", "Account"), ("mpesa_phone", "M-Pesa"),
                         ("net_pay", "Net Pay")],
            "register": [("employee_no", "Emp No"), ("employee_name", "Name"), ("department", "Department"),
                         ("basic_salary", "Basic"), ("gross_pay", "Gross"), ("nssf_employee", "NSSF"),
                         ("shif", "SHIF"), ("housing_levy_employee", "AHL"), ("paye", "PAYE"),
                         ("other_deductions", "Other Ded."), ("net_pay", "Net Pay")],
        }
        if kind not in columns:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown report '{kind}'")
        cols = columns[kind]
        rows = [{key: getattr(p, key) for key, _ in cols} for p in payslips]
        totals = {
            key: sum((r[key] for r in rows), ZERO)
            for key, _ in cols
            if rows and isinstance(rows[0][key], Decimal)
        }
        return {
            "run_no": run.run_no,
            "period": f"{run.period_year}-{run.period_month:02d}",
            "kind": kind,
            "columns": [{"key": k, "label": label} for k, label in cols],
            "rows": rows,
            "totals": totals,
        }

    async def statutory_csv(self, run_id: str, kind: str) -> str:
        report = await self.statutory_report(run_id, kind)
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([c["label"] for c in report["columns"]])
        for row in report["rows"]:
            writer.writerow([row[c["key"]] for c in report["columns"]])
        if report["totals"]:
            writer.writerow([report["totals"].get(c["key"], "TOTAL" if i == 0 else "") for i, c in enumerate(report["columns"])])
        return buffer.getvalue()

    async def p9(self, employee_id: str, year: int) -> dict:
        """KRA P9A tax deduction card: the employee's month-by-month pay and
        tax for the year, from approved/paid runs only."""
        employee = await self.hr.get_employee(employee_id)
        runs = {
            r.id: r
            for r in await self.runs.list(
                PayrollRun.period_year == year,
                PayrollRun.status.in_([PayrollRunStatus.approved, PayrollRunStatus.paid]),
            )
        }
        payslips = [
            p for p in await self.payslips.list(Payslip.employee_id == employee.id) if p.run_id in runs
        ]
        by_month = {runs[p.run_id].period_month: p for p in payslips}
        months = []
        for month in range(1, 13):
            p = by_month.get(month)
            months.append(
                {
                    "month": calendar.month_name[month],
                    "basic_salary": p.basic_salary if p else ZERO,
                    "benefits": (p.gross_pay - p.basic_salary) if p else ZERO,
                    "gross_pay": p.gross_pay if p else ZERO,
                    "retirement_contribution": (p.nssf_employee + p.pension_relief) if p else ZERO,
                    "shif": p.shif if p else ZERO,
                    "housing_levy": p.housing_levy_employee if p else ZERO,
                    "taxable_pay": p.taxable_pay if p else ZERO,
                    "tax_charged": p.paye_before_relief if p else ZERO,
                    "personal_relief": p.personal_relief if p else ZERO,
                    "paye": p.paye if p else ZERO,
                }
            )
        numeric = [k for k in months[0] if k != "month"]
        return {
            "year": year,
            "employee_id": employee.id,
            "employee_no": employee.employee_no,
            "employee_name": employee.full_name,
            "kra_pin": employee.kra_pin,
            "months": months,
            "totals": {k: sum((m[k] for m in months), ZERO) for k in numeric},
        }
