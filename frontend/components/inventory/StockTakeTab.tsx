"use client";

import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, ClipboardCheck, ClipboardList, Plus } from "lucide-react";
import { Badge, Button, Card, EmptyState, ErrorBanner, Field, Input, Loading, Modal, Select, Table, Td, Th } from "@/components/om/primitives";
import { errorMessage, useApi, useApiMutation } from "@/lib/api/query";
import { fmtDate, fmtMoney, fmtQty, num } from "@/lib/format";
import type { StockCountDetail, StockCountSummary, Warehouse } from "@/lib/api/types";

const REFRESH = [["inventory"], ["accounting"]];
const TONE = { draft: "warning", posted: "success", cancelled: "neutral" } as const;
const LABEL = { draft: "Counting", posted: "Posted", cancelled: "Cancelled" } as const;

/** Stock take: freeze a count sheet, type in what's on the shelf, post the
 * differences. Stock that sells while you count is allowed for. */
export function StockTakeTab({ warehouses, categories, canWrite }: { warehouses: Warehouse[]; categories: string[]; canWrite: boolean }) {
  const { data: counts, isLoading } = useApi<StockCountSummary[]>("/inventory/stock-counts");
  const start = useApiMutation<Record<string, unknown>, { id: string }>("post", "/inventory/stock-counts", REFRESH);
  const [openId, setOpenId] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [form, setForm] = useState({ warehouse_id: "", category: "", note: "" });
  const [error, setError] = useState<string | null>(null);
  const whNames = useMemo(() => new Map(warehouses.map((w) => [w.id, w.name])), [warehouses]);

  if (openId) return <CountSheet id={openId} warehouse={whNames} canWrite={canWrite} onBack={() => setOpenId(null)} />;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-2xl text-sm text-slate-500">Count what is physically on the shelf and correct your records in one go. The value of anything missing or found posts to your accounts.</p>
        {canWrite && <Button onClick={() => { setError(null); setForm({ warehouse_id: warehouses[0]?.id ?? "", category: "", note: "" }); setShowNew(true); }} disabled={!warehouses.length}><Plus /> Start a stock take</Button>}
      </div>
      <Card>
        {isLoading ? <Loading /> : !counts?.length ? (
          <div className="p-6"><EmptyState icon={<ClipboardList />} title="No stock takes yet" description="Most shops count monthly, and always at year end." /></div>
        ) : (
          <Table>
            <thead><tr><Th>Number</Th><Th>Location</Th><Th>Started</Th><Th>Note</Th><Th>Difference</Th><Th>Status</Th></tr></thead>
            <tbody>
              {counts.map((c) => (
                <tr key={c.id} onClick={() => setOpenId(c.id)} className="cursor-pointer hover:bg-slate-50 dark:hover:bg-navy-700/40">
                  <Td className="font-medium">{c.count_no}</Td>
                  <Td>{whNames.get(c.warehouse_id) ?? "—"}</Td>
                  <Td className="whitespace-nowrap">{fmtDate(c.created_at)}</Td>
                  <Td className="text-slate-500">{c.note || "—"}</Td>
                  <Td className={`tabular-nums ${num(c.variance_value) < 0 ? "text-red-600" : ""}`}>{c.status === "posted" ? fmtMoney(c.variance_value) : "—"}</Td>
                  <Td><Badge tone={TONE[c.status]}>{LABEL[c.status]}</Badge></Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <Modal open={showNew} onClose={() => setShowNew(false)} title="Start a stock take">
        <form
          className="space-y-4"
          onSubmit={async (e) => {
            e.preventDefault();
            setError(null);
            try {
              const created = await start.mutateAsync({ warehouse_id: form.warehouse_id, category: form.category || null, note: form.note });
              setShowNew(false);
              setOpenId(created.id);
            } catch (err) {
              setError(errorMessage(err));
            }
          }}
        >
          <Field label="Where are you counting?">
            <Select required value={form.warehouse_id} onChange={(e) => setForm({ ...form, warehouse_id: e.target.value })}>
              <option value="">Select…</option>
              {warehouses.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
            </Select>
          </Field>
          <Field label="What are you counting?" hint="Count one category at a time if the shop is large">
            <Select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
              <option value="">Everything</option>
              {categories.map((c) => <option key={c} value={c}>{c}</option>)}
            </Select>
          </Field>
          <Field label="Note (optional)"><Input value={form.note} maxLength={200} onChange={(e) => setForm({ ...form, note: e.target.value })} placeholder="e.g. October month-end count" /></Field>
          <ErrorBanner message={error} />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setShowNew(false)}>Cancel</Button>
            <Button type="submit" disabled={start.isPending}>Create count sheet</Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}

function CountSheet({ id, warehouse, canWrite, onBack }: { id: string; warehouse: Map<string, string>; canWrite: boolean; onBack: () => void }) {
  const { data: count, isLoading } = useApi<StockCountDetail>(`/inventory/stock-counts/${id}`);
  const save = useApiMutation("put", `/inventory/stock-counts/${id}`, REFRESH);
  const post = useApiMutation<void, { adjusted_lines: number; variance_value: string }>("post", `/inventory/stock-counts/${id}/post`, REFRESH);
  const cancel = useApiMutation<void>("post", `/inventory/stock-counts/${id}/cancel`, REFRESH);
  const [entries, setEntries] = useState<Record<string, string> | null>(null);
  const [dirty, setDirty] = useState(false);
  const [search, setSearch] = useState("");
  const [onlyDiff, setOnlyDiff] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Load the saved figures once; later refetches must not wipe what's being typed.
  useEffect(() => {
    if (count) setEntries((current) => current ?? Object.fromEntries(count.lines.map((l) => [l.id, l.counted_qty === null ? "" : String(num(l.counted_qty))])));
  }, [count]);

  if (isLoading || !count || !entries) return <Card><Loading rows={6} /></Card>;

  const editable = canWrite && count.status === "draft";
  const q = search.trim().toLowerCase();
  const diffOf = (lineId: string, systemQty: string) => (entries[lineId] === "" ? null : num(entries[lineId]) - num(systemQty));
  const rows = count.lines.filter((l) => {
    if (q && !l.name.toLowerCase().includes(q) && !l.sku.toLowerCase().includes(q)) return false;
    if (onlyDiff && !diffOf(l.id, l.system_qty)) return false;
    return true;
  });
  const counted = count.lines.filter((l) => entries[l.id] !== "").length;
  const payload = () => ({ lines: count.lines.map((l) => ({ line_id: l.id, counted_qty: entries[l.id] === "" ? null : entries[l.id] })) });

  async function run(fn: () => Promise<void>) {
    setError(null);
    setNotice(null);
    try {
      await fn();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const saveNow = () => run(async () => {
    await save.mutateAsync(payload());
    setDirty(false);
    setNotice("Saved. You can come back and carry on later.");
  });

  const postNow = () => run(async () => {
    const uncounted = count.lines.length - counted;
    const warn = uncounted ? `${uncounted} product${uncounted === 1 ? " has" : "s have"} no count and will be left unchanged.\n\n` : "";
    if (!window.confirm(`${warn}Post this stock take? Stock levels will be corrected to what you counted. This can't be undone.`)) return;
    await save.mutateAsync(payload());
    const result = await post.mutateAsync();
    setDirty(false);
    setNotice(result.adjusted_lines ? `Posted — ${result.adjusted_lines} product${result.adjusted_lines === 1 ? "" : "s"} corrected, net ${fmtMoney(result.variance_value)}.` : "Posted — everything matched, nothing to correct.");
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Button variant="ghost" className="px-2" onClick={() => (!dirty || window.confirm("Leave without saving your counts?")) && onBack()}><ArrowLeft /> All stock takes</Button>
          <div>
            <p className="font-semibold">{count.count_no} · {warehouse.get(count.warehouse_id) ?? "—"}</p>
            <p className="text-xs text-slate-500">Started {fmtDate(count.created_at)}{count.note && ` · ${count.note}`}</p>
          </div>
          <Badge tone={TONE[count.status]}>{LABEL[count.status]}</Badge>
        </div>
        {editable && (
          <div className="flex gap-2">
            <Button variant="ghost" disabled={cancel.isPending} onClick={() => run(async () => { if (window.confirm("Cancel this stock take? Nothing will be changed.")) { await cancel.mutateAsync(); onBack(); } })}>Cancel count</Button>
            <Button variant="secondary" disabled={save.isPending || !dirty} onClick={saveNow}>Save progress</Button>
            <Button disabled={post.isPending || save.isPending || !counted} onClick={postNow}><ClipboardCheck /> Post stock take</Button>
          </div>
        )}
      </div>

      <ErrorBanner message={error} />
      {notice && <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300">{notice}</p>}

      <div className="flex flex-wrap items-center gap-3">
        <div className="w-full sm:w-72"><Input placeholder="Search name or SKU…" value={search} onChange={(e) => setSearch(e.target.value)} /></div>
        <label className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
          <input type="checkbox" checked={onlyDiff} onChange={(e) => setOnlyDiff(e.target.checked)} className="h-4 w-4 rounded border-slate-300 text-brand" /> Only show differences
        </label>
        <span className="ml-auto text-sm text-slate-500">{counted} of {count.lines.length} counted</span>
      </div>

      <Card>
        <Table>
          <thead><tr><Th>Product</Th><Th>Category</Th><Th>Expected</Th><Th>Counted</Th><Th>Difference</Th></tr></thead>
          <tbody>
            {rows.map((l) => {
              const diff = editable ? diffOf(l.id, l.system_qty) : l.variance === null ? null : num(l.variance);
              return (
                <tr key={l.id}>
                  <Td><p className="font-medium">{l.name}</p><p className="font-mono text-xs text-slate-400">{l.sku}</p></Td>
                  <Td className="text-slate-500">{l.category || "—"}</Td>
                  <Td className="tabular-nums">{fmtQty(l.system_qty)} <span className="text-xs text-slate-400">{l.unit}</span></Td>
                  <Td>
                    {editable ? (
                      <Input
                        type="number" step="any" min="0" inputMode="decimal" aria-label={`Counted ${l.name}`} className="w-28" placeholder="—"
                        value={entries[l.id]}
                        onChange={(e) => { setEntries({ ...entries, [l.id]: e.target.value }); setDirty(true); }}
                      />
                    ) : (
                      <span className="tabular-nums">{l.counted_qty === null ? "—" : fmtQty(l.counted_qty)}</span>
                    )}
                  </Td>
                  <Td className={`tabular-nums font-medium ${!diff ? "text-slate-400" : diff < 0 ? "text-red-600" : "text-emerald-600"}`}>
                    {diff === null ? "—" : diff === 0 ? "Matches" : `${diff > 0 ? "+" : ""}${fmtQty(diff)}`}
                  </Td>
                </tr>
              );
            })}
            {!rows.length && <tr><Td colSpan={5} className="text-slate-400">Nothing matches.</Td></tr>}
          </tbody>
        </Table>
      </Card>
    </div>
  );
}
