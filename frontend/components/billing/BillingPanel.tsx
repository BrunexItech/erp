"use client";

import { CalendarClock, CheckCircle2, CreditCard, Lock, Smartphone } from "lucide-react";
import { Badge, Card, Loading, Table, Td, Th } from "@/components/om/primitives";
import { useApi } from "@/lib/api/query";
import { fmtDate, fmtMoney, humanize, num } from "@/lib/format";

export interface BillingOverview {
  access: { level: "ok" | "grace" | "locked"; state: string; days_left: number | null; message: string };
  package: { name: string; description: string; price_monthly: string; price_yearly: string; limits: { max_users?: number | null; max_sku?: number | null } };
  subscription: { status: string; cycle: string; trial_ends_at: string | null; current_period_end: string | null };
  invoices: { id: string; number: string; period_start: string; period_end: string; amount: string; currency: string; status: string; due_date: string; paid_at: string | null; payment_reference: string }[];
  pay_to: { product_name: string; mpesa_paybill: string; mpesa_till: string; bank_details: string; support_email: string; support_phone: string; currency: string };
}

const STATE: Record<string, { label: string; tone: "success" | "warning" | "danger" | "info" | "neutral" }> = {
  trialing: { label: "Free trial", tone: "info" },
  active: { label: "Active", tone: "success" },
  past_due: { label: "Payment overdue", tone: "danger" },
  trial_ended: { label: "Trial ended", tone: "danger" },
  cancelled: { label: "Cancelled", tone: "danger" },
  complimentary: { label: "Complimentary", tone: "success" },
  none: { label: "Active", tone: "success" },
};

/** The customer's own subscription: plan, status, what's owed and how to pay.
 * Also shown full-screen when the account is locked. */
export function BillingPanel() {
  const { data, isLoading } = useApi<BillingOverview>("/workspaces/billing");
  if (isLoading || !data) return <Loading />;
  const { access, subscription, pay_to: pay } = data;
  const open = data.invoices.filter((i) => i.status === "open");
  const owed = open.reduce((s, i) => s + num(i.amount), 0);
  const state = STATE[access.state] ?? STATE.active;
  const price = subscription.cycle === "yearly" ? data.package.price_yearly : data.package.price_monthly;
  const free = num(data.package.price_monthly) === 0;
  const limit = (v?: number | null) => (v === null || v === undefined ? "Unlimited" : v.toLocaleString());

  return (
    <div className="space-y-6">
      {access.level !== "ok" && (
        <div className={`flex items-start gap-3 rounded-2xl p-4 ${access.level === "locked" ? "bg-red-50 text-red-900" : "bg-amber-50 text-amber-900"}`}>
          <Lock className="mt-0.5 h-5 w-5 shrink-0" />
          <div>
            <p className="font-semibold">{access.level === "locked" ? "Your account is paused" : "Payment overdue"}</p>
            <p className="text-sm">{access.message} Nothing has been deleted.</p>
          </div>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="p-6 lg:col-span-2">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-xs font-medium text-slate-500">Your plan</p>
              <p className="mt-1 text-2xl font-semibold tracking-tight">{data.package.name}</p>
              <p className="mt-1 text-sm text-slate-500">{data.package.description}</p>
            </div>
            <Badge tone={state.tone}>{state.label}</Badge>
          </div>
          <dl className="mt-6 grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
            <div><dt className="text-xs text-slate-500">Price</dt><dd className="mt-0.5 font-semibold">{free ? "Free" : `${fmtMoney(price, pay.currency)} / ${subscription.cycle === "yearly" ? "year" : "month"}`}</dd></div>
            <div>
              <dt className="text-xs text-slate-500">{access.state === "trialing" ? "Trial ends" : "Renews"}</dt>
              <dd className="mt-0.5 font-semibold">{fmtDate(access.state === "trialing" ? subscription.trial_ends_at : subscription.current_period_end)}</dd>
            </div>
            <div><dt className="text-xs text-slate-500">Users</dt><dd className="mt-0.5 font-semibold">{limit(data.package.limits.max_users)}</dd></div>
            <div><dt className="text-xs text-slate-500">Products</dt><dd className="mt-0.5 font-semibold">{limit(data.package.limits.max_sku)}</dd></div>
          </dl>
          {access.state === "trialing" && access.days_left !== null && (
            <p className="mt-4 flex items-center gap-2 text-sm text-slate-600"><CalendarClock className="h-4 w-4 text-brand" />{access.days_left} day(s) left in your free trial.</p>
          )}
        </Card>

        <Card className="p-6">
          <p className="text-xs font-medium text-slate-500">{owed > 0 ? "Amount due" : "Nothing to pay"}</p>
          <p className="mt-1 text-2xl font-semibold tracking-tight">{fmtMoney(owed, pay.currency)}</p>
          {owed > 0 ? (
            <div className="mt-4 space-y-3 text-sm">
              <p className="font-medium">How to pay</p>
              {pay.mpesa_paybill && (
                <p className="flex gap-2"><Smartphone className="mt-0.5 h-4 w-4 shrink-0 text-brand" /><span>M-Pesa Paybill <b>{pay.mpesa_paybill}</b>, account <b>{open[0].number}</b></span></p>
              )}
              {pay.mpesa_till && <p className="flex gap-2"><Smartphone className="mt-0.5 h-4 w-4 shrink-0 text-brand" /><span>M-Pesa Till <b>{pay.mpesa_till}</b></span></p>}
              {pay.bank_details && <p className="flex gap-2"><CreditCard className="mt-0.5 h-4 w-4 shrink-0 text-brand" /><span className="whitespace-pre-line">{pay.bank_details}</span></p>}
              {!pay.mpesa_paybill && !pay.mpesa_till && !pay.bank_details && <p className="text-slate-500">Contact us to arrange payment.</p>}
              <p className="text-xs text-slate-500">Access is restored as soon as your payment is confirmed.</p>
            </div>
          ) : (
            <p className="mt-4 flex items-center gap-2 text-sm text-emerald-700"><CheckCircle2 className="h-4 w-4" />You&apos;re all paid up.</p>
          )}
          {(pay.support_email || pay.support_phone) && (
            <p className="mt-4 border-t border-slate-100 pt-3 text-xs text-slate-500">Questions? {[pay.support_phone, pay.support_email].filter(Boolean).join(" · ")}</p>
          )}
        </Card>
      </div>

      <Card>
        <p className="border-b border-slate-100 px-5 py-3 text-sm font-semibold dark:border-navy-700">Subscription invoices</p>
        {!data.invoices.length ? (
          <p className="p-6 text-sm text-slate-400">No invoices yet{access.state === "trialing" ? " — your first one appears a week before the trial ends." : "."}</p>
        ) : (
          <Table>
            <thead><tr><Th>Invoice</Th><Th>Period</Th><Th>Due</Th><Th>Amount</Th><Th>Status</Th><Th>Paid</Th></tr></thead>
            <tbody>
              {data.invoices.map((i) => (
                <tr key={i.id}>
                  <Td className="font-medium">{i.number}</Td>
                  <Td>{fmtDate(i.period_start)} – {fmtDate(i.period_end)}</Td>
                  <Td>{fmtDate(i.due_date)}</Td>
                  <Td>{fmtMoney(i.amount, i.currency)}</Td>
                  <Td><Badge tone={i.status === "paid" ? "success" : i.status === "open" ? "warning" : "neutral"}>{humanize(i.status)}</Badge></Td>
                  <Td className="text-slate-500">{i.paid_at ? `${fmtDate(i.paid_at)}${i.payment_reference ? ` · ${i.payment_reference}` : ""}` : "—"}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}
