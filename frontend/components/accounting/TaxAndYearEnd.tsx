"use client";

import { useState } from "react";
import { CalendarCheck, Download, Lock } from "lucide-react";
import { Badge, Button, Card, ErrorBanner, Field, Input, Loading, Select, Table, Td, Th } from "@/components/om/primitives";
import { errorMessage, openFile, useApi, useApiMutation } from "@/lib/api/query";
import { fmtDate, fmtMoney, num } from "@/lib/format";
import type { Account } from "@/lib/api/types";

const REFRESH = [["accounting"]];

interface VatReport {
  start: string;
  end: string;
  sales: null | { by_rate: { rate: string; taxable: string; vat: string }[]; invoice_count: number; credit_notes_taxable: string; credit_notes_vat: string; output_vat: string };
  purchases: null | { bills: { bill_no: string; date: string; vendor: string; vendor_pin: string; vendor_reference: string; taxable: string; vat: string }[]; purchases_taxable: string; input_vat: string };
  output_vat: string;
  input_vat: string;
  net_vat: string;
}

function lastMonth(): [string, string] {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  const end = new Date(now.getFullYear(), now.getMonth(), 0);
  return [`${end.getFullYear()}-${pad(end.getMonth() + 1)}-01`, `${end.getFullYear()}-${pad(end.getMonth() + 1)}-${pad(end.getDate())}`];
}

export function VatTab({ currency }: { currency?: string }) {
  const [defaults] = useState(lastMonth);
  const [start, setStart] = useState(defaults[0]);
  const [end, setEnd] = useState(defaults[1]);
  const { data, isLoading } = useApi<VatReport>(`/accounting/reports/vat?start=${start}&end=${end}`);
  const net = num(data?.net_vat);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="From"><Input type="date" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
        <Field label="To"><Input type="date" value={end} onChange={(e) => setEnd(e.target.value)} /></Field>
        <Button variant="secondary" onClick={() => openFile(`/accounting/reports/vat/csv?start=${start}&end=${end}`, `vat-return-${start}.csv`)}><Download /> Download CSV</Button>
        <p className="text-xs text-slate-400">Defaults to last month — the return due by the 20th.</p>
      </div>
      {isLoading || !data ? <Loading /> : (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <Summary label="Output VAT (on your sales)" value={fmtMoney(data.output_vat)} />
            <Summary label="Input VAT (on your purchases)" value={fmtMoney(data.input_vat)} />
            <Summary label={net >= 0 ? "VAT to pay KRA" : "VAT credit to carry forward"} value={fmtMoney(Math.abs(net), currency)} strong />
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <p className="border-b border-slate-100 px-5 py-3 text-sm font-semibold dark:border-navy-700">Sales{data.sales ? ` · ${data.sales.invoice_count} invoice(s)` : ""}</p>
              <Table>
                <thead><tr><Th>Rate</Th><Th>Taxable value</Th><Th>VAT</Th></tr></thead>
                <tbody>
                  {data.sales?.by_rate.map((r) => (
                    <tr key={r.rate}><Td>{num(r.rate) ? `${(num(r.rate) * 100).toFixed(0)}%` : "0% / exempt"}</Td><Td>{fmtMoney(r.taxable)}</Td><Td>{fmtMoney(r.vat)}</Td></tr>
                  ))}
                  {data.sales && num(data.sales.credit_notes_taxable) > 0 && (
                    <tr><Td className="text-slate-500">Less credit notes</Td><Td>-{fmtMoney(data.sales.credit_notes_taxable)}</Td><Td>-{fmtMoney(data.sales.credit_notes_vat)}</Td></tr>
                  )}
                  {!data.sales?.by_rate.length && <tr><Td colSpan={3} className="text-slate-400">No sales in this period.</Td></tr>}
                </tbody>
              </Table>
            </Card>
            <Card>
              <p className="border-b border-slate-100 px-5 py-3 text-sm font-semibold dark:border-navy-700">Purchases with VAT</p>
              <Table>
                <thead><tr><Th>Bill</Th><Th>Supplier</Th><Th>PIN</Th><Th>Taxable</Th><Th>VAT</Th></tr></thead>
                <tbody>
                  {data.purchases?.bills.map((b) => (
                    <tr key={b.bill_no}>
                      <Td className="whitespace-nowrap">{b.bill_no}<p className="text-xs text-slate-400">{fmtDate(b.date)}</p></Td>
                      <Td>{b.vendor}</Td>
                      <Td className={`font-mono text-xs ${b.vendor_pin ? "" : "text-amber-600"}`}>{b.vendor_pin || "missing"}</Td>
                      <Td>{fmtMoney(b.taxable)}</Td><Td>{fmtMoney(b.vat)}</Td>
                    </tr>
                  ))}
                  {!data.purchases?.bills.length && <tr><Td colSpan={5} className="text-slate-400">No purchases with VAT in this period.</Td></tr>}
                </tbody>
              </Table>
            </Card>
          </div>
          <p className="text-xs text-slate-400">Input VAT is only claimable against a valid tax invoice — suppliers shown with a missing PIN should be fixed in CRM before filing. Check these figures with your accountant before submitting on iTax.</p>
        </>
      )}
    </div>
  );
}

