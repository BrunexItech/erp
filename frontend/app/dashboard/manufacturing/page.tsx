"use client";

import { useMemo, useState } from "react";
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
import { useProducts, useWarehouses } from "@/lib/api/hooks";
import { errorMessage, useApi, useApiMutation } from "@/lib/api/query";
import { fmtDate, fmtMoney, fmtQty, humanize, num } from "@/lib/format";
import type { Bom, BomDetail, WorkOrder } from "@/lib/api/types";

type Tab = "orders" | "boms";
const REFRESH = [["manufacturing"], ["inventory"], ["accounting"]];
const WO_TONE: Record<string, "warning" | "success" | "neutral"> = { planned: "warning", completed: "success", cancelled: "neutral" };

export default function ManufacturingPage() {
  const [tab, setTab] = useState<Tab>("orders");
  return (
    <div className="space-y-6">
      <PageHeader title="Manufacturing" description="Bills of materials and work orders — components consumed at cost, finished goods valued automatically." />
      <Tabs<Tab> value={tab} onChange={setTab} tabs={[{ key: "orders", label: "Work orders" }, { key: "boms", label: "Bills of materials" }]} />
      {tab === "orders" ? <WorkOrdersTab /> : <BomsTab />}
    </div>
  );
}

function useProductNames() {
  const { data: products } = useProducts();
  return useMemo(() => new Map((products ?? []).map((p) => [p.id, `${p.sku} — ${p.name}`])), [products]);
}

function BomsTab() {
  const { data: boms, isLoading } = useApi<Bom[]>("/manufacturing/boms");
  const names = useProductNames();
  const [showNew, setShowNew] = useState(false);
  const [viewing, setViewing] = useState<string | null>(null);
  return (
    <div className="space-y-4">
      <div className="flex justify-end"><Button onClick={() => setShowNew(true)}>New BOM</Button></div>
      <Card>
        {isLoading ? <Loading /> : !boms?.length ? (
          <div className="p-6"><EmptyState title="No bills of materials" description="Define what goes into each product you make." /></div>
        ) : (
          <Table>
            <thead><tr><Th>BOM</Th><Th>Makes</Th><Th>Batch size</Th><Th></Th></tr></thead>
            <tbody>
              {boms.map((b) => (
                <tr key={b.id}>
                  <Td className="font-medium">{b.name}</Td>
                  <Td>{names.get(b.product_id) ?? "—"}</Td>
                  <Td>{fmtQty(b.output_qty)}</Td>
                  <Td><Button variant="secondary" className="px-2 py-1 text-xs" onClick={() => setViewing(b.id)}>Costing & availability</Button></Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      {showNew && <BomForm onClose={() => setShowNew(false)} />}
      {viewing && <BomView bomId={viewing} onClose={() => setViewing(null)} />}
    </div>
  );
}

function BomForm({ onClose }: { onClose: () => void }) {
  const { data: products } = useProducts();
  const create = useApiMutation("post", "/manufacturing/boms", REFRESH);
  const [productId, setProductId] = useState("");
  const [name, setName] = useState("");
  const [output, setOutput] = useState("1");
  const [lines, setLines] = useState([{ component_id: "", qty: "1", scrap_pct: "0" }]);
  const [error, setError] = useState<string | null>(null);

  return (
    <Modal open onClose={onClose} title="New bill of materials" wide>
      <form
        className="space-y-4"
        onSubmit={async (e) => {
          e.preventDefault();
          setError(null);
          try {
            await create.mutateAsync({ product_id: productId, name, output_qty: output, lines: lines.filter((l) => l.component_id) });
            onClose();
          } catch (err) {
            setError(errorMessage(err));
          }
        }}
      >
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Field label="Finished product">
            <Select required value={productId} onChange={(e) => setProductId(e.target.value)}>
              <option value="">Select…</option>
              {products?.map((p) => <option key={p.id} value={p.id}>{p.sku} — {p.name}</option>)}
            </Select>
          </Field>
          <Field label="BOM name"><Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Defaults to product name" /></Field>
          <Field label="Batch makes (units)"><Input type="number" min="0.0001" step="any" value={output} onChange={(e) => setOutput(e.target.value)} /></Field>
        </div>
        <p className="text-xs font-semibold uppercase tracking-wide text-brand">Components per batch</p>
        {lines.map((l, i) => (
          <div key={i} className="grid grid-cols-12 gap-2">
            <div className="col-span-6">
              <Select value={l.component_id} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, component_id: e.target.value } : x)))}>
                <option value="">Component…</option>
                {products?.filter((p) => p.id !== productId).map((p) => <option key={p.id} value={p.id}>{p.sku} — {p.name}</option>)}
              </Select>
            </div>
            <div className="col-span-3"><Input type="number" step="any" min="0" placeholder="Qty" value={l.qty} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, qty: e.target.value } : x)))} /></div>
            <div className="col-span-2"><Input type="number" step="0.01" min="0" placeholder="Scrap %" value={l.scrap_pct} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, scrap_pct: e.target.value } : x)))} /></div>
            <button type="button" className="col-span-1 text-slate-400 hover:text-red-600" onClick={() => setLines(lines.filter((_, j) => j !== i))}>✕</button>
          </div>
        ))}
        <Button type="button" variant="secondary" className="px-3 py-1.5 text-xs" onClick={() => setLines([...lines, { component_id: "", qty: "1", scrap_pct: "0" }])}>+ Add component</Button>
        <ErrorBanner message={error} />
        <div className="flex justify-end"><Button type="submit" disabled={create.isPending}>Create BOM</Button></div>
      </form>
    </Modal>
  );
}

