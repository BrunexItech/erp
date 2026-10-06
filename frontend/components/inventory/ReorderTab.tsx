"use client";

import { useEffect, useState } from "react";
import { PackageCheck, ShoppingCart } from "lucide-react";
import { Badge, Button, Card, EmptyState, ErrorBanner, Field, Input, Loading, Modal, Select, Table, Td, Th } from "@/components/om/primitives";
import { useMe, useParties } from "@/lib/api/hooks";
import { errorMessage, useApi, useApiMutation } from "@/lib/api/query";
import { fmtMoney, fmtQty, num } from "@/lib/format";
import type { PurchaseOrder, ReorderRow } from "@/lib/api/types";

interface Pick {
  on: boolean;
  qty: string;
  cost: string;
}

/** Everything at or below its reorder level, with a suggested quantity — tick
 * what you want and it becomes a purchase order for one supplier. */
export function ReorderTab() {
  const { data: me } = useMe();
  const canOrder = !!me && me.features.includes("purchasing") && (me.permissions.includes("*") || me.permissions.includes("purchasing.write"));
  const { data: rows, isLoading } = useApi<ReorderRow[]>("/inventory/reports/reorder");
  const { data: parties } = useParties();
  const createOrder = useApiMutation<Record<string, unknown>, PurchaseOrder>("post", "/purchasing/purchase-orders", [["purchasing"]]);
  const [picks, setPicks] = useState<Record<string, Pick>>({});
  const [showOrder, setShowOrder] = useState(false);
  const [vendorId, setVendorId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<string | null>(null);
  const vendors = parties?.filter((p) => p.kind === "vendor" || p.kind === "both") ?? [];

  // Keep what's been typed; add defaults for rows we haven't seen.
  useEffect(() => {
    if (!rows) return;
    setPicks((current) => {
      const next = { ...current };
      for (const r of rows) next[r.product_id] ??= { on: false, qty: String(num(r.suggested_qty)), cost: num(r.last_cost) ? num(r.last_cost).toFixed(2) : "" };
      return next;
    });
  }, [rows]);

  const chosen = (rows ?? []).filter((r) => picks[r.product_id]?.on && num(picks[r.product_id].qty) > 0);
  const total = chosen.reduce((sum, r) => sum + num(picks[r.product_id].qty) * num(picks[r.product_id].cost), 0);
  const set = (id: string, patch: Partial<Pick>) => setPicks((p) => ({ ...p, [id]: { ...p[id], ...patch } }));
  const allOn = !!rows?.length && rows.every((r) => picks[r.product_id]?.on);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const order = await createOrder.mutateAsync({
        party_id: vendorId,
        lines: chosen.map((r) => ({ product_id: r.product_id, qty_ordered: picks[r.product_id].qty, unit_cost: picks[r.product_id].cost || "0" })),
      });
      setCreated(order.po_no || "Purchase order");
      setShowOrder(false);
      setPicks((p) => Object.fromEntries(Object.entries(p).map(([k, v]) => [k, { ...v, on: false }])));
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-2xl text-sm text-slate-500">Products at or below their reorder level. The suggested quantity brings each one back to twice that level — change it to suit.</p>
        {canOrder && <Button disabled={!chosen.length} onClick={() => { setError(null); setShowOrder(true); }}><ShoppingCart /> Create purchase order{chosen.length ? ` (${chosen.length})` : ""}</Button>}
      </div>
      {created && (
        <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300">
          {created} created as a draft. <a href="/dashboard/purchasing" className="font-medium underline">Open Purchasing</a> to confirm and send it.
        </p>
      )}
      <Card>
        {isLoading ? <Loading /> : !rows?.length ? (
          <div className="p-6"><EmptyState icon={<PackageCheck />} title="Nothing needs reordering" description="Set a reorder level on a product and it will appear here when stock runs low." /></div>
        ) : (
          <Table>
            <thead>
              <tr>
                {canOrder && (
                  <Th>
                    <input type="checkbox" aria-label="Select all" checked={allOn} onChange={(e) => setPicks((p) => Object.fromEntries(Object.entries(p).map(([k, v]) => [k, { ...v, on: e.target.checked }])))} className="h-4 w-4 rounded border-slate-300 text-brand" />
                  </Th>
                )}
                <Th>Product</Th><Th>On hand</Th><Th>Reorder level</Th><Th>Order qty</Th><Th>Unit cost</Th><Th>Line total</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const pick = picks[r.product_id] ?? { on: false, qty: "", cost: "" };
                return (
                  <tr key={r.product_id}>
                    {canOrder && (
                      <Td><input type="checkbox" aria-label={`Order ${r.name}`} checked={pick.on} onChange={(e) => set(r.product_id, { on: e.target.checked })} className="h-4 w-4 rounded border-slate-300 text-brand" /></Td>
                    )}
                    <Td><p className="font-medium">{r.name}</p><p className="font-mono text-xs text-slate-400">{r.sku}{r.category && ` · ${r.category}`}</p></Td>
                    <Td>
                      <span className="mr-2 font-medium tabular-nums">{fmtQty(r.on_hand)} <span className="text-xs font-normal text-slate-400">{r.unit}</span></span>
                      {num(r.on_hand) <= 0 ? <Badge tone="danger">Out</Badge> : <Badge tone="warning">Low</Badge>}
                    </Td>
                    <Td className="tabular-nums">{fmtQty(r.reorder_level)}</Td>
                    <Td>
                      {canOrder ? <Input type="number" step="any" min="0" className="w-24" aria-label={`Quantity of ${r.name}`} value={pick.qty} onChange={(e) => set(r.product_id, { qty: e.target.value, on: true })} /> : <span className="tabular-nums">{fmtQty(r.suggested_qty)}</span>}
                    </Td>
                    <Td>
                      {canOrder ? <Input type="number" step="0.01" min="0" className="w-28" aria-label={`Unit cost of ${r.name}`} value={pick.cost} onChange={(e) => set(r.product_id, { cost: e.target.value })} /> : fmtMoney(r.last_cost)}
                    </Td>
                    <Td className="tabular-nums">{fmtMoney(num(pick.qty) * num(pick.cost))}</Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        )}
      </Card>

      <Modal open={showOrder} onClose={() => setShowOrder(false)} title="Create purchase order">
        <form className="space-y-4" onSubmit={submit}>
          <Field label="Supplier">
            <Select required value={vendorId} onChange={(e) => setVendorId(e.target.value)}>
              <option value="">Select a supplier…</option>
              {vendors.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
            </Select>
          </Field>
          {!vendors.length && <p className="text-xs text-amber-600">Add a supplier under Customers & Suppliers first.</p>}
          <ul className="max-h-56 divide-y divide-slate-100 overflow-y-auto rounded-xl border border-slate-200 text-sm dark:divide-navy-700 dark:border-navy-700">
            {chosen.map((r) => (
              <li key={r.product_id} className="flex justify-between gap-3 px-3 py-2">
                <span className="truncate">{fmtQty(picks[r.product_id].qty)} × {r.name}</span>
                <span className="shrink-0 tabular-nums">{fmtMoney(num(picks[r.product_id].qty) * num(picks[r.product_id].cost))}</span>
              </li>
            ))}
          </ul>
          <p className="flex justify-between text-sm font-semibold"><span>Total before VAT</span><span className="tabular-nums">{fmtMoney(total)}</span></p>
          <ErrorBanner message={error} />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setShowOrder(false)}>Cancel</Button>
            <Button type="submit" disabled={createOrder.isPending || !vendorId}>Create draft order</Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
