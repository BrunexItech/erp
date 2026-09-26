"use client";

import { useMemo, useState } from "react";
import {
  Badge,
  Button,
  Card,
  Checkbox,
  EmptyState,
  ErrorBanner,
  Field,
  Input,
  Loading,
  Modal,
  PageHeader,
  Select,
  StatTile,
  Table,
  Tabs,
  Td,
  Th,
} from "@/components/om/primitives";
import { useMe } from "@/lib/api/hooks";
import { errorMessage, openFile, useApi, useApiMutation } from "@/lib/api/query";
import { fmtDate, fmtMoney, humanize, num, today } from "@/lib/format";
import type { Department, Employee, LeaveBalance, LeaveRequest, LeaveType, PayItem } from "@/lib/api/types";

type Tab = "employees" | "leave" | "departments";

export default function HrPage() {
  const [tab, setTab] = useState<Tab>("employees");
  return (
    <div className="space-y-6">
      <PageHeader title="Employees & Leave" description="Staff records, statutory numbers, departments and leave management." />
      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        tabs={[
          { key: "employees", label: "Employees" },
          { key: "leave", label: "Leave" },
          { key: "departments", label: "Departments" },
        ]}
      />
      {tab === "employees" && <EmployeesTab />}
      {tab === "leave" && <LeaveTab />}
      {tab === "departments" && <DepartmentsTab />}
    </div>
  );
}

function useCan() {
  const { data: me } = useMe();
  const perms = new Set(me?.permissions ?? []);
  return (p: string) => perms.has("*") || perms.has(p);
}

const STATUS_TONE: Record<string, "success" | "warning" | "danger"> = { active: "success", suspended: "warning", terminated: "danger" };