function BomView({ bomId, onClose }: { bomId: string; onClose: () => void }) {
  const { data: warehouses } = useWarehouses();
  const [qty, setQty] = useState("");
  const [warehouseId, setWarehouseId] = useState("");
  const params = new URLSearchParams();
  if (qty) params.set("qty", qty);
  if (warehouseId) params.set("warehouse_id", warehouseId);
  const { data, isLoading } = useApi<BomDetail>(`/manufacturing/boms/${bomId}?${params.toString()}`);
  return (
    <Modal open onClose={onClose} title={data?.name ?? "BOM"} wide>
      <div className="space-y-4">
        <div className="flex flex-wrap gap-3">
          <Field label="Build quantity"><Input type="number" min="0" step="any" placeholder={data?.output_qty} value={qty} onChange={(e) => setQty(e.target.value)} /></Field>
          <Field label="Check stock at">
            <Select value={warehouseId} onChange={(e) => setWarehouseId(e.target.value)}>
              <option value="">All locations</option>
              {warehouses?.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
            </Select>
          </Field>
        </div>
        {isLoading || !data ? <Loading /> : (
          <>
            <Table>
              <thead><tr><Th>Component</Th><Th>Per batch</Th><Th>Scrap</Th><Th>Required</Th><Th>On hand</Th><Th>Short</Th><Th>Unit cost</Th><Th>Cost</Th></tr></thead>
              <tbody>
                {data.lines.map((l) => (
                  <tr key={l.id}>
                    <Td>{l.sku} — {l.name}</Td>
                    <Td>{fmtQty(l.qty)}</Td>
                    <Td>{num(l.scrap_pct) ? `${num(l.scrap_pct)}%` : "—"}</Td>
                    <Td>{fmtQty(l.required)}</Td>
                    <Td>{fmtQty(l.on_hand)}</Td>
                    <Td className={num(l.shortfall) > 0 ? "font-medium text-red-600" : ""}>{num(l.shortfall) ? fmtQty(l.shortfall) : "—"}</Td>
                    <Td className="tabular-nums">{fmtMoney(l.unit_cost)}</Td>
                    <Td className="tabular-nums">{fmtMoney(l.extended_cost)}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <div className="flex flex-wrap gap-6 text-sm">
              <p>Material cost per unit: <strong>{fmtMoney(data.unit_material_cost)}</strong></p>
              <p>Can build now: <strong>{fmtQty(data.max_buildable)}</strong> unit(s)</p>
            </div>
          </>
        )}
      </div>
    </Modal>
  );
}

function WorkOrdersTab() {
  const { data: orders, isLoading } = useApi<WorkOrder[]>("/manufacturing/work-orders");
  const { data: boms } = useApi<Bom[]>("/manufacturing/boms");
  const { data: warehouses } = useWarehouses();
  const names = useProductNames();
  const create = useApiMutation("post", "/manufacturing/work-orders", REFRESH);
  const complete = useApiMutation<{ id: string; qty_produced: string | null; conversion_cost: string }>(
    "post", (b) => `/manufacturing/work-orders/${b.id}/complete`, REFRESH
  );
  const cancel = useApiMutation<{ id: string }>("post", (b) => `/manufacturing/work-orders/${b.id}/cancel`, REFRESH);
  const [showNew, setShowNew] = useState(false);
  const [completing, setCompleting] = useState<WorkOrder | null>(null);
  const [form, setForm] = useState({ bom_id: "", warehouse_id: "", qty_planned: "1", planned_date: "" });
  const [produced, setProduced] = useState("");
  const [conversion, setConversion] = useState("0");
  const [error, setError] = useState<string | null>(null);
  const warehouseNames = useMemo(() => new Map((warehouses ?? []).map((w) => [w.id, w.name])), [warehouses]);

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
      <div className="flex justify-end"><Button onClick={() => setShowNew(true)} disabled={!boms?.length}>New work order</Button></div>
      <ErrorBanner message={!showNew && !completing ? error : null} />
      <Card>
        {isLoading ? <Loading /> : !orders?.length ? (
          <div className="p-6"><EmptyState title="No work orders" description={boms?.length ? "Plan a production run." : "Create a bill of materials first."} /></div>
        ) : (
          <Table>
            <thead><tr><Th>WO</Th><Th>Product</Th><Th>Warehouse</Th><Th>Planned</Th><Th>Produced</Th><Th>Unit cost</Th><Th>Status</Th><Th></Th></tr></thead>
            <tbody>
              {orders.map((o) => (
                <tr key={o.id}>
                  <Td className="font-medium">{o.wo_no}</Td>
                  <Td>{names.get(o.product_id) ?? "—"}</Td>
                  <Td>{warehouseNames.get(o.warehouse_id) ?? "—"}</Td>
                  <Td>{fmtQty(o.qty_planned)}{o.planned_date && <span className="text-xs text-slate-400"> · {fmtDate(o.planned_date)}</span>}</Td>
                  <Td>{num(o.qty_produced) ? fmtQty(o.qty_produced) : "—"}</Td>
                  <Td className="tabular-nums">{num(o.unit_cost) ? fmtMoney(o.unit_cost) : "—"}</Td>
                  <Td><Badge tone={WO_TONE[o.status]}>{humanize(o.status)}</Badge></Td>
                  <Td>
                    {o.status === "planned" && (
                      <div className="flex justify-end gap-1">
                        <Button className="px-2 py-1 text-xs" onClick={() => { setCompleting(o); setProduced(o.qty_planned); setConversion("0"); }}>Complete</Button>
                        <Button variant="secondary" className="px-2 py-1 text-xs" onClick={() => act(() => cancel.mutateAsync({ id: o.id }))}>Cancel</Button>
                      </div>
                    )}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <Modal open={showNew} onClose={() => setShowNew(false)} title="New work order">
        <form
          className="space-y-3"
          onSubmit={async (e) => {
            e.preventDefault();
            if (await act(() => create.mutateAsync({ ...form, planned_date: form.planned_date || null }))) setShowNew(false);
          }}
        >
          <Field label="Bill of materials">
            <Select required value={form.bom_id} onChange={(e) => setForm({ ...form, bom_id: e.target.value })}>
              <option value="">Select…</option>
              {boms?.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
            </Select>
          </Field>
          <Field label="Produce at warehouse">
            <Select required value={form.warehouse_id} onChange={(e) => setForm({ ...form, warehouse_id: e.target.value })}>
              <option value="">Select…</option>
              {warehouses?.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
            </Select>
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Quantity"><Input type="number" min="0" step="any" value={form.qty_planned} onChange={(e) => setForm({ ...form, qty_planned: e.target.value })} /></Field>
            <Field label="Planned date"><Input type="date" value={form.planned_date} onChange={(e) => setForm({ ...form, planned_date: e.target.value })} /></Field>
          </div>
          <ErrorBanner message={error} />
          <div className="flex justify-end"><Button type="submit" disabled={create.isPending}>Create</Button></div>
        </form>
      </Modal>

      <Modal open={!!completing} onClose={() => setCompleting(null)} title={`Complete ${completing?.wo_no ?? ""}`}>
        <form
          className="space-y-3"
          onSubmit={async (e) => {
            e.preventDefault();
            if (!completing) return;
            if (await act(() => complete.mutateAsync({ id: completing.id, qty_produced: produced || null, conversion_cost: conversion || "0" }))) setCompleting(null);
          }}
        >
          <p className="text-sm text-slate-500">Issues the components from stock at their current cost and receives the finished goods. A component shortage stops the whole build.</p>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Quantity produced"><Input type="number" min="0" step="any" value={produced} onChange={(e) => setProduced(e.target.value)} /></Field>
            <Field label="Labour & overhead" hint="Capitalised into the finished goods"><Input type="number" step="0.01" min="0" value={conversion} onChange={(e) => setConversion(e.target.value)} /></Field>
          </div>
          <ErrorBanner message={error} />
          <div className="flex justify-end"><Button type="submit" disabled={complete.isPending}>Complete production</Button></div>
        </form>
      </Modal>
    </div>
  );
}
