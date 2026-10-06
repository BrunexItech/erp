"use client";

import { useMemo, useState } from "react";
import { CalendarClock, Plus, Repeat } from "lucide-react";
import { Badge, Button, Card, Checkbox, EmptyState, ErrorBanner, Field, Input, Loading, Modal, Select, Table, Td, Textarea, Th } from "@/components/om/primitives";
import { useBranding, useParties, useProducts } from "@/lib/api/hooks";
import { errorMessage, useApi, useApiMutation } from "@/lib/api/query";
import { fmtDate, fmtMoney, humanize, num, today } from "@/lib/format";
import type { RecurringInvoice } from "@/lib/api/types";
import { emptyLine, LineDraft, LineItemsEditor, lineTotals, toPayloadLines } from "./LineItemsEditor";

const REFRESH = [["sales"], ["accounting"]];

/** Invoices that repeat — rent, retainers, subscriptions. Each one is raised
 * automatically on its date; "Raise due invoices" does it on demand. */
export function RecurringTab({ currency }: { currency?: string }) {
  const { data: templates, isLoading } = useApi<RecurringInvoice[]>("/sales/recurring");
  const { data: parties } = useParties();
  const { data: branding } = useBranding();
  const inclusive = !!branding?.prices_include_tax;
  const run = useApiMutation<void, { raised: number; invoice_numbers: string[] }>("post", "/sales/recurring/run", REFRESH);
  const toggle = useApiMutation<string>("post", (id) => `/sales/recurring/${id}/toggle`, REFRESH);
  const [showNew, setShowNew] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const names = useMemo(() => new Map((parties ?? []).map((p) => [p.id, p.name])), [parties]);
  const due = (templates ?? []).filter((t) => t.is_active && t.next_date <= today()).length;

  async function act(fn: () => Promise<void>) {
    setError(null);
    setNotice(null);
    try {
      await fn();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const amountOf = (t: RecurringInvoice) =>
    lineTotals(t.lines.map((l) => ({ product_id: "", description: "", qty: String(l.qty), unit_price: String(l.unit_price), discount_pct: "0", tax_rate: String(num(l.tax_rate) * 100) })), inclusive).total;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-2xl text-sm text-slate-500">Set an invoice up once and it is raised for you every week, month, quarter or year — and emailed to the customer if you choose.</p>
        <div className="flex gap-2">
          <Button
            variant="secondary"
            disabled={run.isPending || !due}
            onClick={() => act(async () => {
              const result = await run.mutateAsync();
              setNotice(result.raised ? `Raised ${result.invoice_numbers.join(", ")}.` : "Nothing was due.");
            })}
          >
            <CalendarClock /> Raise due invoices{due ? ` (${due})` : ""}
          </Button>
          <Button onClick={() => setShowNew(true)}><Plus /> New recurring invoice</Button>
        </div>
      </div>
      <ErrorBanner message={error} />
      {notice && <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300">{notice}</p>}
      <Card>
        {isLoading ? <Loading /> : !templates?.length ? (
          <div className="p-6"><EmptyState icon={<Repeat />} title="No recurring invoices" description="Good for rent, monthly retainers, service contracts and subscriptions." /></div>
        ) : (
          <Table>
            <thead><tr><Th>Name</Th><Th>Customer</Th><Th>Repeats</Th><Th>Next invoice</Th><Th>Amount</Th><Th>Raised so far</Th><Th>Status</Th><Th></Th></tr></thead>
            <tbody>
              {templates.map((t) => (
                <tr key={t.id} className={t.is_active ? "" : "opacity-60"}>
                  <Td className="font-medium">{t.name}{t.email_to_customer && <p className="text-xs font-normal text-slate-400">Emailed automatically</p>}</Td>
                  <Td>{names.get(t.party_id) ?? "—"}</Td>
                  <Td>{humanize(t.frequency)}</Td>
                  <Td className={t.is_active && t.next_date <= today() ? "font-medium text-amber-600" : ""}>
                    {t.is_active ? fmtDate(t.next_date) : "—"}
                    {t.end_date && <p className="text-xs font-normal text-slate-400">until {fmtDate(t.end_date)}</p>}
                  </Td>
                  <Td className="tabular-nums">{fmtMoney(amountOf(t), currency)}</Td>
                  <Td>{t.invoices_raised}</Td>
                  <Td><Badge tone={t.is_active ? "success" : "neutral"}>{t.is_active ? "Active" : "Paused"}</Badge></Td>
                  <Td><Button variant="secondary" className="px-2 py-1 text-xs" disabled={toggle.isPending} onClick={() => act(async () => { await toggle.mutateAsync(t.id); })}>{t.is_active ? "Pause" : "Resume"}</Button></Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      {showNew && <NewRecurringModal currency={currency} inclusive={inclusive} onClose={() => setShowNew(false)} />}
    </div>
  );
}

function NewRecurringModal({ currency, inclusive, onClose }: { currency?: string; inclusive: boolean; onClose: () => void }) {
  const { data: parties } = useParties();
  const { data: products } = useProducts();
  const create = useApiMutation("post", "/sales/recurring", REFRESH);
  const [form, setForm] = useState({ party_id: "", name: "", frequency: "monthly", next_date: today(), end_date: "", reference: "", notes: "", email_to_customer: false });
  const [lines, setLines] = useState<LineDraft[]>([emptyLine()]);
  const [error, setError] = useState<string | null>(null);
  const customers = parties?.filter((p) => p.kind !== "vendor") ?? [];
  const customer = customers.find((c) => c.id === form.party_id);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const payloadLines = toPayloadLines(lines);
    if (!payloadLines.length) return setError("Add at least one line with a product or description.");
    if (form.end_date && form.end_date < form.next_date) return setError("The end date is before the first invoice.");
    try {
      await create.mutateAsync({ ...form, end_date: form.end_date || null, lines: payloadLines });
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <Modal open onClose={onClose} title="New recurring invoice" wide>
      <form onSubmit={submit} className="space-y-5">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
          <div className="sm:col-span-2">
            <Field label="Customer">
              <Select required value={form.party_id} onChange={(e) => setForm({ ...form, party_id: e.target.value })}>
                <option value="">Select a customer…</option>
                {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </Select>
            </Field>
          </div>
          <div className="sm:col-span-2">
            <Field label="What is it for?" hint="Your own name for it — not printed"><Input required maxLength={200} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="e.g. Monthly shop rent" /></Field>
          </div>
          <Field label="Repeats">
            <Select value={form.frequency} onChange={(e) => setForm({ ...form, frequency: e.target.value })}>
              <option value="weekly">Every week</option>
              <option value="monthly">Every month</option>
              <option value="quarterly">Every quarter</option>
              <option value="yearly">Every year</option>
            </Select>
          </Field>
          <Field label="First invoice on"><Input type="date" required value={form.next_date} onChange={(e) => setForm({ ...form, next_date: e.target.value })} /></Field>
          <Field label="Stop after" hint="Blank = until you pause it"><Input type="date" value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} /></Field>
          <Field label="Reference"><Input value={form.reference} onChange={(e) => setForm({ ...form, reference: e.target.value })} placeholder="Contract / LPO no." /></Field>
        </div>
        <LineItemsEditor lines={lines} onChange={setLines} products={products ?? []} currency={currency} inclusive={inclusive} />
        <Field label="Notes (printed on each invoice)"><Textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></Field>
        <Checkbox label="Email each invoice to the customer when it is raised" checked={form.email_to_customer} onChange={(v) => setForm({ ...form, email_to_customer: v })} />
        {form.email_to_customer && customer && !customer.email && <p className="text-xs text-amber-600">{customer.name} has no email address yet — add one under Customers & Suppliers or the invoices won't be sent.</p>}
        <ErrorBanner message={error} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={create.isPending}>{create.isPending ? "Saving…" : "Save"}</Button>
        </div>
      </form>
    </Modal>
  );
}
