"use client";

import { useState } from "react";
import {
  Badge,
  Button,
  Card,
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
import { errorMessage, openFile, useApi, useApiMutation } from "@/lib/api/query";
import { fmtDate, fmtMoney, humanize, MONTHS, num } from "@/lib/format";
import type { PayrollRun, Payslip, PayslipItem, StatutoryReport } from "@/lib/api/types";

type Tab = "runs" | "calculator";

const RUN_TONE: Record<string, "neutral" | "success" | "warning"> = { draft: "neutral", approved: "warning", paid: "success" };
const REFRESH = [["hr"], ["accounting"]];

export default function PayrollPage() {
  const [tab, setTab] = useState<Tab>("runs");
  const [runId, setRunId] = useState<string | null>(null);
  return (
    <div className="space-y-6">
      <PageHeader
        title="Payroll"
        description="Monthly payroll with Kenyan statutory deductions — PAYE, NSSF, SHIF, Housing Levy and NITA."
      />
      {runId ? (
        <RunDetail runId={runId} onBack={() => setRunId(null)} />
      ) : (
        <>
          <Tabs<Tab> value={tab} onChange={setTab} tabs={[{ key: "runs", label: "Payroll runs" }, { key: "calculator", label: "Salary calculator" }]} />
          {tab === "runs" ? <RunsList onOpen={setRunId} /> : <Calculator />}
        </>
      )}
    </div>
  );
}

function RunsList({ onOpen }: { onOpen: (id: string) => void }) {
  const { data: runs, isLoading } = useApi<PayrollRun[]>("/hr/payroll/runs");
  const create = useApiMutation<Record<string, unknown>, PayrollRun>("post", "/hr/payroll/runs", REFRESH);
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [error, setError] = useState<string | null>(null);

  async function start(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const run = await create.mutateAsync({ period_year: year, period_month: month });
      onOpen(run.id);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <form onSubmit={start} className="flex flex-wrap items-end gap-3">
          <Field label="Month">
            <Select value={month} onChange={(e) => setMonth(Number(e.target.value))}>
              {MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
            </Select>
          </Field>
          <Field label="Year"><Input type="number" value={year} onChange={(e) => setYear(Number(e.target.value))} /></Field>
          <Button type="submit" disabled={create.isPending}>{create.isPending ? "Calculating…" : "Run payroll"}</Button>
          <p className="text-xs text-slate-400">Generates a draft payslip for every employee employed in the month. Nothing posts until you approve.</p>
        </form>
        <div className="mt-3"><ErrorBanner message={error} /></div>
      </Card>
      <Card>
        {isLoading ? <Loading /> : !runs?.length ? (
          <div className="p-6"><EmptyState title="No payroll runs yet" description="Add employees under Employees & Leave, then run your first payroll." /></div>
        ) : (
          <Table>
            <thead><tr><Th>Run</Th><Th>Period</Th><Th>Staff</Th><Th>Gross</Th><Th>PAYE</Th><Th>Net pay</Th><Th>Employer cost</Th><Th>Status</Th></tr></thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id} className="cursor-pointer hover:bg-slate-50 dark:hover:bg-navy-700/40" onClick={() => onOpen(r.id)}>
                  <Td className="font-medium">{r.run_no}</Td>
                  <Td>{MONTHS[r.period_month - 1]} {r.period_year}</Td>
                  <Td>{r.employee_count}</Td>
                  <Td className="tabular-nums">{fmtMoney(r.gross_pay)}</Td>
                  <Td className="tabular-nums">{fmtMoney(r.paye)}</Td>
                  <Td className="tabular-nums">{fmtMoney(r.net_pay)}</Td>
                  <Td className="tabular-nums">{fmtMoney(r.employer_cost)}</Td>
                  <Td><Badge tone={RUN_TONE[r.status]}>{humanize(r.status)}</Badge></Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}

type RunTab = "payslips" | "paye" | "nssf" | "shif" | "housing_levy" | "payments";

function RunDetail({ runId, onBack }: { runId: string; onBack: () => void }) {
  const { data: run } = useApi<PayrollRun>(`/hr/payroll/runs/${runId}`);
  const { data: payslips, isLoading } = useApi<Payslip[]>(`/hr/payroll/runs/${runId}/payslips`);
  const approve = useApiMutation("post", `/hr/payroll/runs/${runId}/approve`, REFRESH);
  const pay = useApiMutation("post", `/hr/payroll/runs/${runId}/mark-paid`, REFRESH);
  const recalc = useApiMutation("post", `/hr/payroll/runs/${runId}/recalculate`, REFRESH);
  const remove = useApiMutation("del", `/hr/payroll/runs/${runId}`, REFRESH);
  const [tab, setTab] = useState<RunTab>("payslips");
  const [editing, setEditing] = useState<Payslip | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function act(fn: () => Promise<unknown>, after?: () => void) {
    setError(null);
    try {
      await fn();
      after?.();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  if (!run) return <Loading />;
  const period = `${MONTHS[run.period_month - 1]} ${run.period_year}`;
  const csvName = (kind: string) => `${kind}-${run.period_year}-${String(run.period_month).padStart(2, "0")}.csv`;

  return (
    <div className="space-y-5">
      <button onClick={onBack} className="text-sm text-brand hover:underline">← All payroll runs</button>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-navy-900 dark:text-white">{period} payroll</h2>
          <p className="text-sm text-slate-500">
            {run.run_no} · pay date {fmtDate(run.pay_date)} · <Badge tone={RUN_TONE[run.status]}>{humanize(run.status)}</Badge>
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onClick={() => openFile(`/hr/payroll/runs/${runId}/payslips/pdf`)}>All payslips (PDF)</Button>
          {run.status === "draft" && (
            <>
              <Button variant="secondary" onClick={() => act(() => recalc.mutateAsync(undefined))}>Recalculate</Button>
              <Button variant="danger" onClick={() => confirm("Delete this draft payroll?") && act(() => remove.mutateAsync(undefined), onBack)}>Delete draft</Button>
              <Button onClick={() => confirm(`Approve ${period} payroll? This posts salaries and statutory liabilities to the ledger and locks the payslips.`) && act(() => approve.mutateAsync(undefined))}>
                Approve & post
              </Button>
            </>
          )}
          {run.status === "approved" && (
            <Button onClick={() => confirm("Mark salaries as paid? This posts the net pay out of Cash & Bank.") && act(() => pay.mutateAsync({}))}>
              Mark salaries paid
            </Button>
          )}
        </div>
      </div>
      <ErrorBanner message={error} />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
        <StatTile label="Gross pay" value={fmtMoney(run.gross_pay)} sub={`${run.employee_count} employees`} />
        <StatTile label="PAYE" value={fmtMoney(run.paye)} />
        <StatTile label="NSSF (both)" value={fmtMoney(num(run.nssf_employee) + num(run.nssf_employer))} />
        <StatTile label="SHIF" value={fmtMoney(run.shif)} />
        <StatTile label="Housing levy (both)" value={fmtMoney(num(run.housing_levy_employee) + num(run.housing_levy_employer))} />
        <StatTile label="Net pay" value={fmtMoney(run.net_pay)} sub={`Employer cost ${fmtMoney(run.employer_cost)}`} />
      </div>

      <Tabs<RunTab>
        value={tab}
        onChange={setTab}
        tabs={[
          { key: "payslips", label: "Payslips" },
          { key: "paye", label: "PAYE (P10)" },
          { key: "nssf", label: "NSSF" },
          { key: "shif", label: "SHIF" },
          { key: "housing_levy", label: "Housing Levy" },
          { key: "payments", label: "Bank / M-Pesa list" },
        ]}
      />

      {tab === "payslips" ? (
        <Card>
          {isLoading ? <Loading /> : (
            <Table>
              <thead>
                <tr><Th>No.</Th><Th>Employee</Th><Th>Days</Th><Th>Basic</Th><Th>Gross</Th><Th>NSSF</Th><Th>SHIF</Th><Th>AHL</Th><Th>PAYE</Th><Th>Other</Th><Th>Net</Th><Th></Th></tr>
              </thead>
              <tbody>
                {payslips?.map((p) => (
                  <tr key={p.id}>
                    <Td className="font-mono text-xs">{p.employee_no}</Td>
                    <Td className="font-medium">
                      {p.employee_name}
                      {p.adjustments.length > 0 && <span className="ml-1 text-xs text-brand">+{p.adjustments.length} adj.</span>}
                    </Td>
                    <Td className="text-xs">{p.days_worked}/{p.days_in_period}</Td>
                    <Td className="tabular-nums">{fmtMoney(p.basic_salary)}</Td>
                    <Td className="tabular-nums">{fmtMoney(p.gross_pay)}</Td>
                    <Td className="tabular-nums">{fmtMoney(p.nssf_employee)}</Td>
                    <Td className="tabular-nums">{fmtMoney(p.shif)}</Td>
                    <Td className="tabular-nums">{fmtMoney(p.housing_levy_employee)}</Td>
                    <Td className="tabular-nums">{fmtMoney(p.paye)}</Td>
                    <Td className="tabular-nums">{fmtMoney(p.other_deductions)}</Td>
                    <Td className="font-semibold tabular-nums">{fmtMoney(p.net_pay)}</Td>
                    <Td>
                      <div className="flex justify-end gap-1">
                        {run.status === "draft" && (
                          <Button variant="secondary" className="px-2 py-1 text-xs" onClick={() => setEditing(p)}>Adjust</Button>
                        )}
                        <Button variant="secondary" className="px-2 py-1 text-xs" onClick={() => openFile(`/hr/payroll/payslips/${p.id}/pdf`)}>PDF</Button>
                      </div>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>
      ) : (
        <StatutoryTab runId={runId} kind={tab} onCsv={() => openFile(`/hr/payroll/runs/${runId}/reports/${tab}/csv`, csvName(tab))} />
      )}

      {editing && <AdjustmentsModal payslip={editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

function StatutoryTab({ runId, kind, onCsv }: { runId: string; kind: string; onCsv: () => void }) {
  const { data, isLoading } = useApi<StatutoryReport>(`/hr/payroll/runs/${runId}/reports/${kind}`);
  if (isLoading || !data) return <Loading />;
  const isMoney = (key: string) => key in data.totals;
  return (
    <div className="space-y-3">
      <div className="flex justify-end"><Button variant="secondary" onClick={onCsv}>Download CSV</Button></div>
      <Card>
        <Table>
          <thead><tr>{data.columns.map((c) => <Th key={c.key}>{c.label}</Th>)}</tr></thead>
          <tbody>
            {data.rows.map((row, i) => (
              <tr key={i}>
                {data.columns.map((c) => (
                  <Td key={c.key} className={isMoney(c.key) ? "tabular-nums" : ""}>
                    {isMoney(c.key) ? fmtMoney(row[c.key]) : String(row[c.key] || "—")}
                  </Td>
                ))}
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              {data.columns.map((c, i) => (
                <Td key={c.key} className="font-semibold tabular-nums">{isMoney(c.key) ? fmtMoney(data.totals[c.key]) : i === 0 ? "Total" : ""}</Td>
              ))}
            </tr>
          </tfoot>
        </Table>
      </Card>
    </div>
  );
}

function AdjustmentsModal({ payslip, onClose }: { payslip: Payslip; onClose: () => void }) {
  const save = useApiMutation("put", `/hr/payroll/payslips/${payslip.id}/adjustments`, REFRESH);
  const [items, setItems] = useState<PayslipItem[]>(
    payslip.adjustments.map((a) => ({ ...a, kind: a.kind ?? "earning" }))
  );
  const [error, setError] = useState<string | null>(null);
  const blank: PayslipItem = { kind: "earning", name: "", amount: "", taxable: true, pre_tax: false };

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await save.mutateAsync({
        adjustments: items.filter((i) => i.name && num(i.amount) > 0).map((i) => ({
          kind: i.kind, name: i.name, amount: i.amount, taxable: i.taxable ?? true, pre_tax: i.pre_tax ?? false,
        })),
      });
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <Modal open onClose={onClose} title={`One-off items — ${payslip.employee_name}`}>
      <form onSubmit={submit} className="space-y-3">
        <p className="text-sm text-slate-500">Overtime, bonuses, commissions, salary advance recovery — for this month only. Taxes are recomputed.</p>
        {items.map((item, i) => (
          <div key={i} className="grid grid-cols-12 gap-2">
            <div className="col-span-3">
              <Select value={item.kind} onChange={(e) => setItems(items.map((x, j) => (j === i ? { ...x, kind: e.target.value as "earning" | "deduction" } : x)))}>
                <option value="earning">Earning</option><option value="deduction">Deduction</option>
              </Select>
            </div>
            <div className="col-span-5">
              <Input placeholder="e.g. Overtime" value={item.name} onChange={(e) => setItems(items.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} />
            </div>
            <div className="col-span-3">
              <Input type="number" step="0.01" min="0" placeholder="Amount" value={item.amount} onChange={(e) => setItems(items.map((x, j) => (j === i ? { ...x, amount: e.target.value } : x)))} />
            </div>
            <button type="button" className="col-span-1 text-slate-400 hover:text-red-600" onClick={() => setItems(items.filter((_, j) => j !== i))}>✕</button>
          </div>
        ))}
        <Button type="button" variant="secondary" className="px-3 py-1.5 text-xs" onClick={() => setItems([...items, { ...blank }])}>+ Add item</Button>
        <ErrorBanner message={error} />
        <div className="flex justify-end"><Button type="submit" disabled={save.isPending}>Save & recalculate</Button></div>
      </form>
    </Modal>
  );
}

interface CalcResult {
  gross_pay: string; nssf_employee: string; shif: string; housing_levy_employee: string; taxable_pay: string;
  paye_before_relief: string; personal_relief: string; paye: string; net_pay: string; employer_cost: string;
  nssf_employer: string; housing_levy_employer: string; nita: string;
}

function Calculator() {
  const [basic, setBasic] = useState("50000");
  const [allowances, setAllowances] = useState("0");
  const [nonTaxable, setNonTaxable] = useState("0");
  const [pension, setPension] = useState("0");
  const calc = useApiMutation<Record<string, string>, CalcResult>("post", "/hr/payroll/calculator");
  const r = calc.data;

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card className="p-6">
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            calc.mutate({ basic_salary: basic || "0", taxable_allowances: allowances || "0", non_taxable_allowances: nonTaxable || "0", pension_contribution: pension || "0" });
          }}
        >
          <Field label="Basic salary (monthly)"><Input type="number" min="0" step="0.01" value={basic} onChange={(e) => setBasic(e.target.value)} /></Field>
          <Field label="Taxable allowances"><Input type="number" min="0" step="0.01" value={allowances} onChange={(e) => setAllowances(e.target.value)} /></Field>
          <Field label="Non-taxable allowances"><Input type="number" min="0" step="0.01" value={nonTaxable} onChange={(e) => setNonTaxable(e.target.value)} /></Field>
          <Field label="Pension contribution (pre-tax)"><Input type="number" min="0" step="0.01" value={pension} onChange={(e) => setPension(e.target.value)} /></Field>
          <Button type="submit" disabled={calc.isPending}>Calculate</Button>
        </form>
      </Card>
      {r && (
        <Card className="p-6">
          <dl className="space-y-1.5 text-sm">
            {([
              ["Gross pay", r.gross_pay], ["NSSF", r.nssf_employee], ["SHIF", r.shif], ["Housing levy", r.housing_levy_employee],
              ["Taxable pay", r.taxable_pay], ["Tax charged", r.paye_before_relief], ["Personal relief", r.personal_relief], ["PAYE", r.paye],
            ] as [string, string][]).map(([k, v]) => (
              <div key={k} className="flex justify-between"><dt className="text-slate-500">{k}</dt><dd className="tabular-nums">{fmtMoney(v)}</dd></div>
            ))}
            <div className="flex justify-between border-t border-slate-200 pt-2 text-base font-semibold dark:border-navy-700">
              <dt>Net pay</dt><dd className="tabular-nums">{fmtMoney(r.net_pay)}</dd>
            </div>
            <div className="flex justify-between pt-3 text-slate-500">
              <dt>Cost to employer (incl. NSSF {fmtMoney(r.nssf_employer)}, AHL {fmtMoney(r.housing_levy_employer)}, NITA {fmtMoney(r.nita)})</dt>
              <dd className="tabular-nums font-medium text-navy-900 dark:text-white">{fmtMoney(r.employer_cost)}</dd>
            </div>
          </dl>
        </Card>
      )}
    </div>
  );
}
