"use client";

import { Fragment, useState } from "react";
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
  Table,
  Tabs,
  Td,
  Th,
} from "@/components/om/primitives";
import { BankingTab } from "@/components/accounting/BankingTab";
import { VatTab, YearEndTab } from "@/components/accounting/TaxAndYearEnd";
import { useBranding, useMe } from "@/lib/api/hooks";
import { errorMessage, useApi, useApiMutation } from "@/lib/api/query";
import { fmtDate, fmtMoney, humanize, MONTHS, num, today, yearStart } from "@/lib/format";
import type {
  Account,
  BalanceSheet,
  GeneralLedger,
  JournalEntryRow,
  ProfitAndLoss,
  ReportLine,
  TrialBalanceRow,
} from "@/lib/api/types";

type Tab = "pnl" | "bs" | "tb" | "gl" | "journals" | "bank" | "vat" | "coa" | "budgets" | "settings";

const TYPE_TONE: Record<string, "neutral" | "success" | "warning" | "danger"> = {
  asset: "success",
  liability: "danger",
  equity: "neutral",
  revenue: "success",
  expense: "warning",
};

export default function AccountingPage() {
  const [tab, setTab] = useState<Tab>("pnl");
  const { data: branding } = useBranding();
  const { data: me } = useMe();
  const isAdmin = !!me?.permissions.includes("*");
  const canWrite = isAdmin || !!me?.permissions.includes("accounting.write");
  const currency = branding?.currency;
  return (
    <div className="space-y-6">
      <PageHeader
        title="Accounting"
        description="Double-entry general ledger — sales, purchasing, inventory, payroll and assets post here automatically."
      />
      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        tabs={[
          { key: "pnl", label: "Profit & Loss" },
          { key: "bs", label: "Balance Sheet" },
          { key: "tb", label: "Trial Balance" },
          { key: "gl", label: "General Ledger" },
          { key: "journals", label: "Journal Entries" },
          { key: "bank", label: "Banking" },
          { key: "vat", label: "VAT Return" },
          { key: "coa", label: "Chart of Accounts" },
          { key: "budgets", label: "Budgets" },
          { key: "settings", label: "Year-end & Settings" },
        ]}
      />
      {tab === "pnl" && <PnlTab currency={currency} />}
      {tab === "bs" && <BalanceSheetTab currency={currency} />}
      {tab === "tb" && <TrialBalanceTab />}
      {tab === "gl" && <LedgerTab />}
      {tab === "journals" && <JournalsTab />}
      {tab === "coa" && <ChartTab />}
      {tab === "budgets" && <BudgetsTab />}
      {tab === "bank" && <BankingTab canWrite={canWrite} />}
      {tab === "vat" && <VatTab currency={currency} />}
      {tab === "settings" && <YearEndTab isAdmin={isAdmin} />}
    </div>
  );
}

function StatementSection({ title, lines, total, negate }: { title: string; lines: ReportLine[]; total: string; negate?: boolean }) {
  if (!lines.length && num(total) === 0) return null;
  return (
    <>
      <tr>
        <Td colSpan={2} className="bg-slate-50 pt-4 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:bg-navy-900">
          {title}
        </Td>
      </tr>
      {lines.map((l) => (
        <tr key={`${l.code}-${l.name}`}>
          <Td className="pl-8">{l.code ? `${l.code} · ` : ""}{l.name}</Td>
          <Td className="text-right tabular-nums">{fmtMoney(l.amount)}</Td>
        </tr>
      ))}
      <tr>
        <Td className="font-medium">Total {title.toLowerCase()}</Td>
        <Td className="text-right font-medium tabular-nums">{negate ? `(${fmtMoney(total)})` : fmtMoney(total)}</Td>
      </tr>
    </>
  );
}

function TotalRow({ label, value, strong, currency }: { label: string; value: string; strong?: boolean; currency?: string }) {
  const n = num(value);
  return (
    <tr className={strong ? "bg-brand/5" : ""}>
      <Td className={strong ? "text-base font-semibold" : "font-semibold"}>{label}</Td>
      <Td className={`text-right tabular-nums ${strong ? "text-base font-semibold" : "font-semibold"} ${n < 0 ? "text-red-600" : ""}`}>
        {fmtMoney(value, strong ? currency : undefined)}
      </Td>
    </tr>
  );
}

