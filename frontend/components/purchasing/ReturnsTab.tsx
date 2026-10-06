"use client";

import { useMemo, useState } from "react";
import { Plus, Undo2 } from "lucide-react";
import { Button, Card, EmptyState, ErrorBanner, Field, Input, Loading, Modal, Select, Table, Td, Th } from "@/components/om/primitives";
import { useParties, useProducts, useVendorBills, useWarehouses } from "@/lib/api/hooks";
import { errorMessage, useApi, useApiMutation } from "@/lib/api/query";
import { fmtDate, fmtMoney, num, today } from "@/lib/format";
import type { DebitNote } from "@/lib/api/types";

const REFRESH = [["purchasing"], ["inventory"], ["accounting"]];

/** Goods sent back to a supplier. Each return raises a debit note: stock goes
 * down and what you owe on the bill falls by the same amount. */
export function ReturnsTab({ canWrite }: { canWrite: boolean }) {
  const { data: notes, isLoading } = useApi<DebitNote[]>("/purchasing/vendor-returns");
  const { data: parties } = useParties();
  const { data: bills } = useVendorBills();
  const [showNew, setShowNew] = useState(false);
  const names = useMemo(() => new Map((parties ?? []).map((p) => [p.id, p.name])), [parties]);
  const billNos = useMemo(() => new Map((bills ?? []).map((b) => [b.id, b.bill_no])), [bills]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-2xl text-sm text-slate-500">Send damaged or wrong goods back. Stock leaves your shelves and the supplier&apos;s bill is reduced by the credit, VAT included.</p>
        {canWrite && <Button onClick={() => setShowNew(true)}><Plus /> Return to supplier</Button>}
      </div>
      <Card>
        {isLoading ? <Loading /> : !notes?.length ? (
          <div className="p-6"><EmptyState icon={<Undo2 />} title="No supplier returns" description="Returns you record appear here as debit notes." /></div>
        ) : (
          <Table>
            <thead><tr><Th>Debit note</Th><Th>Supplier</Th><Th>Against bill</Th><Th>Date</Th><Th>Reason</Th><Th>Before VAT</Th><Th>VAT</Th><Th>Total</Th></tr></thead>
            <tbody>
              {notes.map((n) => (
                <tr key={n.id}>
                  <Td className="font-medium">{n.debit_note_no}</Td>
                  <Td>{names.get(n.party_id) ?? "—"}</Td>
                  <Td>{billNos.get(n.vendor_bill_id) ?? "—"}</Td>
                  <Td className="whitespace-nowrap">{fmtDate(n.note_date)}</Td>
                  <Td className="text-slate-500">{n.reason || "—"}</Td>
                  <Td className="tabular-nums">{fmtMoney(n.subtotal)}</Td>
                  <Td className="tabular-nums">{fmtMoney(n.tax_total)}</Td>
                  <Td className="font-medium tabular-nums">{fmtMoney(n.total)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      {showNew && <NewReturnModal names={names} onClose={() => setShowNew(false)} />}
    </div>
  );
}

function NewReturnModal({ names, onClose }: { names: Map<string, string>; onClose: () => void }) {
  const { data: bills } = useVendorBills();
  const { data: products } = useProducts();
  const { data: warehouses } = useWarehouses();
  const create = useApiMutation("post", "/purchasing/vendor-returns", REFRESH);
  const [form, setForm] = useState({ vendor_bill_id: "", warehouse_id: "", note_date: today(), reason: "", vat: "16" });
  const [lines, setLines] = useState([{ product_id: "", qty: "", unit_price: "" }]);
  const [error, setError] = useState<string | null>(null);
  const openBills = (bills ?? []).filter((b) => b.status === "posted" || b.status === "partially_paid");
  const bill = openBills.find((b) => b.id === form.vendor_bill_id);
  const setLine = (i: number, patch: Partial<(typeof lines)[number]>) => setLines(lines.map((l, j) => (j === i ? { ...l, ...patch } : l)));

  const subtotal = lines.reduce((sum, l) => sum + num(l.qty) * num(l.unit_price), 0);
  const vat = Math.round(subtotal * num(form.vat)) / 100;

  function pickBill(id: string) {
    const picked = openBills.find((b) => b.id === id);
    // Default the VAT rate to the one on the bill being reduced.
    const rate = picked && num(picked.subtotal) > 0 ? Math.round((num(picked.tax_total) / num(picked.subtotal)) * 100) : 16;
    setForm({ ...form, vendor_bill_id: id, vat: String(rate) });
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const payload = lines.filter((l) => l.product_id && num(l.qty) > 0);
    if (!payload.length) return setError("Add at least one product and the quantity going back.");
    try {
      await create.mutateAsync({
        vendor_bill_id: form.vendor_bill_id, warehouse_id: form.warehouse_id, note_date: form.note_date, reason: form.reason,
        tax_rate: String(num(form.vat) / 100),
        lines: payload.map((l) => ({ product_id: l.product_id, qty: l.qty, unit_price: l.unit_price || "0" })),
      });
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <Modal open onClose={onClose} title="Return goods to a supplier" wide>
      <form onSubmit={submit} className="space-y-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div className="sm:col-span-2">
            <Field label="Which bill are the goods from?" hint="Only bills with money still owed — for a bill already paid, record the supplier's refund instead">
              <Select required value={form.vendor_bill_id} onChange={(e) => pickBill(e.target.value)}>
                <option value="">Select a bill…</option>
                {openBills.map((b) => <option key={b.id} value={b.id}>{b.bill_no} · {names.get(b.party_id) ?? "Supplier"} · {fmtMoney(b.total)}</option>)}
              </Select>
            </Field>
          </div>
          <Field label="Goods leave from">
            <Select required value={form.warehouse_id} onChange={(e) => setForm({ ...form, warehouse_id: e.target.value })}>
              <option value="">Select…</option>
              {warehouses?.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
            </Select>
          </Field>
          <Field label="Date"><Input type="date" required value={form.note_date} onChange={(e) => setForm({ ...form, note_date: e.target.value })} /></Field>
          <Field label="VAT % on the purchase"><Input type="number" step="0.01" min="0" max="100" value={form.vat} onChange={(e) => setForm({ ...form, vat: e.target.value })} /></Field>
          <Field label="Reason"><Input required maxLength={200} value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} placeholder="e.g. Damaged in transit" /></Field>
        </div>

        <div className="space-y-2">
          <div className="hidden grid-cols-12 gap-2 px-1 text-xs font-medium text-slate-500 sm:grid">
            <span className="col-span-6">Product</span><span className="col-span-2">Qty returned</span><span className="col-span-3">Credit per unit (before VAT)</span>
          </div>
          {lines.map((line, i) => (
            <div key={i} className="grid grid-cols-12 gap-2">
              <div className="col-span-12 sm:col-span-6">
                <Select aria-label="Product" value={line.product_id} onChange={(e) => {
                  const product = products?.find((p) => p.id === e.target.value);
                  setLine(i, { product_id: e.target.value, unit_price: product && num(product.avg_cost) ? num(product.avg_cost).toFixed(2) : line.unit_price });
                }}>
                  <option value="">Product…</option>
                  {products?.filter((p) => num(p.stock_qty) > 0).map((p) => <option key={p.id} value={p.id}>{p.sku} — {p.name}</option>)}
                </Select>
              </div>
              <div className="col-span-5 sm:col-span-2"><Input type="number" step="any" min="0" placeholder="Qty" aria-label="Quantity returned" value={line.qty} onChange={(e) => setLine(i, { qty: e.target.value })} /></div>
              <div className="col-span-6 sm:col-span-3"><Input type="number" step="0.01" min="0" placeholder="0.00" aria-label="Credit per unit" value={line.unit_price} onChange={(e) => setLine(i, { unit_price: e.target.value })} /></div>
              <button type="button" aria-label="Remove line" className="col-span-1 text-slate-400 hover:text-red-600" onClick={() => setLines(lines.length > 1 ? lines.filter((_, j) => j !== i) : lines)}>✕</button>
            </div>
          ))}
          <Button type="button" variant="secondary" className="px-3 py-1.5 text-xs" onClick={() => setLines([...lines, { product_id: "", qty: "", unit_price: "" }])}>+ Add another product</Button>
        </div>

        <div className="ml-auto w-full max-w-xs space-y-1 text-sm text-slate-600 dark:text-slate-300">
          <p className="flex justify-between"><span>Before VAT</span><span className="tabular-nums">{fmtMoney(subtotal)}</span></p>
          <p className="flex justify-between"><span>VAT</span><span className="tabular-nums">{fmtMoney(vat)}</span></p>
          <p className="flex justify-between border-t border-slate-200 pt-1 font-semibold text-navy-900 dark:border-navy-700 dark:text-white"><span>Credit from supplier</span><span className="tabular-nums">{fmtMoney(subtotal + vat)}</span></p>
          {bill && <p className="text-xs text-slate-400">Bill {bill.bill_no} is {fmtMoney(bill.total)} in total.</p>}
        </div>

        <ErrorBanner message={error} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={create.isPending}>{create.isPending ? "Saving…" : "Record return"}</Button>
        </div>
      </form>
    </Modal>
  );
}
