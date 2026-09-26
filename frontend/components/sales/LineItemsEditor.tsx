"use client";

import { Button, Input, Select } from "@/components/om/primitives";
import { fmtMoney, num } from "@/lib/format";
import type { Product } from "@/lib/api/types";

export interface LineDraft {
  product_id: string;
  description: string;
  qty: string;
  unit_price: string;
  discount_pct: string;
  tax_rate: string; // percent in the UI (16), fraction on the wire (0.16)
}

export const emptyLine = (): LineDraft => ({
  product_id: "",
  description: "",
  qty: "1",
  unit_price: "0",
  discount_pct: "0",
  tax_rate: "16",
});

const round2 = (v: number) => Math.round((v + Number.EPSILON) * 100) / 100;

/** Mirrors backend compute_lines(): round each line, then sum. */
export function lineTotals(lines: LineDraft[]) {
  let subtotal = 0;
  let discount = 0;
  let tax = 0;
  for (const l of lines) {
    const gross = num(l.qty) * num(l.unit_price);
    const disc = round2((gross * num(l.discount_pct)) / 100);
    const net = round2(gross) - disc;
    subtotal += net;
    discount += disc;
    tax += round2((net * num(l.tax_rate)) / 100);
  }
  return { subtotal, discount, tax, total: subtotal + tax };
}

export function toPayloadLines(lines: LineDraft[]) {
  return lines
    .filter((l) => l.product_id || l.description.trim())
    .map((l) => ({
      product_id: l.product_id || null,
      description: l.description,
      qty: l.qty,
      unit_price: l.unit_price,
      discount_pct: l.discount_pct || "0",
      tax_rate: String(num(l.tax_rate) / 100),
    }));
}

export function LineItemsEditor({
  lines,
  onChange,
  products,
  currency,
}: {
  lines: LineDraft[];
  onChange: (lines: LineDraft[]) => void;
  products: Product[];
  currency?: string;
}) {
  const update = (i: number, patch: Partial<LineDraft>) =>
    onChange(lines.map((l, idx) => (idx === i ? { ...l, ...patch } : l)));

  function pickProduct(i: number, productId: string) {
    const product = products.find((p) => p.id === productId);
    update(i, {
      product_id: productId,
      description: product ? product.name : lines[i].description,
      unit_price: product ? String(num(product.sale_price)) : lines[i].unit_price,
      tax_rate: product ? String(num(product.tax_rate) * 100) : lines[i].tax_rate,
    });
  }

  const totals = lineTotals(lines);

  return (
    <div className="space-y-3">
      <div className="hidden grid-cols-12 gap-2 px-1 text-xs font-medium text-slate-500 md:grid">
        <span className="col-span-3">Product</span>
        <span className="col-span-3">Description</span>
        <span className="col-span-1">Qty</span>
        <span className="col-span-2">Unit price</span>
        <span className="col-span-1">Disc %</span>
        <span className="col-span-1">VAT %</span>
        <span className="col-span-1 text-right">Amount</span>
      </div>
      {lines.map((line, i) => {
        const gross = num(line.qty) * num(line.unit_price);
        const net = gross - (gross * num(line.discount_pct)) / 100;
        return (
          <div key={i} className="grid grid-cols-2 gap-2 rounded-lg border border-slate-200 p-2 dark:border-navy-700 md:grid-cols-12 md:border-0 md:p-0">
            <div className="col-span-2 md:col-span-3">
              <Select value={line.product_id} onChange={(e) => pickProduct(i, e.target.value)}>
                <option value="">— Service / free text —</option>
                {products.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.sku} — {p.name}
                  </option>
                ))}
              </Select>
            </div>
            <div className="col-span-2 md:col-span-3">
              <Input placeholder="Description" value={line.description} onChange={(e) => update(i, { description: e.target.value })} />
            </div>
            <div className="md:col-span-1">
              <Input type="number" min="0" step="any" value={line.qty} onChange={(e) => update(i, { qty: e.target.value })} />
            </div>
            <div className="md:col-span-2">
              <Input type="number" min="0" step="0.01" value={line.unit_price} onChange={(e) => update(i, { unit_price: e.target.value })} />
            </div>
            <div className="md:col-span-1">
              <Input type="number" min="0" max="100" step="0.01" value={line.discount_pct} onChange={(e) => update(i, { discount_pct: e.target.value })} />
            </div>
            <div className="md:col-span-1">
              <Input type="number" min="0" max="100" step="0.01" value={line.tax_rate} onChange={(e) => update(i, { tax_rate: e.target.value })} />
            </div>
            <div className="col-span-2 flex items-center justify-end gap-2 md:col-span-1">
              <span className="text-sm font-medium tabular-nums text-navy-900 dark:text-white">{fmtMoney(net)}</span>
              {lines.length > 1 && (
                <button
                  type="button"
                  onClick={() => onChange(lines.filter((_, idx) => idx !== i))}
                  className="text-slate-400 hover:text-red-600"
                  aria-label="Remove line"
                >
                  ✕
                </button>
              )}
            </div>
          </div>
        );
      })}
      <Button type="button" variant="secondary" className="px-3 py-1.5 text-xs" onClick={() => onChange([...lines, emptyLine()])}>
        + Add line
      </Button>
      <div className="ml-auto w-full max-w-xs space-y-1 text-sm">
        <Row label="Subtotal" value={fmtMoney(totals.subtotal + totals.discount)} />
        {totals.discount > 0 && <Row label="Discount" value={`-${fmtMoney(totals.discount)}`} />}
        <Row label="VAT" value={fmtMoney(totals.tax)} />
        <div className="border-t border-slate-200 pt-1 dark:border-navy-700">
          <Row label="Total" value={fmtMoney(totals.total, currency)} bold />
        </div>
      </div>
    </div>
  );
}

function Row({ label, value, bold }: { label: string; value: string; bold?: boolean }) {
  return (
    <div className={`flex justify-between ${bold ? "font-semibold text-navy-900 dark:text-white" : "text-slate-600 dark:text-slate-300"}`}>
      <span>{label}</span>
      <span className="tabular-nums">{value}</span>
    </div>
  );
}