function PnlTab({ currency }: { currency?: string }) {
  const [start, setStart] = useState(yearStart());
  const [end, setEnd] = useState(today());
  const { data, isLoading } = useApi<ProfitAndLoss>(`/accounting/reports/profit-and-loss?start=${start}&end=${end}`);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-3">
        <Field label="From"><Input type="date" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
        <Field label="To"><Input type="date" value={end} onChange={(e) => setEnd(e.target.value)} /></Field>
      </div>
      <Card className="max-w-3xl">
        {isLoading || !data ? (
          <Loading />
        ) : (
          <Table>
            <tbody>
              <StatementSection title="Revenue" lines={data.revenue} total={data.total_revenue} />
              <StatementSection title="Cost of sales" lines={data.cost_of_sales} total={data.total_cost_of_sales} negate />
              <TotalRow label={`Gross profit (${num(data.gross_margin_pct).toFixed(1)}% margin)`} value={data.gross_profit} />
              <StatementSection title="Operating expenses" lines={data.operating_expenses} total={data.total_operating_expenses} negate />
              <TotalRow label="Operating profit" value={data.operating_profit} />
              <StatementSection title="Other income" lines={data.other_income} total={data.total_other_income} />
              <TotalRow label="Net profit" value={data.net_profit} strong currency={currency} />
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}

function BalanceSheetTab({ currency }: { currency?: string }) {
  const [asOf, setAsOf] = useState(today());
  const { data, isLoading } = useApi<BalanceSheet>(`/accounting/reports/balance-sheet?as_of=${asOf}`);
  const sum = (lines: ReportLine[]) => String(lines.reduce((s, l) => s + num(l.amount), 0));
  return (
    <div className="space-y-4">
      <div className="flex items-end gap-3">
        <Field label="As of"><Input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} /></Field>
        {data && <Badge tone={data.balanced ? "success" : "danger"}>{data.balanced ? "Balanced" : "Out of balance"}</Badge>}
      </div>
      {isLoading || !data ? (
        <Loading />
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Card>
            <Table>
              <tbody>
                <StatementSection title="Current assets" lines={data.current_assets} total={sum(data.current_assets)} />
                <StatementSection title="Fixed assets" lines={data.fixed_assets} total={sum(data.fixed_assets)} />
                <TotalRow label="Total assets" value={data.total_assets} strong currency={currency} />
              </tbody>
            </Table>
          </Card>
          <Card>
            <Table>
              <tbody>
                <StatementSection title="Current liabilities" lines={data.current_liabilities} total={sum(data.current_liabilities)} />
                <StatementSection title="Long-term liabilities" lines={data.long_term_liabilities} total={sum(data.long_term_liabilities)} />
                <TotalRow label="Total liabilities" value={data.total_liabilities} />
                <StatementSection title="Equity" lines={data.equity} total={data.total_equity} />
                <TotalRow
                  label="Liabilities + equity"
                  value={String(num(data.total_liabilities) + num(data.total_equity))}
                  strong
                  currency={currency}
                />
              </tbody>
            </Table>
          </Card>
        </div>
      )}
    </div>
  );
}

function TrialBalanceTab() {
  const [asOf, setAsOf] = useState(today());
  const { data, isLoading } = useApi<TrialBalanceRow[]>(`/accounting/trial-balance?as_of=${asOf}`);
  const rows = data?.filter((r) => num(r.debit) || num(r.credit)) ?? [];
  const debit = rows.reduce((s, r) => s + num(r.debit), 0);
  const credit = rows.reduce((s, r) => s + num(r.credit), 0);
  return (
    <div className="space-y-4">
      <div className="flex items-end gap-3">
        <Field label="As of"><Input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} /></Field>
        {data && <Badge tone={Math.abs(debit - credit) < 0.005 ? "success" : "danger"}>{Math.abs(debit - credit) < 0.005 ? "Balanced" : "Out of balance"}</Badge>}
      </div>
      <Card>
        {isLoading ? (
          <Loading />
        ) : !rows.length ? (
          <div className="p-6"><EmptyState title="No postings yet" /></div>
        ) : (
          <Table>
            <thead>
              <tr><Th>Code</Th><Th>Account</Th><Th>Type</Th><Th>Debit</Th><Th>Credit</Th></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.code}>
                  <Td>{r.code}</Td>
                  <Td>{r.name}</Td>
                  <Td><Badge tone={TYPE_TONE[r.type]}>{r.type}</Badge></Td>
                  <Td className="tabular-nums">{num(r.debit) ? fmtMoney(r.debit) : ""}</Td>
                  <Td className="tabular-nums">{num(r.credit) ? fmtMoney(r.credit) : ""}</Td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <Td className="font-semibold">Total</Td><Td>{""}</Td><Td>{""}</Td>
                <Td className="font-semibold tabular-nums">{fmtMoney(debit)}</Td>
                <Td className="font-semibold tabular-nums">{fmtMoney(credit)}</Td>
              </tr>
            </tfoot>
          </Table>
        )}
      </Card>
    </div>
  );
}

