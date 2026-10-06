"use client";

import Link from "next/link";
import { ArrowRight, Boxes, HandCoins, Landmark, Receipt, ScrollText, ShoppingCart, Store, Wallet } from "lucide-react";
import { useBranding, useMe } from "@/lib/api/hooks";
import { BarChart, Card, EmptyState, SectionTitle, StatTile, Table, Td, Th } from "@/components/om/primitives";
import { useApi } from "@/lib/api/query";
import { fmtMoney, monthStart, num, today } from "@/lib/format";
import type { AgingReport, ProfitAndLoss, TrendPoint, TrialBalanceRow } from "@/lib/api/types";

const MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export default function DashboardPage() {
  const { data: me } = useMe();
  const { data: branding } = useBranding();
  const features = new Set(me?.features ?? []);
  const can = (p: string) => !!me && (me.permissions.includes("*") || me.permissions.includes(p));
  // Staff without ledger access get the quick links, not a wall of 403s.
  const hasAccounting = features.has("accounting") && can("accounting.read");
  const hasSales = features.has("sales") && can("sales.read");
  const currency = branding?.currency;

  const { data: tb } = useApi<TrialBalanceRow[]>(hasAccounting ? "/accounting/trial-balance" : null);
  const { data: pnl } = useApi<ProfitAndLoss>(
    hasAccounting ? `/accounting/reports/profit-and-loss?start=${monthStart()}&end=${today()}` : null
  );
  const { data: trend } = useApi<TrendPoint[]>(hasAccounting ? "/accounting/reports/monthly-trend?months=12" : null);
  const { data: aging } = useApi<AgingReport>(hasSales ? "/sales/reports/ar-aging" : null);

  const balance = (code: string, natural: "debit" | "credit") => {
    const row = tb?.find((r) => r.code === code);
    if (!row) return 0;
    return natural === "debit" ? num(row.debit) - num(row.credit) : num(row.credit) - num(row.debit);
  };

  const greeting = new Date().getHours() < 12 ? "Good morning" : new Date().getHours() < 17 ? "Good afternoon" : "Good evening";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-navy-900 dark:text-white">{greeting}</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          {branding?.name ?? "Your business"} at a glance — {new Date().toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" })}
        </p>
      </div>

      {hasAccounting ? (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
            <StatTile label="Cash & bank" icon={<Landmark />} value={fmtMoney(balance("1000", "debit"))} sub={currency} />
            <StatTile label="Receivables" icon={<HandCoins />} tone="emerald" value={fmtMoney(balance("1100", "debit"))} sub={aging ? `${fmtMoney(num(aging.totals.total) - num(aging.totals.current))} overdue` : undefined} />
            <StatTile label="Payables" icon={<ScrollText />} tone="rose" value={fmtMoney(balance("2100", "credit"))} />
            <StatTile label="Inventory value" icon={<Boxes />} tone="violet" value={fmtMoney(balance("1200", "debit"))} />
            <StatTile label="VAT payable" icon={<Receipt />} tone="amber" value={fmtMoney(balance("2200", "credit") - balance("1300", "debit"))} sub="Output less input VAT" />
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <Card className="p-5 lg:col-span-2">
              <SectionTitle>Revenue vs expenses — last 12 months</SectionTitle>
              {trend?.some((t) => num(t.revenue) || num(t.expenses)) ? (
                <BarChart
                  data={trend.map((t) => ({ label: MONTH_ABBR[Number(t.period.slice(5)) - 1], values: [num(t.revenue), num(t.expenses)] }))}
                  series={[{ name: "Revenue", color: "#1a7a8c" }, { name: "Expenses", color: "#f59e0b" }]}
                  format={(v) => fmtMoney(v)}
                />
              ) : (
                <EmptyState title="No activity yet" description="Invoices, bills and payroll will chart here." />
              )}
            </Card>
            <Card className="p-5">
              <SectionTitle>This month</SectionTitle>
              {pnl ? (
                <dl className="space-y-2 text-sm">
                  <Row label="Revenue" value={fmtMoney(pnl.total_revenue)} />
                  <Row label="Cost of sales" value={fmtMoney(pnl.total_cost_of_sales)} />
                  <Row label={`Gross profit (${num(pnl.gross_margin_pct).toFixed(0)}%)`} value={fmtMoney(pnl.gross_profit)} />
                  <Row label="Operating expenses" value={fmtMoney(pnl.total_operating_expenses)} />
                  <div className="border-t border-slate-200 pt-2 dark:border-navy-700">
                    <Row label="Net profit" value={fmtMoney(pnl.net_profit, currency)} strong negative={num(pnl.net_profit) < 0} />
                  </div>
                </dl>
              ) : (
                <p className="text-sm text-slate-400">Loading…</p>
              )}
            </Card>
          </div>
        </>
      ) : (
        <Card className="p-6">
          <p className="text-sm text-slate-500 dark:text-slate-400">Enable the Accounting module to see financial summaries here.</p>
        </Card>
      )}

      {hasSales && aging && aging.rows.length > 0 && (
        <Card>
          <div className="flex items-center justify-between px-5 pt-4">
            <SectionTitle>Who owes you</SectionTitle>
            <Link href="/dashboard/sales" className="text-sm text-brand hover:underline">All receivables →</Link>
          </div>
          <Table>
            <thead><tr><Th>Customer</Th><Th>Current</Th><Th>Overdue</Th><Th>Total</Th></tr></thead>
            <tbody>
              {aging.rows.slice(0, 6).map((r) => (
                <tr key={r.party_id}>
                  <Td className="font-medium">{r.party_name}</Td>
                  <Td className="tabular-nums">{fmtMoney(r.current)}</Td>
                  <Td className={`tabular-nums ${num(r.total) - num(r.current) > 0 ? "text-red-600" : ""}`}>{fmtMoney(num(r.total) - num(r.current))}</Td>
                  <Td className="font-semibold tabular-nums">{fmtMoney(r.total)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      )}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          { href: "/dashboard/sales", label: "New invoice", icon: Receipt, show: hasSales },
          { href: "/pos", label: "Open POS", icon: Store, show: features.has("pos") },
          { href: "/dashboard/purchasing", label: "Record a bill", icon: ShoppingCart, show: features.has("purchasing") },
          { href: "/dashboard/payroll", label: "Run payroll", icon: Wallet, show: features.has("hr") },
        ]
          .filter((l) => l.show)
          .map(({ href, label, icon: Icon }) => (
            <Link key={href} href={href} className="group flex items-center gap-3 rounded-2xl border border-slate-200/80 bg-white px-4 py-3.5 text-sm font-medium text-navy-900 shadow-card transition hover:-translate-y-0.5 hover:border-brand/40 hover:shadow-lift dark:border-navy-700 dark:bg-navy-800 dark:text-white">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-50 text-brand"><Icon className="h-4 w-4" /></span>
              <span className="flex-1">{label}</span>
              <ArrowRight className="h-4 w-4 text-slate-300 transition group-hover:translate-x-0.5 group-hover:text-brand" />
            </Link>
          ))}
      </div>
    </div>
  );
}

function Row({ label, value, strong, negative }: { label: string; value: string; strong?: boolean; negative?: boolean }) {
  return (
    <div className={`flex justify-between ${strong ? "text-base font-semibold" : ""}`}>
      <dt className="text-slate-500 dark:text-slate-400">{label}</dt>
      <dd className={`tabular-nums ${negative ? "text-red-600" : "text-navy-900 dark:text-white"}`}>{value}</dd>
    </div>
  );
}