function Summary({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className={`rounded-2xl p-5 ${strong ? "bg-navy-900 text-white" : "bg-white shadow-card ring-1 ring-slate-200/80"}`}>
      <p className={`text-xs ${strong ? "text-slate-300" : "text-slate-500"}`}>{label}</p>
      <p className="mt-1 text-2xl font-semibold tracking-tight">{value}</p>
    </div>
  );
}

const METHODS: [string, string, string][] = [
  ["cash", "Cash", "1000"],
  ["mpesa", "M-Pesa", "1010"],
  ["bank", "Bank transfer", "1020"],
  ["cheque", "Cheque", "1020"],
  ["card", "Card", "1020"],
];

export function YearEndTab({ isAdmin }: { isAdmin: boolean }) {
  const { data: status } = useApi<{ closed_years: number[]; lock_date: string | null }>("/accounting/year-end");
  const { data: settings } = useApi<{ lock_date: string | null; fiscal_year_start_month: number; payment_accounts: Record<string, string> }>("/accounting/settings");
  const { data: accounts } = useApi<Account[]>("/accounting/accounts");
  const close = useApiMutation<{ year: number }, { profit: string; entry_no: string }>("post", (b) => `/accounting/year-end/${b.year}/close`, REFRESH);
  const reopen = useApiMutation<{ year: number }>("post", (b) => `/accounting/year-end/${b.year}/reopen`, REFRESH);
  const saveLock = useApiMutation("put", "/accounting/settings", REFRESH);
  const saveAccounts = useApiMutation("put", "/accounting/settings/payment-accounts", REFRESH);
  const lastYear = new Date().getFullYear() - 1;
  const [year, setYear] = useState(lastYear);
  const [lock, setLock] = useState<string | null>(null);
  const [mapping, setMapping] = useState<Record<string, string> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function run(fn: () => Promise<unknown>) {
    setError(null);
    setNotice(null);
    try {
      await fn();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  if (!status || !settings) return <Loading />;
  const lockValue = lock ?? settings.lock_date ?? "";
  const map = mapping ?? settings.payment_accounts ?? {};
  const banks = accounts?.filter((a) => a.type === "asset" && a.subtype === "bank" && a.is_active) ?? [];

  return (
    <div className="space-y-6">
      <ErrorBanner message={error} />
      {notice && <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{notice}</p>}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="p-6">
          <h2 className="flex items-center gap-2 text-sm font-semibold"><CalendarCheck className="h-4 w-4 text-brand" /> Close a financial year</h2>
          <p className="mt-2 text-sm text-slate-500">
            Moves the year&apos;s profit or loss into Retained Earnings so income and expense accounts start the new year at zero, and locks the year so filed figures can&apos;t change. It can be reopened.
          </p>
          <div className="mt-4 flex items-end gap-3">
            <Field label="Year"><Input type="number" value={year} max={lastYear} onChange={(e) => setYear(Number(e.target.value))} /></Field>
            <Button
              disabled={!isAdmin || close.isPending || status.closed_years.includes(year)}
              onClick={() => confirm(`Close the ${year} financial year? Do this after your accountant has finished the year's adjustments.`) && run(async () => {
                const r = await close.mutateAsync({ year });
                setNotice(`${year} closed. ${num(r.profit) >= 0 ? "Profit" : "Loss"} of ${fmtMoney(Math.abs(num(r.profit)))} moved to Retained Earnings (entry ${r.entry_no}).`);
              })}
            >
              Close {year}
            </Button>
          </div>
          {!isAdmin && <p className="mt-2 text-xs text-slate-400">Only owners and admins can close a year.</p>}
          <div className="mt-5">
            <p className="text-xs font-medium text-slate-500">Closed years</p>
            {status.closed_years.length ? (
              <ul className="mt-2 divide-y divide-slate-100">
                {[...status.closed_years].reverse().map((y) => (
                  <li key={y} className="flex items-center justify-between py-2 text-sm">
                    <span className="flex items-center gap-2"><Badge tone="success">Closed</Badge>{y}</span>
                    {isAdmin && <button className="text-xs text-slate-500 hover:text-navy-900" onClick={() => confirm(`Reopen ${y}? Its figures will be editable again.`) && run(() => reopen.mutateAsync({ year: y }))}>Reopen</button>}
                  </li>
                ))}
              </ul>
            ) : <p className="mt-1 text-sm text-slate-400">None yet.</p>}
          </div>
        </Card>

        <Card className="p-6">
          <h2 className="flex items-center gap-2 text-sm font-semibold"><Lock className="h-4 w-4 text-brand" /> Lock date</h2>
          <p className="mt-2 text-sm text-slate-500">
            Nothing can be posted on or before this date — use it after filing a VAT return. Closing a year sets it for you.
          </p>
          <form className="mt-4 flex items-end gap-3" onSubmit={(e) => { e.preventDefault(); run(async () => { await saveLock.mutateAsync({ lock_date: lockValue || null, fiscal_year_start_month: settings.fiscal_year_start_month }); setNotice("Lock date saved."); }); }}>
            <Field label="Books locked through"><Input type="date" value={lockValue} onChange={(e) => setLock(e.target.value)} disabled={!isAdmin} /></Field>
            {isAdmin && <Button type="submit" variant="secondary" disabled={saveLock.isPending}>Save</Button>}
          </form>
        </Card>
      </div>

      <Card className="p-6">
        <h2 className="text-sm font-semibold">Where payments are recorded</h2>
        <p className="mt-2 max-w-3xl text-sm text-slate-500">
          Each payment method posts to its own account, so cash, M-Pesa and each bank can be reconciled separately. Have a second bank account? Add it under Chart of Accounts (type Asset, group Bank) and point a method at it.
        </p>
        <form className="mt-4 space-y-4" onSubmit={(e) => { e.preventDefault(); run(async () => { await saveAccounts.mutateAsync({ payment_accounts: map }); setNotice("Payment accounts saved."); }); }}>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            {METHODS.map(([key, label, defaultCode]) => (
              <Field key={key} label={label}>
                <Select value={map[key] ?? ""} onChange={(e) => setMapping({ ...map, [key]: e.target.value })} disabled={!isAdmin}>
                  <option value="">Default ({banks.find((b) => b.code === defaultCode)?.name ?? defaultCode})</option>
                  {banks.map((b) => <option key={b.id} value={b.id}>{b.code} · {b.name}</option>)}
                </Select>
              </Field>
            ))}
          </div>
          {isAdmin && <Button type="submit" variant="secondary" disabled={saveAccounts.isPending}>Save</Button>}
        </form>
      </Card>
    </div>
  );
}

export function ActivityTab() {
  const [area, setArea] = useState("");
  const { data, isLoading } = useApi<{ id: string; at: string; user: string; action: string; area: string; via_support: boolean }[]>(`/workspaces/activity${area ? `?area=${area}` : ""}`);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="w-48">
          <Select value={area} onChange={(e) => setArea(e.target.value)}>
            <option value="">All areas</option>
            {["sales", "purchasing", "inventory", "accounting", "hr", "crm", "assets", "manufacturing", "workspaces"].map((a) => <option key={a} value={a}>{a === "workspaces" ? "Settings & team" : a === "hr" ? "HR & payroll" : a[0].toUpperCase() + a.slice(1)}</option>)}
          </Select>
        </div>
        <p className="text-sm text-slate-500">Every change made in your business, who made it and when. Entries can&apos;t be edited or deleted.</p>
      </div>
      <Card>
        {isLoading ? <Loading /> : !data?.length ? <p className="p-6 text-sm text-slate-400">No activity recorded yet.</p> : (
          <Table>
            <thead><tr><Th>When</Th><Th>Who</Th><Th>What</Th><Th>Area</Th></tr></thead>
            <tbody>
              {data.map((e) => (
                <tr key={e.id}>
                  <Td className="whitespace-nowrap text-xs">{new Date(`${e.at}Z`).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" })}</Td>
                  <Td className="text-slate-600">{e.user}{e.via_support && <span className="ml-2"><Badge tone="warning">Support session</Badge></span>}</Td>
                  <Td className="font-medium">{e.action}</Td>
                  <Td><Badge>{e.area === "workspaces" ? "settings" : e.area}</Badge></Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}