function LedgerTab() {
  const { data: accounts } = useApi<Account[]>("/accounting/accounts");
  const [accountId, setAccountId] = useState("");
  const [start, setStart] = useState(yearStart());
  const [end, setEnd] = useState(today());
  const { data, isLoading } = useApi<GeneralLedger>(
    accountId ? `/accounting/reports/general-ledger/${accountId}?start=${start}&end=${end}` : null
  );
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-3">
        <div className="w-72">
          <Field label="Account">
            <Select value={accountId} onChange={(e) => setAccountId(e.target.value)}>
              <option value="">Select an account…</option>
              {accounts?.map((a) => <option key={a.id} value={a.id}>{a.code} · {a.name}</option>)}
            </Select>
          </Field>
        </div>
        <Field label="From"><Input type="date" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
        <Field label="To"><Input type="date" value={end} onChange={(e) => setEnd(e.target.value)} /></Field>
      </div>
      {!accountId ? (
        <EmptyState title="Pick an account" description="See every posting with a running balance." />
      ) : isLoading || !data ? (
        <Loading />
      ) : (
        <Card>
          <Table>
            <thead>
              <tr><Th>Date</Th><Th>Entry</Th><Th>Description</Th><Th>Source</Th><Th>Debit</Th><Th>Credit</Th><Th>Balance</Th></tr>
            </thead>
            <tbody>
              <tr>
                <Td>{fmtDate(start)}</Td><Td>{""}</Td><Td className="font-medium">Opening balance</Td><Td>{""}</Td><Td>{""}</Td><Td>{""}</Td>
                <Td className="tabular-nums font-medium">{fmtMoney(data.opening_balance)}</Td>
              </tr>
              {data.lines.map((l, i) => (
                <tr key={`${l.entry_id}-${i}`}>
                  <Td>{fmtDate(l.date)}</Td>
                  <Td className="font-mono text-xs">{l.entry_no}</Td>
                  <Td>{l.memo}</Td>
                  <Td className="text-xs text-slate-500">{humanize(l.source_type)}</Td>
                  <Td className="tabular-nums">{num(l.debit) ? fmtMoney(l.debit) : ""}</Td>
                  <Td className="tabular-nums">{num(l.credit) ? fmtMoney(l.credit) : ""}</Td>
                  <Td className="tabular-nums">{fmtMoney(l.balance)}</Td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <Td className="font-semibold" colSpan={6}>Closing balance</Td>
                <Td className="font-semibold tabular-nums">{fmtMoney(data.closing_balance)}</Td>
              </tr>
            </tfoot>
          </Table>
        </Card>
      )}
    </div>
  );
}

interface DraftLine { account_id: string; debit: string; credit: string; memo: string }

function JournalsTab() {
  const [source, setSource] = useState("");
  const { data: entries, isLoading } = useApi<JournalEntryRow[]>(`/accounting/journal-entries?limit=200${source ? `&source_type=${source}` : ""}`);
  const { data: accounts } = useApi<Account[]>("/accounting/accounts");
  const post = useApiMutation("post", "/accounting/journal-entries", [["accounting"]]);
  const reverse = useApiMutation<{ id: string; date: string }>("post", (b) => `/accounting/journal-entries/${b.id}/reverse`, [["accounting"]]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [date, setDate] = useState(today());
  const [memo, setMemo] = useState("");
  const blank = (): DraftLine => ({ account_id: "", debit: "", credit: "", memo: "" });
  const [lines, setLines] = useState<DraftLine[]>([blank(), blank()]);
  const totalDebit = lines.reduce((s, l) => s + num(l.debit), 0);
  const totalCredit = lines.reduce((s, l) => s + num(l.credit), 0);
  const balanced = totalDebit > 0 && Math.abs(totalDebit - totalCredit) < 0.005;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await post.mutateAsync({
        date,
        memo,
        lines: lines.filter((l) => l.account_id && (num(l.debit) || num(l.credit))).map((l) => ({
          account_id: l.account_id, debit: l.debit || "0", credit: l.credit || "0", memo: l.memo,
        })),
      });
      setShowNew(false);
      setLines([blank(), blank()]);
      setMemo("");
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="w-56">
          <Field label="Source">
            <Select value={source} onChange={(e) => setSource(e.target.value)}>
              <option value="">All sources</option>
              {["manual", "sales_invoice", "payment_received", "delivery", "goods_receipt", "vendor_bill", "payment_made",
                "credit_note", "payroll_run", "payroll_payment", "depreciation", "asset_acquisition", "asset_disposal",
                "work_order", "stock_adjustment", "stock_opening", "reversal"].map((s) => (
                <option key={s} value={s}>{humanize(s)}</option>
              ))}
            </Select>
          </Field>
        </div>
        <Button onClick={() => setShowNew(true)}>New journal entry</Button>
      </div>
      <ErrorBanner message={!showNew ? error : null} />
      <Card>
        {isLoading ? (
          <Loading />
        ) : !entries?.length ? (
          <div className="p-6"><EmptyState title="No journal entries" /></div>
        ) : (
          <Table>
            <thead>
              <tr><Th>Entry</Th><Th>Date</Th><Th>Description</Th><Th>Source</Th><Th>Amount</Th><Th></Th></tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <Fragment key={e.id}>
                  <tr className="cursor-pointer hover:bg-slate-50 dark:hover:bg-navy-700/40" onClick={() => setExpanded(expanded === e.id ? null : e.id)}>
                    <Td className="font-mono text-xs">{e.entry_no}</Td>
                    <Td>{fmtDate(e.date)}</Td>
                    <Td>{e.memo}</Td>
                    <Td>
                      <span className="text-xs text-slate-500">{humanize(e.source_type)}</span>
                      {e.reversed_by_id && <Badge tone="danger">Reversed</Badge>}
                    </Td>
                    <Td className="tabular-nums">{fmtMoney(e.total)}</Td>
                    <Td>
                      {!e.reversed_by_id && !e.reversal_of_id && (
                        <Button
                          variant="secondary"
                          className="px-2 py-1 text-xs"
                          onClick={async (ev) => {
                            ev.stopPropagation();
                            if (!confirm(`Post a reversing entry for ${e.entry_no} dated today?`)) return;
                            try {
                              await reverse.mutateAsync({ id: e.id, date: today() });
                            } catch (err) {
                              setError(errorMessage(err));
                            }
                          }}
                        >
                          Reverse
                        </Button>
                      )}
                    </Td>
                  </tr>
                  {expanded === e.id &&
                    e.lines.map((l, i) => (
                      <tr key={i} className="bg-slate-50 text-xs dark:bg-navy-900">
                        <Td>{""}</Td>
                        <Td colSpan={2}>{l.account_code} · {l.account_name}{l.memo && <span className="text-slate-400"> — {l.memo}</span>}</Td>
                        <Td className="tabular-nums">{num(l.debit) ? `Dr ${fmtMoney(l.debit)}` : ""}</Td>
                        <Td className="tabular-nums">{num(l.credit) ? `Cr ${fmtMoney(l.credit)}` : ""}</Td>
                        <Td>{""}</Td>
                      </tr>
                    ))}
                </Fragment>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <Modal open={showNew} onClose={() => setShowNew(false)} title="New journal entry" wide>
        <form onSubmit={submit} className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Field label="Date"><Input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field>
            <div className="sm:col-span-2"><Field label="Description"><Input required value={memo} onChange={(e) => setMemo(e.target.value)} /></Field></div>
          </div>
          {lines.map((l, i) => (
            <div key={i} className="grid grid-cols-2 gap-2 sm:grid-cols-12">
              <div className="col-span-2 sm:col-span-5">
                <Select value={l.account_id} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, account_id: e.target.value } : x)))}>
                  <option value="">Account…</option>
                  {accounts?.filter((a) => a.is_active).map((a) => <option key={a.id} value={a.id}>{a.code} · {a.name}</option>)}
                </Select>
              </div>
              <div className="sm:col-span-2">
                <Input type="number" step="0.01" min="0" placeholder="Debit" value={l.debit}
                  onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, debit: e.target.value, credit: e.target.value ? "" : x.credit } : x)))} />
              </div>
              <div className="sm:col-span-2">
                <Input type="number" step="0.01" min="0" placeholder="Credit" value={l.credit}
                  onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, credit: e.target.value, debit: e.target.value ? "" : x.debit } : x)))} />
              </div>
              <div className="col-span-2 sm:col-span-3">
                <Input placeholder="Line memo" value={l.memo} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, memo: e.target.value } : x)))} />
              </div>
            </div>
          ))}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Button type="button" variant="secondary" className="px-3 py-1.5 text-xs" onClick={() => setLines([...lines, blank()])}>+ Add line</Button>
            <p className={`text-sm tabular-nums ${balanced ? "text-emerald-600" : "text-amber-600"}`}>
              Debits {fmtMoney(totalDebit)} · Credits {fmtMoney(totalCredit)} {balanced ? "✓ balanced" : "— must balance"}
            </p>
          </div>
          <ErrorBanner message={error} />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setShowNew(false)}>Cancel</Button>
            <Button type="submit" disabled={!balanced || post.isPending}>Post entry</Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}