function EmployeesTab() {
  const { data: employees, isLoading } = useApi<Employee[]>("/hr/employees");
  const { data: departments } = useApi<Department[]>("/hr/departments");
  const can = useCan();
  const [editing, setEditing] = useState<Employee | "new" | null>(null);
  const [viewing, setViewing] = useState<Employee | null>(null);
  const [search, setSearch] = useState("");
  const deptNames = useMemo(() => new Map((departments ?? []).map((d) => [d.id, d.name])), [departments]);

  const rows = (employees ?? []).filter((e) => {
    const q = search.toLowerCase();
    return !q || e.full_name.toLowerCase().includes(q) || e.employee_no.toLowerCase().includes(q) || e.job_title.toLowerCase().includes(q);
  });
  const active = (employees ?? []).filter((e) => e.status === "active");
  const payroll = active.reduce((s, e) => s + num(e.basic_salary), 0);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <StatTile label="Active employees" value={String(active.length)} />
        <StatTile label="Departments" value={String(departments?.length ?? 0)} />
        {can("payroll.read") && <StatTile label="Monthly basic payroll" value={fmtMoney(payroll)} />}
      </div>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="w-full sm:w-72">
          <Input placeholder="Search name, number or title…" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        {can("hr.write") && <Button onClick={() => setEditing("new")}>Add employee</Button>}
      </div>
      <Card>
        {isLoading ? <Loading /> : !rows.length ? (
          <div className="p-6"><EmptyState title="No employees yet" description="Add your team to run payroll and manage leave." /></div>
        ) : (
          <Table>
            <thead>
              <tr><Th>No.</Th><Th>Name</Th><Th>Department</Th><Th>Title</Th><Th>Hired</Th>{can("payroll.read") && <Th>Basic</Th>}<Th>Status</Th><Th></Th></tr>
            </thead>
            <tbody>
              {rows.map((e) => (
                <tr key={e.id} className="cursor-pointer hover:bg-slate-50 dark:hover:bg-navy-700/40" onClick={() => setViewing(e)}>
                  <Td className="font-mono text-xs">{e.employee_no}</Td>
                  <Td className="font-medium">{e.full_name}</Td>
                  <Td>{deptNames.get(e.department_id ?? "") ?? "—"}</Td>
                  <Td>{e.job_title || "—"}</Td>
                  <Td>{fmtDate(e.hire_date)}</Td>
                  {can("payroll.read") && <Td className="tabular-nums">{fmtMoney(e.basic_salary)}</Td>}
                  <Td><Badge tone={STATUS_TONE[e.status]}>{humanize(e.status)}</Badge></Td>
                  <Td>
                    {can("hr.write") && (
                      <Button variant="secondary" className="px-2 py-1 text-xs" onClick={(ev) => { ev.stopPropagation(); setEditing(e); }}>
                        Edit
                      </Button>
                    )}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      {editing && (
        <EmployeeForm employee={editing === "new" ? null : editing} departments={departments ?? []} onClose={() => setEditing(null)} />
      )}
      {viewing && <EmployeeProfile employee={viewing} onClose={() => setViewing(null)} />}
    </div>
  );
}

const EMPTY: Partial<Employee> = {
  first_name: "", last_name: "", other_names: "", email: "", phone: "", gender: "", national_id: "", kra_pin: "",
  nssf_no: "", shif_no: "", department_id: null, job_title: "", employment_type: "permanent", hire_date: today(),
  basic_salary: "0", payment_method: "bank", bank_name: "", bank_branch: "", bank_account: "", mpesa_phone: "",
  has_disability_exemption: false, nssf_exempt: false, housing_levy_exempt: false, status: "active",
};

function EmployeeForm({ employee, departments, onClose }: { employee: Employee | null; departments: Department[]; onClose: () => void }) {
  const can = useCan();
  const canPay = can("payroll.write");
  const [form, setForm] = useState<Partial<Employee>>(employee ?? EMPTY);
  const [error, setError] = useState<string | null>(null);
  const create = useApiMutation("post", "/hr/employees", [["hr"]]);
  const update = useApiMutation("patch", `/hr/employees/${employee?.id}`, [["hr"]]);
  const set = (patch: Partial<Employee>) => setForm({ ...form, ...patch });
  const text = (key: keyof Employee) => ({
    value: (form[key] as string) ?? "",
    onChange: (e: React.ChangeEvent<HTMLInputElement>) => set({ [key]: e.target.value } as Partial<Employee>),
  });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const payload: Record<string, unknown> = { ...form };
    for (const k of ["id", "full_name", "employee_no"]) delete payload[k];
    if (!payload.department_id) payload.department_id = null;
    if (!payload.date_of_birth) payload.date_of_birth = null;
    if (!payload.termination_date) delete payload.termination_date;
    if (!canPay) for (const k of ["basic_salary", "bank_name", "bank_branch", "bank_account", "mpesa_phone"]) delete payload[k];
    try {
      if (employee) await update.mutateAsync(payload);
      else {
        delete payload.status;
        await create.mutateAsync(payload);
      }
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <Modal open onClose={onClose} title={employee ? `Edit ${employee.full_name}` : "Add employee"} wide>
      <form onSubmit={submit} className="space-y-5">
        <Section title="Personal">
          <Field label="First name"><Input required {...text("first_name")} /></Field>
          <Field label="Last name"><Input required {...text("last_name")} /></Field>
          <Field label="Other names"><Input {...text("other_names")} /></Field>
          <Field label="Email"><Input type="email" {...text("email")} /></Field>
          <Field label="Phone"><Input {...text("phone")} /></Field>
          <Field label="Gender">
            <Select value={form.gender ?? ""} onChange={(e) => set({ gender: e.target.value })}>
              <option value="">—</option><option value="female">Female</option><option value="male">Male</option>
            </Select>
          </Field>
          <Field label="Date of birth"><Input type="date" {...text("date_of_birth")} /></Field>
          <Field label="National ID"><Input {...text("national_id")} /></Field>
        </Section>
        <Section title="Statutory">
          <Field label="KRA PIN"><Input {...text("kra_pin")} /></Field>
          <Field label="NSSF number"><Input {...text("nssf_no")} /></Field>
          <Field label="SHIF / SHA number"><Input {...text("shif_no")} /></Field>
          <div className="flex flex-col justify-end gap-2">
            <Checkbox label="Disability tax exemption" checked={!!form.has_disability_exemption} onChange={(v) => set({ has_disability_exemption: v })} />
            <Checkbox label="NSSF exempt" checked={!!form.nssf_exempt} onChange={(v) => set({ nssf_exempt: v })} />
            <Checkbox label="Housing levy exempt" checked={!!form.housing_levy_exempt} onChange={(v) => set({ housing_levy_exempt: v })} />
          </div>
        </Section>
        <Section title="Employment">
          <Field label="Department">
            <Select value={form.department_id ?? ""} onChange={(e) => set({ department_id: e.target.value || null })}>
              <option value="">—</option>
              {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </Select>
          </Field>
          <Field label="Job title"><Input {...text("job_title")} /></Field>
          <Field label="Type">
            <Select value={form.employment_type} onChange={(e) => set({ employment_type: e.target.value as Employee["employment_type"] })}>
              {["permanent", "contract", "casual", "intern"].map((t) => <option key={t} value={t}>{humanize(t)}</option>)}
            </Select>
          </Field>
          <Field label="Hire date"><Input type="date" required {...text("hire_date")} /></Field>
          {employee && (
            <>
              <Field label="Status">
                <Select value={form.status} onChange={(e) => set({ status: e.target.value as Employee["status"] })}>
                  {["active", "suspended", "terminated"].map((t) => <option key={t} value={t}>{humanize(t)}</option>)}
                </Select>
              </Field>
              {form.status === "terminated" && <Field label="Termination date"><Input type="date" {...text("termination_date")} /></Field>}
            </>
          )}
        </Section>
        {canPay && (
          <Section title="Pay">
            <Field label="Basic salary (monthly)"><Input type="number" step="0.01" min="0" {...text("basic_salary")} /></Field>
            <Field label="Pay by">
              <Select value={form.payment_method} onChange={(e) => set({ payment_method: e.target.value as Employee["payment_method"] })}>
                <option value="bank">Bank transfer</option><option value="mpesa">M-Pesa</option><option value="cash">Cash</option>
              </Select>
            </Field>
            {form.payment_method === "bank" && (
              <>
                <Field label="Bank"><Input {...text("bank_name")} /></Field>
                <Field label="Branch"><Input {...text("bank_branch")} /></Field>
                <Field label="Account number"><Input {...text("bank_account")} /></Field>
              </>
            )}
            {form.payment_method === "mpesa" && <Field label="M-Pesa number"><Input {...text("mpesa_phone")} /></Field>}
          </Section>
        )}
        <ErrorBanner message={error} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={create.isPending || update.isPending}>{employee ? "Save changes" : "Add employee"}</Button>
        </div>
      </form>
    </Modal>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-brand">{title}</p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">{children}</div>
    </div>
  );
}

function EmployeeProfile({ employee, onClose }: { employee: Employee; onClose: () => void }) {
  const can = useCan();
  const year = new Date().getFullYear();
  const { data: balances } = useApi<LeaveBalance[]>(`/hr/employees/${employee.id}/leave-balances?year=${year}`);
  const { data: items } = useApi<PayItem[]>(can("payroll.read") ? `/hr/employees/${employee.id}/pay-items` : null);
  const add = useApiMutation("post", `/hr/employees/${employee.id}/pay-items`, [["hr"]]);
  const remove = useApiMutation<{ id: string }>("del", (b) => `/hr/pay-items/${b.id}`, [["hr"]]);
  const [kind, setKind] = useState<"earning" | "deduction">("earning");
  const [name, setName] = useState("");
  const [amount, setAmount] = useState("");
  const [flag, setFlag] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await add.mutateAsync({ kind, name, amount, taxable: kind === "earning" ? flag : true, pre_tax: kind === "deduction" ? !flag : false });
      setName("");
      setAmount("");
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const details: [string, string][] = [
    ["Employee no.", employee.employee_no], ["Job title", employee.job_title], ["Hired", fmtDate(employee.hire_date)],
    ["Email", employee.email], ["Phone", employee.phone], ["National ID", employee.national_id],
    ["KRA PIN", employee.kra_pin], ["NSSF", employee.nssf_no], ["SHIF", employee.shif_no],
  ];

  return (
    <Modal open onClose={onClose} title={employee.full_name} wide>
      <div className="space-y-6">
        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
          {details.map(([k, v]) => (
            <div key={k}><dt className="text-xs text-slate-500">{k}</dt><dd className="text-navy-900 dark:text-slate-100">{v || "—"}</dd></div>
          ))}
        </dl>

        <div>
          <h3 className="mb-2 text-sm font-semibold text-slate-500">Leave balances {year}</h3>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {balances?.map((b) => (
              <div key={b.leave_type_id} className="rounded-lg border border-slate-200 p-3 text-sm dark:border-navy-700">
                <p className="font-medium">{b.leave_type}</p>
                <p className="text-slate-500">
                  {b.remaining === null ? `${num(b.taken)} day(s) taken` : `${num(b.remaining)} of ${num(b.entitled)} days left`}
                  {num(b.pending) > 0 && ` · ${num(b.pending)} pending`}
                </p>
              </div>
            ))}
          </div>
        </div>

        {can("payroll.read") && (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-slate-500">Recurring allowances & deductions</h3>
              <Button variant="secondary" className="px-2 py-1 text-xs" onClick={() => openFile(`/hr/employees/${employee.id}/p9/pdf?year=${year}`)}>
                P9 {year}
              </Button>
            </div>
            <Table>
              <tbody>
                {items?.filter((i) => i.is_active).map((i) => (
                  <tr key={i.id}>
                    <Td><Badge tone={i.kind === "earning" ? "success" : "warning"}>{i.kind}</Badge></Td>
                    <Td>{i.name}{i.kind === "earning" && !i.taxable && " (non-taxable)"}{i.pre_tax && " (pre-tax pension)"}</Td>
                    <Td className="tabular-nums">{fmtMoney(i.amount)}</Td>
                    <Td>{can("payroll.write") && <Button variant="secondary" className="px-2 py-1 text-xs" onClick={() => remove.mutate({ id: i.id })}>Remove</Button>}</Td>
                  </tr>
                ))}
                {!items?.some((i) => i.is_active) && <tr><Td className="text-slate-400">None — basic salary only.</Td></tr>}
              </tbody>
            </Table>
            {can("payroll.write") && (
              <form onSubmit={submit} className="grid grid-cols-2 gap-2 sm:grid-cols-5">
                <Select value={kind} onChange={(e) => { setKind(e.target.value as typeof kind); setFlag(true); }}>
                  <option value="earning">Allowance</option><option value="deduction">Deduction</option>
                </Select>
                <Input required placeholder={kind === "earning" ? "e.g. House allowance" : "e.g. SACCO"} value={name} onChange={(e) => setName(e.target.value)} />
                <Input required type="number" step="0.01" min="0.01" placeholder="Amount" value={amount} onChange={(e) => setAmount(e.target.value)} />
                <div className="flex items-center">
                  <Checkbox
                    label={kind === "earning" ? "Taxable" : "After tax"}
                    checked={flag}
                    onChange={setFlag}
                  />
                </div>
                <Button type="submit" disabled={add.isPending}>Add</Button>
              </form>
            )}
            <ErrorBanner message={error} />
          </div>
        )}
      </div>
    </Modal>
  );
}

const LEAVE_TONE: Record<string, "neutral" | "success" | "warning" | "danger"> = {
  pending: "warning", approved: "success", rejected: "danger", cancelled: "neutral",
};

function LeaveTab() {
  const can = useCan();
  const [status, setStatus] = useState("pending");
  const { data: requests, isLoading } = useApi<LeaveRequest[]>(`/hr/leave-requests${status ? `?status=${status}` : ""}`);
  const { data: employees } = useApi<Employee[]>("/hr/employees?status=active");
  const { data: types } = useApi<LeaveType[]>("/hr/leave-types");
  const create = useApiMutation("post", "/hr/leave-requests", [["hr"]]);
  const decide = useApiMutation<{ id: string; status: string; note?: string }>("post", (b) => `/hr/leave-requests/${b.id}/decision`, [["hr"]]);
  const [show, setShow] = useState(false);
  const [form, setForm] = useState({ employee_id: "", leave_type_id: "", start_date: today(), end_date: today(), reason: "" });
  const [error, setError] = useState<string | null>(null);
  const empNames = useMemo(() => new Map((employees ?? []).map((e) => [e.id, e.full_name])), [employees]);
  const typeNames = useMemo(() => new Map((types ?? []).map((t) => [t.id, t.name])), [types]);

  async function act(fn: () => Promise<unknown>) {
    setError(null);
    try {
      await fn();
      return true;
    } catch (err) {
      setError(errorMessage(err));
      return false;
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="w-44">
          <Select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="pending">Pending approval</option><option value="approved">Approved</option>
            <option value="rejected">Rejected</option><option value="">All requests</option>
          </Select>
        </div>
        {can("hr.write") && <Button onClick={() => setShow(true)}>Record leave request</Button>}
      </div>
      <ErrorBanner message={!show ? error : null} />
      <Card>
        {isLoading ? <Loading /> : !requests?.length ? (
          <div className="p-6"><EmptyState title="No leave requests" /></div>
        ) : (
          <Table>
            <thead><tr><Th>Employee</Th><Th>Type</Th><Th>From</Th><Th>To</Th><Th>Days</Th><Th>Reason</Th><Th>Status</Th><Th></Th></tr></thead>
            <tbody>
              {requests.map((r) => (
                <tr key={r.id}>
                  <Td className="font-medium">{empNames.get(r.employee_id) ?? "—"}</Td>
                  <Td>{typeNames.get(r.leave_type_id) ?? "—"}</Td>
                  <Td>{fmtDate(r.start_date)}</Td>
                  <Td>{fmtDate(r.end_date)}</Td>
                  <Td>{num(r.days)}</Td>
                  <Td className="max-w-xs truncate">{r.reason || "—"}</Td>
                  <Td><Badge tone={LEAVE_TONE[r.status]}>{humanize(r.status)}</Badge></Td>
                  <Td>
                    {can("hr.write") && (
                      <div className="flex justify-end gap-1">
                        {r.status === "pending" && (
                          <>
                            <Button className="px-2 py-1 text-xs" onClick={() => act(() => decide.mutateAsync({ id: r.id, status: "approved" }))}>Approve</Button>
                            <Button variant="secondary" className="px-2 py-1 text-xs" onClick={() => act(() => decide.mutateAsync({ id: r.id, status: "rejected" }))}>Reject</Button>
                          </>
                        )}
                        {r.status === "approved" && (
                          <Button variant="secondary" className="px-2 py-1 text-xs" onClick={() => act(() => decide.mutateAsync({ id: r.id, status: "cancelled" }))}>Cancel</Button>
                        )}
                      </div>
                    )}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <Modal open={show} onClose={() => setShow(false)} title="Record leave request">
        <form
          className="space-y-3"
          onSubmit={async (e) => {
            e.preventDefault();
            if (await act(() => create.mutateAsync(form))) setShow(false);
          }}
        >
          <Field label="Employee">
            <Select required value={form.employee_id} onChange={(e) => setForm({ ...form, employee_id: e.target.value })}>
              <option value="">Select…</option>
              {employees?.map((e) => <option key={e.id} value={e.id}>{e.full_name}</option>)}
            </Select>
          </Field>
          <Field label="Leave type">
            <Select required value={form.leave_type_id} onChange={(e) => setForm({ ...form, leave_type_id: e.target.value })}>
              <option value="">Select…</option>
              {types?.map((t) => <option key={t.id} value={t.id}>{t.name}{num(t.days_per_year) ? ` (${num(t.days_per_year)} days/yr)` : ""}</option>)}
            </Select>
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="From"><Input type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} /></Field>
            <Field label="To"><Input type="date" value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} /></Field>
          </div>
          <Field label="Reason"><Input value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} /></Field>
          <p className="text-xs text-slate-400">Days are counted Monday–Friday. Unpaid leave, once approved, is deducted from that month&apos;s payroll.</p>
          <ErrorBanner message={error} />
          <div className="flex justify-end"><Button type="submit" disabled={create.isPending}>Submit</Button></div>
        </form>
      </Modal>
    </div>
  );
}

function DepartmentsTab() {
  const can = useCan();
  const { data: departments, isLoading } = useApi<Department[]>("/hr/departments");
  const { data: employees } = useApi<Employee[]>("/hr/employees?status=active");
  const create = useApiMutation("post", "/hr/departments", [["hr"]]);
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const headcount = (id: string) => employees?.filter((e) => e.department_id === id).length ?? 0;

  return (
    <div className="space-y-4">
      {can("hr.write") && (
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={async (e) => {
            e.preventDefault();
            setError(null);
            try {
              await create.mutateAsync({ name, code });
              setName("");
              setCode("");
            } catch (err) {
              setError(errorMessage(err));
            }
          }}
        >
          <Field label="Department name"><Input required value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <Field label="Code"><Input value={code} onChange={(e) => setCode(e.target.value)} /></Field>
          <Button type="submit" disabled={create.isPending}>Add department</Button>
        </form>
      )}
      <ErrorBanner message={error} />
      <Card>
        {isLoading ? <Loading /> : !departments?.length ? (
          <div className="p-6"><EmptyState title="No departments yet" /></div>
        ) : (
          <Table>
            <thead><tr><Th>Name</Th><Th>Code</Th><Th>Active staff</Th></tr></thead>
            <tbody>
              {departments.map((d) => (
                <tr key={d.id}><Td className="font-medium">{d.name}</Td><Td>{d.code || "—"}</Td><Td>{headcount(d.id)}</Td></tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}
