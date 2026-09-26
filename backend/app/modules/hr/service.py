from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import TenantRepository
from app.core.numbering import next_number
from app.modules.hr.models import (
    DEFAULT_LEAVE_TYPES,
    Department,
    Employee,
    EmployeePayItem,
    EmployeeStatus,
    LeaveRequest,
    LeaveStatus,
    LeaveType,
    PayItemKind,
)
from app.modules.hr.schemas import (
    DepartmentCreate,
    EmployeeCreate,
    LeaveRequestCreate,
    LeaveTypeCreate,
    PayItemCreate,
)


def working_days(start: date, end: date) -> int:
    """Mon–Fri days in [start, end], inclusive."""
    if end < start:
        return 0
    days = 0
    current = start
    while current <= end:
        if current.weekday() < 5:
            days += 1
        current += timedelta(days=1)
    return days


class HrService:
    def __init__(self, session: AsyncSession, workspace_id: str):
        self.session = session
        self.workspace_id = workspace_id
        self.departments = TenantRepository(session, workspace_id, Department)
        self.employees = TenantRepository(session, workspace_id, Employee)
        self.pay_items = TenantRepository(session, workspace_id, EmployeePayItem)
        self.leave_types = TenantRepository(session, workspace_id, LeaveType)
        self.leave_requests = TenantRepository(session, workspace_id, LeaveRequest)

    # ------------------------------------------------------------ departments

    async def create_department(self, payload: DepartmentCreate) -> Department:
        if await self.departments.list(Department.name == payload.name):
            raise HTTPException(status.HTTP_409_CONFLICT, "a department with that name exists")
        department = Department(**payload.model_dump())
        await self.departments.add(department)
        await self.session.commit()
        await self.session.refresh(department)
        return department

    # -------------------------------------------------------------- employees

    async def get_employee(self, employee_id: str) -> Employee:
        employee = await self.employees.get(employee_id)
        if employee is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "employee not found")
        return employee

    async def create_employee(self, payload: EmployeeCreate) -> Employee:
        data = payload.model_dump()
        employee_no = data.pop("employee_no") or await next_number(self.session, self.workspace_id, "employee")
        if await self.employees.list(Employee.employee_no == employee_no):
            raise HTTPException(status.HTTP_409_CONFLICT, f"employee number {employee_no} is taken")
        if data["department_id"] and await self.departments.get(data["department_id"]) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "department not found")
        employee = Employee(employee_no=employee_no, **data)
        await self.employees.add(employee)
        await self.session.commit()
        await self.session.refresh(employee)
        return employee

    async def update_employee(self, employee_id: str, changes: dict) -> Employee:
        employee = await self.get_employee(employee_id)
        if changes.get("department_id") and await self.departments.get(changes["department_id"]) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "department not found")
        if changes.get("status") == EmployeeStatus.terminated and not (
            changes.get("termination_date") or employee.termination_date
        ):
            changes["termination_date"] = date.today()
        for field, value in changes.items():
            setattr(employee, field, value)
        await self.session.commit()
        await self.session.refresh(employee)
        return employee

    # -------------------------------------------------------------- pay items

    async def add_pay_item(self, employee_id: str, payload: PayItemCreate) -> EmployeePayItem:
        await self.get_employee(employee_id)
        item = EmployeePayItem(
            employee_id=employee_id,
            kind=payload.kind,
            name=payload.name,
            amount=payload.amount,
            taxable=payload.taxable if payload.kind == PayItemKind.earning else True,
            pre_tax=payload.pre_tax if payload.kind == PayItemKind.deduction else False,
        )
        await self.pay_items.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def deactivate_pay_item(self, item_id: str) -> EmployeePayItem:
        item = await self.pay_items.get(item_id)
        if item is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "pay item not found")
        item.is_active = False
        await self.session.commit()
        await self.session.refresh(item)
        return item

    # ------------------------------------------------------------------ leave

    async def list_leave_types(self) -> list[LeaveType]:
        types = await self.leave_types.list()
        if not types:
            for name, days, paid in DEFAULT_LEAVE_TYPES:
                await self.leave_types.add(LeaveType(name=name, days_per_year=days, is_paid=paid))
            await self.session.commit()
            types = await self.leave_types.list()
        return sorted(types, key=lambda t: t.name)

    async def create_leave_type(self, payload: LeaveTypeCreate) -> LeaveType:
        if await self.leave_types.list(LeaveType.name == payload.name):
            raise HTTPException(status.HTTP_409_CONFLICT, "leave type exists")
        leave_type = LeaveType(**payload.model_dump())
        await self.leave_types.add(leave_type)
        await self.session.commit()
        await self.session.refresh(leave_type)
        return leave_type

    async def _days_taken(self, employee_id: str, leave_type_id: str, year: int, exclude_id: str | None = None) -> Decimal:
        requests = await self.leave_requests.list(
            LeaveRequest.employee_id == employee_id,
            LeaveRequest.leave_type_id == leave_type_id,
            LeaveRequest.status.in_([LeaveStatus.pending, LeaveStatus.approved]),
        )
        return sum(
            (r.days for r in requests if r.start_date.year == year and r.id != exclude_id), Decimal("0")
        )

    async def leave_balances(self, employee_id: str, year: int) -> list[dict]:
        await self.get_employee(employee_id)
        rows = []
        for leave_type in await self.list_leave_types():
            if not leave_type.is_active:
                continue
            requests = await self.leave_requests.list(
                LeaveRequest.employee_id == employee_id,
                LeaveRequest.leave_type_id == leave_type.id,
            )
            this_year = [r for r in requests if r.start_date.year == year]
            taken = sum((r.days for r in this_year if r.status == LeaveStatus.approved), Decimal("0"))
            pending = sum((r.days for r in this_year if r.status == LeaveStatus.pending), Decimal("0"))
            entitled = leave_type.days_per_year
            rows.append(
                {
                    "leave_type_id": leave_type.id,
                    "leave_type": leave_type.name,
                    "entitled": entitled,
                    "taken": taken,
                    "pending": pending,
                    "remaining": entitled - taken - pending if entitled else None,
                }
            )
        return rows

    async def request_leave(self, payload: LeaveRequestCreate) -> LeaveRequest:
        employee = await self.get_employee(payload.employee_id)
        if employee.status == EmployeeStatus.terminated:
            raise HTTPException(status.HTTP_409_CONFLICT, "employee has been terminated")
        leave_type = await self.leave_types.get(payload.leave_type_id)
        if leave_type is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "leave type not found")
        if payload.end_date < payload.start_date:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "end date is before start date")
        if payload.start_date.year != payload.end_date.year:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "split leave that crosses a year end into two requests")
        days = Decimal(working_days(payload.start_date, payload.end_date))
        if days == 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "the selected dates contain no working days")

        overlapping = [
            r
            for r in await self.leave_requests.list(
                LeaveRequest.employee_id == employee.id,
                LeaveRequest.status.in_([LeaveStatus.pending, LeaveStatus.approved]),
            )
            if r.start_date <= payload.end_date and payload.start_date <= r.end_date
        ]
        if overlapping:
            raise HTTPException(status.HTTP_409_CONFLICT, "overlaps an existing leave request")

        if leave_type.days_per_year > 0:
            used = await self._days_taken(employee.id, leave_type.id, payload.start_date.year)
            remaining = leave_type.days_per_year - used
            if days > remaining:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"only {remaining} day(s) of {leave_type.name} left this year; requested {days}",
                )

        request = LeaveRequest(
            employee_id=employee.id,
            leave_type_id=leave_type.id,
            start_date=payload.start_date,
            end_date=payload.end_date,
            days=days,
            reason=payload.reason,
        )
        await self.leave_requests.add(request)
        await self.session.commit()
        await self.session.refresh(request)
        return request

    async def decide_leave(self, request_id: str, new_status: LeaveStatus, note: str, user_id: str) -> LeaveRequest:
        request = await self.leave_requests.get_for_update(request_id)
        if request is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "leave request not found")
        allowed = {
            LeaveStatus.pending: {LeaveStatus.approved, LeaveStatus.rejected, LeaveStatus.cancelled},
            LeaveStatus.approved: {LeaveStatus.cancelled},
        }
        if new_status not in allowed.get(request.status, set()):
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"can't move a {request.status.value} request to {new_status.value}"
            )
        request.status = new_status
        request.decision_note = note
        request.decided_by = user_id
        request.decided_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self.session.commit()
        await self.session.refresh(request)
        return request

    async def unpaid_leave_days(self, employee_id: str, start: date, end: date) -> int:
        """Approved unpaid-leave working days falling inside [start, end] —
        payroll deducts these from the month's basic pay."""
        unpaid_types = {t.id for t in await self.leave_types.list(LeaveType.is_paid.is_(False))}
        if not unpaid_types:
            return 0
        requests = await self.leave_requests.list(
            LeaveRequest.employee_id == employee_id,
            LeaveRequest.status == LeaveStatus.approved,
            LeaveRequest.leave_type_id.in_(unpaid_types),
        )
        return sum(
            working_days(max(r.start_date, start), min(r.end_date, end))
            for r in requests
            if r.start_date <= end and start <= r.end_date
        )