const SUBTYPES: Record<Account["type"], string[]> = {
  asset: ["bank", "current_asset", "fixed_asset"],
  liability: ["current_liability", "long_term_liability"],
  equity: ["equity"],
  revenue: ["operating_revenue", "other_income"],
  expense: ["cost_of_sales", "operating_expense"],
};

function ChartTab() {
  const { data: accounts, isLoading } = useApi<Account[]>("/accounting/accounts");
  const create = useApiMutation("post", "/accounting/accounts", [["accounting"]]);
  const update = useApiMutation<{ id: string; is_active: boolean }>("patch", (b) => `/accounting/accounts/${b.id}`, [["accounting"]]);
  const [show, setShow] = useState(false);
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [type, setType] = useState<Account["type"]>("expense");
  const [subtype, setSubtype] = useState("operating_expense");
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await create.mutateAsync({ code, name, type, subtype });
      setShow(false);
      setCode("");
      setName("");
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-end"><Button onClick={() => setShow(true)}>New account</Button></div>
      <Card>
        {isLoading ? <Loading /> : (
          <Table>
            <thead><tr><Th>Code</Th><Th>Name</Th><Th>Type</Th><Th>Group</Th><Th>Status</Th><Th></Th></tr></thead>
            <tbody>
              {accounts?.map((a) => (
                <tr key={a.id} className={a.is_active ? "" : "opacity-50"}>
                  <Td className="font-mono">{a.code}</Td>
                  <Td>{a.name}{a.is_system && <span className="ml-2 text-xs text-slate-400">system</span>}</Td>
                  <Td><Badge tone={TYPE_TONE[a.type]}>{a.type}</Badge></Td>
                  <Td className="text-xs text-slate-500">{humanize(a.subtype || "—")}</Td>
                  <Td>{a.is_active ? "Active" : "Inactive"}</Td>
                  <Td>
                    {!a.is_system && (
                      <Button variant="secondary" className="px-2 py-1 text-xs" onClick={() => update.mutate({ id: a.id, is_active: !a.is_active })}>
                        {a.is_active ? "Deactivate" : "Activate"}
                      </Button>
                    )}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <Modal open={show} onClose={() => setShow(false)} title="New account">
        <form onSubmit={submit} className="space-y-3">
          <div className="grid grid-cols-3 gap-3">
            <Field label="Code"><Input required value={code} onChange={(e) => setCode(e.target.value)} placeholder="6210" /></Field>
            <div className="col-span-2"><Field label="Name"><Input required value={name} onChange={(e) => setName(e.target.value)} placeholder="Rent" /></Field></div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Type">
              <Select value={type} onChange={(e) => { const t = e.target.value as Account["type"]; setType(t); setSubtype(SUBTYPES[t][0]); }}>
                {Object.keys(SUBTYPES).map((t) => <option key={t} value={t}>{humanize(t)}</option>)}
              </Select>
            </Field>
            <Field label="Report group">
              <Select value={subtype} onChange={(e) => setSubtype(e.target.value)}>
                {SUBTYPES[type].map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
              </Select>
            </Field>
          </div>
          <ErrorBanner message={error} />
          <div className="flex justify-end"><Button type="submit" disabled={create.isPending}>Create account</Button></div>
        </form>
      </Modal>
    </div>
  );
}

interface BudgetRow {
  account_id: string;
  code: string;
  name: string;
  months: { month: number; budget: string; actual: string; variance: string }[];
  total_budget: string;
  total_actual: string;
  variance: string;
}

function BudgetsTab() {
  const [year, setYear] = useState(new Date().getFullYear());
  const { data: rows, isLoading } = useApi<BudgetRow[]>(`/accounting/reports/budget-vs-actual?year=${year}`);
  const { data: accounts } = useApi<Account[]>("/accounting/accounts");
  const save = useApiMutation("put", "/accounting/budgets", [["accounting"]]);
  const [accountId, setAccountId] = useState("");
  const [monthly, setMonthly] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await save.mutateAsync({ account_id: accountId, year, monthly_amounts: Array(12).fill(monthly || "0") });
      setMonthly("");
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <div className="space-y-4">
      <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
        <Field label="Year"><Input type="number" value={year} onChange={(e) => setYear(Number(e.target.value))} /></Field>
        <div className="w-72">
          <Field label="Account">
            <Select required value={accountId} onChange={(e) => setAccountId(e.target.value)}>
              <option value="">Select…</option>
              {accounts?.filter((a) => a.type === "revenue" || a.type === "expense").map((a) => (
                <option key={a.id} value={a.id}>{a.code} · {a.name}</option>
              ))}
            </Select>
          </Field>
        </div>
        <Field label="Monthly budget"><Input type="number" step="0.01" required value={monthly} onChange={(e) => setMonthly(e.target.value)} /></Field>
        <Button type="submit" disabled={save.isPending}>Set budget</Button>
      </form>
      <ErrorBanner message={error} />
      <Card>
        {isLoading ? <Loading /> : !rows?.length ? (
          <div className="p-6"><EmptyState title={`No budgets for ${year}`} description="Set a monthly budget for revenue or expense accounts to track variance." /></div>
        ) : (
          <Table>
            <thead>
              <tr><Th>Account</Th>{MONTHS.map((m) => <Th key={m}>{m.slice(0, 3)}</Th>)}<Th>Year</Th></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <Fragment key={r.account_id}>
                  <tr>
                    <Td className="font-medium">{r.code} · {r.name}</Td>
                    {r.months.map((m) => (
                      <Td key={m.month} className="text-xs tabular-nums">
                        <div>{fmtMoney(m.actual)}</div>
                        <div className="text-slate-400">/ {fmtMoney(m.budget)}</div>
                      </Td>
                    ))}
                    <Td className="text-xs tabular-nums">
                      <div className="font-semibold">{fmtMoney(r.total_actual)}</div>
                      <div className={num(r.variance) < 0 ? "text-red-600" : "text-emerald-600"}>{fmtMoney(r.variance)}</div>
                    </Td>
                  </tr>
                </Fragment>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <p className="text-xs text-slate-400">Each month shows actual / budget. Year column shows actual and variance (actual − budget).</p>
    </div>
  );
}
