"use client";

import { useMemo, useState } from "react";
import { AlertTriangle, ArrowRightLeft, Boxes, Download, PackagePlus, PackageX, Plus, Tags, Upload, Warehouse as WarehouseIcon } from "lucide-react";
import {
  Badge,
  Button,
  Card,
  Checkbox,
  EmptyState,
  ErrorBanner,
  Field,
  Input,
  Loading,
  Modal,
  PageHeader,
  Select,
  StatTile,
  Table,
  Tabs,
  Td,
  Textarea,
  Th,
} from "@/components/om/primitives";
import { ImportModal } from "@/components/om/ImportModal";
import { Attachments } from "@/components/om/Attachments";
import { ProductImageUploader, ProductThumb } from "@/components/inventory/ProductImage";
import { ReorderTab } from "@/components/inventory/ReorderTab";
import { StockTakeTab } from "@/components/inventory/StockTakeTab";
import { useBranding, useMe } from "@/lib/api/hooks";
import { errorMessage, openFile, useApi, useApiMutation } from "@/lib/api/query";
import { fmtDate, fmtMoney, fmtQty, humanize, num } from "@/lib/format";
import type { Product, StockMovement, ValuationReport, ValuationRow, Warehouse } from "@/lib/api/types";

type Tab = "products" | "reorder" | "counts" | "locations" | "transfers";
const REFRESH = [["inventory"], ["accounting"]];
const STATUS: Record<ValuationRow["status"], { tone: "success" | "warning" | "danger"; label: string }> = {
  ok: { tone: "success", label: "In stock" },
  low: { tone: "warning", label: "Low" },
  out: { tone: "danger", label: "Out of stock" },
};

export default function InventoryPage() {
  const { data: me } = useMe();
  const canWrite = !!me && (me.permissions.includes("*") || me.permissions.includes("inventory.write"));
  const { data: branding } = useBranding();
  const { data: report, isLoading } = useApi<ValuationReport>("/inventory/reports/valuation");
  const { data: warehouses } = useApi<Warehouse[]>("/inventory/warehouses");
  const [tab, setTab] = useState<Tab>("products");
  const [showNew, setShowNew] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);

  const totals = report?.totals;
  const margin = totals && num(totals.retail_value) > 0 ? ((num(totals.retail_value) - num(totals.value)) / num(totals.retail_value)) * 100 : 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Inventory"
        description="Products, stock levels across your shops, and what your stock is worth."
        actions={
          <>
            <Button variant="secondary" onClick={() => openFile("/inventory/products/export", "products.csv")}><Download /> Export</Button>
            {canWrite && <Button variant="secondary" onClick={() => setShowImport(true)}><Upload /> Import</Button>}
            {canWrite && <Button onClick={() => setShowNew(true)}><Plus /> Add product</Button>}
          </>
        }
      />

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <StatTile label="Products" icon={<Boxes />} value={String(totals?.products ?? "—")} sub={report ? `${report.categories.length} ${report.categories.length === 1 ? "category" : "categories"}` : undefined} />
        <StatTile label="Stock value (cost)" icon={<Tags />} tone="violet" value={fmtMoney(totals?.value)} sub={branding?.currency} />
        <StatTile label="Retail value" icon={<Tags />} tone="emerald" value={fmtMoney(totals?.retail_value)} sub={`${margin.toFixed(0)}% potential margin`} />
        <StatTile label="Low stock" icon={<AlertTriangle />} tone="amber" value={String(totals?.low ?? "—")} sub="At or below reorder level" />
        <StatTile label="Out of stock" icon={<PackageX />} tone="rose" value={String(totals?.out ?? "—")} />
      </div>

      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        tabs={[
          { key: "products", label: "Products", count: report?.rows.length },
          { key: "reorder", label: "Reorder", count: totals ? totals.low + totals.out : undefined },
          { key: "counts", label: "Stock take" },
          { key: "locations", label: "Shops & warehouses", count: warehouses?.length },
          { key: "transfers", label: "Transfers" },
        ]}
      />

      {tab === "products" && <ProductsTab report={report} isLoading={isLoading} onOpen={setOpenId} onAdd={canWrite ? () => setShowNew(true) : undefined} />}
      {tab === "reorder" && <ReorderTab />}
      {tab === "counts" && <StockTakeTab warehouses={warehouses ?? []} categories={report?.categories ?? []} canWrite={canWrite} />}
      {tab === "locations" && <LocationsTab warehouses={warehouses ?? []} report={report} canWrite={canWrite} />}
      {tab === "transfers" && <TransfersTab warehouses={warehouses ?? []} report={report} canWrite={canWrite} />}

      {showNew && <NewProductModal warehouses={warehouses ?? []} categories={report?.categories ?? []} onClose={() => setShowNew(false)} />}
      {openId && report && (
        <ProductModal row={report.rows.find((r) => r.product_id === openId)!} warehouses={warehouses ?? []} categories={report.categories} canWrite={canWrite} onClose={() => setOpenId(null)} />
      )}
      <ImportModal
        open={showImport}
        onClose={() => setShowImport(false)}
        title="Import products"
        endpoint="/inventory/products/import"
        templatePath="/inventory/products/import-template"
        templateName="products-template.csv"
        help="Add or update many products at once. Products are matched on SKU: new SKUs are created (with opening stock if you fill in quantity, cost and warehouse code); existing ones have their details updated — their stock is never changed by an import."
        invalidate={REFRESH}
      />
    </div>
  );
}

function ProductsTab({ report, isLoading, onOpen, onAdd }: { report?: ValuationReport; isLoading: boolean; onOpen: (id: string) => void; onAdd?: () => void }) {
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [status, setStatus] = useState("");
  const [showInactive, setShowInactive] = useState(false);

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (report?.rows ?? []).filter(
      (r) =>
        (showInactive || r.is_active) &&
        (!category || r.category === category) &&
        (!status || r.status === status) &&
        (!q || r.name.toLowerCase().includes(q) || r.sku.toLowerCase().includes(q))
    );
  }, [report, search, category, status, showInactive]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="w-full sm:w-72"><Input placeholder="Search name or SKU…" value={search} onChange={(e) => setSearch(e.target.value)} /></div>
        <div className="w-44">
          <Select value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">All categories</option>
            {report?.categories.map((c) => <option key={c} value={c}>{c}</option>)}
          </Select>
        </div>
        <div className="w-40">
          <Select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">Any stock level</option>
            <option value="low">Low stock</option>
            <option value="out">Out of stock</option>
            <option value="ok">In stock</option>
          </Select>
        </div>
        <Checkbox label="Show inactive" checked={showInactive} onChange={setShowInactive} />
      </div>
      <Card>
        {isLoading ? <Loading rows={6} /> : !report?.rows.length ? (
          <div className="p-6">
            <EmptyState
              icon={<PackagePlus />}
              title="No products yet"
              description="Add your first product, or import your whole price list from a spreadsheet."
              action={onAdd && <Button onClick={onAdd}><Plus /> Add product</Button>}
            />
          </div>
        ) : !rows.length ? (
          <div className="p-6"><EmptyState title="Nothing matches those filters" /></div>
        ) : (
          <Table>
            <thead>
              <tr><Th>Product</Th><Th>Category</Th><Th>On hand</Th><Th>Unit cost</Th><Th>Stock value</Th><Th>Sale price</Th><Th>Margin</Th><Th>Status</Th></tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const cost = num(r.unit_cost);
                const price = num(r.sale_price);
                const margin = price > 0 && cost > 0 ? ((price - cost) / price) * 100 : null;
                return (
                  <tr key={r.product_id} onClick={() => onOpen(r.product_id)} className={`cursor-pointer hover:bg-slate-50 dark:hover:bg-navy-700/40 ${r.is_active ? "" : "opacity-50"}`}>
                    <Td>
                      <div className="flex items-center gap-3">
                        <ProductThumb url={r.image_url} name={r.name} />
                        <div>
                          <p className="font-medium">{r.name}</p>
                          <p className="font-mono text-xs text-slate-400">{r.sku}</p>
                        </div>
                      </div>
                    </Td>
                    <Td className="text-slate-500">{r.category || "—"}</Td>
                    <Td>
                      <span className="font-medium">{fmtQty(r.qty)}</span> <span className="text-xs text-slate-400">{r.unit}</span>
                      {r.locations.length > 1 && <p className="text-xs text-slate-400">{r.locations.length} locations</p>}
                    </Td>
                    <Td>{fmtMoney(r.unit_cost)}</Td>
                    <Td className="font-medium">{fmtMoney(r.value)}</Td>
                    <Td>{fmtMoney(r.sale_price)}</Td>
                    <Td className={margin !== null && margin < 0 ? "text-red-600" : ""}>{margin === null ? "—" : `${margin.toFixed(0)}%`}</Td>
                    <Td><Badge tone={r.is_active ? STATUS[r.status].tone : "neutral"}>{r.is_active ? STATUS[r.status].label : "Inactive"}</Badge></Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}

function NewProductModal({ warehouses, categories, onClose }: { warehouses: Warehouse[]; categories: string[]; onClose: () => void }) {
  const priceLabel = usePriceLabel();
  const create = useApiMutation<Record<string, unknown>, Product>("post", "/inventory/products", REFRESH);
  const adjust = useApiMutation("post", "/inventory/stock/adjustments", REFRESH);
  const [f, setF] = useState({
    sku: "", name: "", category: "", barcode: "", unit: "pcs", valuation_method: "weighted_average",
    sale_price: "", tax_rate: "16", low_stock_threshold: "0", opening_qty: "", opening_cost: "", warehouse_id: warehouses[0]?.id ?? "",
  });
  const [error, setError] = useState<string | null>(null);
  const bind = (k: keyof typeof f) => ({ value: f[k], onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value }) });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (num(f.opening_qty) > 0 && !f.warehouse_id) {
      setError("Choose where the opening stock is kept (add a shop or warehouse first).");
      return;
    }
    try {
      const product = await create.mutateAsync({
        sku: f.sku.trim(), name: f.name.trim(), category: f.category.trim(), barcode: f.barcode.trim() || null, unit: f.unit || "pcs",
        valuation_method: f.valuation_method, sale_price: f.sale_price || "0", tax_rate: String(num(f.tax_rate) / 100),
        low_stock_threshold: f.low_stock_threshold || "0",
      });
      if (num(f.opening_qty) > 0) {
        await adjust.mutateAsync({
          product_id: product.id, warehouse_id: f.warehouse_id, qty_delta: f.opening_qty,
          unit_cost: f.opening_cost || "0", reason: "Opening stock", is_opening: true,
        });
      }
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <Modal open onClose={onClose} title="Add product" wide>
      <form onSubmit={submit} className="space-y-5">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div className="sm:col-span-2"><Field label="Product name"><Input required autoFocus {...bind("name")} /></Field></div>
          <Field label="SKU / code"><Input required {...bind("sku")} placeholder="CEM-50" /></Field>
          <Field label="Category">
            <Input list="product-categories" {...bind("category")} placeholder="e.g. Building" />
            <datalist id="product-categories">{categories.map((c) => <option key={c} value={c} />)}</datalist>
          </Field>
          <Field label="Barcode"><Input {...bind("barcode")} placeholder="Scan or type" /></Field>
          <Field label="Unit"><Input {...bind("unit")} placeholder="pcs, kg, bag…" /></Field>
          <Field label={priceLabel}><Input type="number" step="0.01" min="0" {...bind("sale_price")} /></Field>
          <Field label="VAT %"><Input type="number" step="0.01" min="0" max="100" {...bind("tax_rate")} /></Field>
          <Field label="Reorder level" hint="Flagged as low at or below this"><Input type="number" step="any" min="0" {...bind("low_stock_threshold")} /></Field>
          <Field label="Costing method" hint="Can't be changed later">
            <Select {...bind("valuation_method")}>
              <option value="weighted_average">Weighted average</option>
              <option value="fifo">FIFO (first in, first out)</option>
            </Select>
          </Field>
        </div>
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-brand">Opening stock (optional)</p>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Field label="Quantity on hand"><Input type="number" step="any" min="0" {...bind("opening_qty")} /></Field>
            <Field label="Cost per unit"><Input type="number" step="0.01" min="0" {...bind("opening_cost")} /></Field>
            <Field label="Kept at">
              <Select {...bind("warehouse_id")}>
                <option value="">Select…</option>
                {warehouses.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
              </Select>
            </Field>
          </div>
        </div>
        <ErrorBanner message={error} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={create.isPending || adjust.isPending}>Add product</Button>
        </div>
      </form>
    </Modal>
  );
}

const MOVEMENT_LABEL: Record<string, string> = {
  opening: "Opening stock", receipt: "Goods received", sale: "Sale", return_: "Customer return", adjustment: "Adjustment", purchase_return: "Returned to supplier",
  transfer: "Transfer", production_issue: "Used in production", production_receipt: "Produced",
};

function ProductModal({ row, warehouses, categories, canWrite, onClose }: { row: ValuationRow; warehouses: Warehouse[]; categories: string[]; canWrite: boolean; onClose: () => void }) {
  const { data: products } = useApi<Product[]>("/inventory/products");
  const product = products?.find((p) => p.id === row.product_id);
  const { data: movements } = useApi<StockMovement[]>(`/inventory/products/${row.product_id}/movements`);
  const update = useApiMutation("patch", `/inventory/products/${row.product_id}`, REFRESH);
  const adjust = useApiMutation("post", "/inventory/stock/adjustments", REFRESH);
  const [view, setView] = useState<"overview" | "edit" | "adjust">("overview");
  const [form, setForm] = useState<Record<string, string> | null>(null);
  const [adj, setAdj] = useState({ warehouse_id: warehouses[0]?.id ?? "", direction: "add", qty: "", unit_cost: "", reason: "" });
  const [error, setError] = useState<string | null>(null);
  const whNames = useMemo(() => new Map(warehouses.map((w) => [w.id, w.name])), [warehouses]);
  const priceLabel = usePriceLabel();

  function startEdit() {
    if (!product) return;
    setForm({
      name: product.name, category: product.category, barcode: product.barcode ?? "", unit: product.unit,
      sale_price: String(num(product.sale_price)), tax_rate: String(num(product.tax_rate) * 100),
      low_stock_threshold: String(num(product.low_stock_threshold)), description: product.description,
    });
    setView("edit");
  }

  async function run(fn: () => Promise<unknown>) {
    setError(null);
    try {
      await fn();
      setView("overview");
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <Modal open onClose={onClose} title={row.name} wide>
      <div className="space-y-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-center gap-4">
            <ProductImageUploader productId={row.product_id} url={row.image_url} name={row.name} canWrite={canWrite} />
            <div>
              <p className="font-mono text-xs text-slate-400">{row.sku}{product?.barcode && ` · ${product.barcode}`}</p>
              <div className="mt-1 flex flex-wrap items-center gap-2">
                <Badge tone={STATUS[row.status].tone}>{STATUS[row.status].label}</Badge>
                {row.category && <Badge>{row.category}</Badge>}
                {product && <span className="text-xs text-slate-400">{product.valuation_method === "fifo" ? "FIFO costing" : "Weighted-average costing"}</span>}
              </div>
            </div>
          </div>
          {canWrite && view === "overview" && (
            <div className="flex gap-2">
              <Button variant="secondary" onClick={startEdit} disabled={!product}>Edit details</Button>
              <Button variant="secondary" onClick={() => setView("adjust")}>Adjust stock</Button>
              {product && (
                <Button variant="ghost" onClick={() => run(() => update.mutateAsync({ is_active: !product.is_active }))}>
                  {product.is_active ? "Deactivate" : "Reactivate"}
                </Button>
              )}
            </div>
          )}
        </div>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            ["On hand", `${fmtQty(row.qty)} ${row.unit}`], ["Unit cost", fmtMoney(row.unit_cost)],
            ["Stock value", fmtMoney(row.value)], ["Sale price", fmtMoney(row.sale_price)],
          ].map(([k, v]) => (
            <div key={k} className="rounded-xl bg-slate-50 p-3 dark:bg-navy-900"><p className="text-xs text-slate-500">{k}</p><p className="mt-0.5 font-semibold">{v}</p></div>
          ))}
        </div>

        <ErrorBanner message={error} />

        {view === "edit" && form && (
          <form className="space-y-3 rounded-xl border border-slate-200 p-4 dark:border-navy-700" onSubmit={(e) => {
            e.preventDefault();
            run(() => update.mutateAsync({
              name: form.name, category: form.category, barcode: form.barcode || null, unit: form.unit, description: form.description,
              sale_price: form.sale_price || "0", tax_rate: String(num(form.tax_rate) / 100), low_stock_threshold: form.low_stock_threshold || "0",
            }));
          }}>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <div className="sm:col-span-2"><Field label="Name"><Input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field></div>
              <Field label="Category">
                <Input list="edit-categories" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} />
                <datalist id="edit-categories">{categories.map((c) => <option key={c} value={c} />)}</datalist>
              </Field>
              <Field label="Barcode"><Input value={form.barcode} onChange={(e) => setForm({ ...form, barcode: e.target.value })} /></Field>
              <Field label="Unit"><Input value={form.unit} onChange={(e) => setForm({ ...form, unit: e.target.value })} /></Field>
              <Field label="Reorder level"><Input type="number" step="any" min="0" value={form.low_stock_threshold} onChange={(e) => setForm({ ...form, low_stock_threshold: e.target.value })} /></Field>
              <Field label={priceLabel}><Input type="number" step="0.01" min="0" value={form.sale_price} onChange={(e) => setForm({ ...form, sale_price: e.target.value })} /></Field>
              <Field label="VAT %"><Input type="number" step="0.01" min="0" max="100" value={form.tax_rate} onChange={(e) => setForm({ ...form, tax_rate: e.target.value })} /></Field>
            </div>
            <Field label="Description"><Textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="secondary" onClick={() => setView("overview")}>Cancel</Button>
              <Button type="submit" disabled={update.isPending}>Save changes</Button>
            </div>
          </form>
        )}

        {view === "adjust" && (
          <form className="space-y-3 rounded-xl border border-slate-200 p-4 dark:border-navy-700" onSubmit={(e) => {
            e.preventDefault();
            const qty = num(adj.qty);
            run(() => adjust.mutateAsync({
              product_id: row.product_id, warehouse_id: adj.warehouse_id,
              qty_delta: String(adj.direction === "remove" ? -qty : qty),
              unit_cost: adj.direction === "remove" ? null : adj.unit_cost || String(num(row.unit_cost)),
              reason: adj.reason, is_opening: adj.direction === "opening",
            }));
          }}>
            <p className="text-sm text-slate-500">Use this after a stock count, or for damaged, expired or found goods. The value change posts to your accounts automatically.</p>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
              <Field label="What happened">
                <Select value={adj.direction} onChange={(e) => setAdj({ ...adj, direction: e.target.value })}>
                  <option value="add">Found / count is higher</option>
                  <option value="remove">Lost, damaged or lower</option>
                  <option value="opening">Opening balance</option>
                </Select>
              </Field>
              <Field label="Location">
                <Select required value={adj.warehouse_id} onChange={(e) => setAdj({ ...adj, warehouse_id: e.target.value })}>
                  <option value="">Select…</option>
                  {warehouses.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
                </Select>
              </Field>
              <Field label={`Quantity (${row.unit})`}><Input type="number" step="any" min="0.0001" required value={adj.qty} onChange={(e) => setAdj({ ...adj, qty: e.target.value })} /></Field>
              {adj.direction !== "remove" && (
                <Field label="Cost per unit" hint={`Blank = ${fmtMoney(row.unit_cost)}`}><Input type="number" step="0.01" min="0" value={adj.unit_cost} onChange={(e) => setAdj({ ...adj, unit_cost: e.target.value })} /></Field>
              )}
            </div>
            <Field label="Reason"><Input required maxLength={36} value={adj.reason} onChange={(e) => setAdj({ ...adj, reason: e.target.value })} placeholder="e.g. Monthly stock count" /></Field>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="secondary" onClick={() => setView("overview")}>Cancel</Button>
              <Button type="submit" disabled={adjust.isPending}>Record adjustment</Button>
            </div>
          </form>
        )}

        <div className="grid gap-5 lg:grid-cols-5">
          <div className="lg:col-span-2">
            <h3 className="mb-2 text-sm font-semibold">Where it is</h3>
            {row.locations.length ? (
              <ul className="divide-y divide-slate-100 rounded-xl border border-slate-200 dark:divide-navy-700 dark:border-navy-700">
                {row.locations.map((l) => (
                  <li key={l.warehouse_id} className="flex justify-between px-3 py-2 text-sm"><span>{l.warehouse}</span><span className="font-medium">{fmtQty(l.qty)} {row.unit}</span></li>
                ))}
              </ul>
            ) : <p className="text-sm text-slate-400">No stock at any location.</p>}
          </div>
          <div className="lg:col-span-3">
            <h3 className="mb-2 text-sm font-semibold">Stock history</h3>
            <div className="max-h-72 overflow-y-auto rounded-xl border border-slate-200 dark:border-navy-700">
              <Table>
                <thead><tr><Th>Date</Th><Th>Movement</Th><Th>Location</Th><Th>Qty</Th><Th>Cost</Th></tr></thead>
                <tbody>
                  {movements?.map((m) => (
                    <tr key={m.id}>
                      <Td className="whitespace-nowrap text-xs">{fmtDate(m.created_at)}</Td>
                      <Td>{MOVEMENT_LABEL[m.type] ?? humanize(m.type)}</Td>
                      <Td className="text-xs text-slate-500">{whNames.get(m.warehouse_id) ?? "—"}</Td>
                      <Td className={num(m.qty_delta) < 0 ? "text-red-600" : "text-emerald-600"}>{num(m.qty_delta) > 0 ? "+" : ""}{fmtQty(m.qty_delta)}</Td>
                      <Td>{fmtMoney(m.unit_cost)}</Td>
                    </tr>
                  ))}
                  {movements && !movements.length && <tr><Td colSpan={5} className="text-slate-400">No movements yet.</Td></tr>}
                </tbody>
              </Table>
            </div>
          </div>
        </div>

        <Attachments entityType="product" entityId={row.product_id} canWrite={canWrite} />
      </div>
    </Modal>
  );
}

/** Whether a product's price is the shelf price or the price before VAT is a
 * business-wide setting; say which one the box means. */
function usePriceLabel(): string {
  const { data: branding } = useBranding();
  return branding?.prices_include_tax ? "Selling price (incl. VAT)" : "Selling price (before VAT)";
}

function LocationsTab({ warehouses, report, canWrite }: { warehouses: Warehouse[]; report?: ValuationReport; canWrite: boolean }) {
  const create = useApiMutation("post", "/inventory/warehouses", REFRESH);
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);

  const stats = useMemo(() => {
    const map = new Map<string, { lines: number; value: number }>();
    for (const row of report?.rows ?? []) {
      for (const l of row.locations) {
        const s = map.get(l.warehouse_id) ?? { lines: 0, value: 0 };
        s.lines += 1;
        s.value += num(l.qty) * num(row.unit_cost);
        map.set(l.warehouse_id, s);
      }
    }
    return map;
  }, [report]);

  return (
    <div className="space-y-4">
      {canWrite && (
        <form className="flex flex-wrap items-end gap-3" onSubmit={async (e) => {
          e.preventDefault();
          setError(null);
          try {
            await create.mutateAsync({ name, code: code || name.slice(0, 4).toUpperCase() });
            setName("");
            setCode("");
          } catch (err) {
            setError(errorMessage(err));
          }
        }}>
          <Field label="Shop / warehouse name"><Input required value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Nakuru Main Store" /></Field>
          <Field label="Short code"><Input value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} placeholder="NKR" maxLength={32} /></Field>
          <Button type="submit" disabled={create.isPending}><Plus /> Add location</Button>
        </form>
      )}
      <ErrorBanner message={error} />
      {!warehouses.length ? (
        <EmptyState icon={<WarehouseIcon />} title="No shops or warehouses yet" description="Add at least one location — stock is always held somewhere, and each POS till sells from one." />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {warehouses.map((w) => {
            const s = stats.get(w.id);
            return (
              <Card key={w.id} className="p-5">
                <div className="flex items-start justify-between">
                  <div><p className="font-semibold">{w.name}</p><p className="font-mono text-xs text-slate-400">{w.code}</p></div>
                  <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-50 text-brand"><WarehouseIcon className="h-4 w-4" /></span>
                </div>
                <div className="mt-4 flex justify-between text-sm">
                  <span className="text-slate-500">{s?.lines ?? 0} product lines</span>
                  <span className="font-semibold">{fmtMoney(s?.value ?? 0)}</span>
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}

interface Transfer {
  id: string;
  created_at: string;
  from_warehouse_id: string;
  to_warehouse_id: string;
  note: string;
  lines: { product_id: string; qty: string; unit_cost: string }[];
}

function TransfersTab({ warehouses, report, canWrite }: { warehouses: Warehouse[]; report?: ValuationReport; canWrite: boolean }) {
  const { data: transfers, isLoading } = useApi<Transfer[]>("/inventory/transfers");
  const create = useApiMutation("post", "/inventory/transfers", REFRESH);
  const [show, setShow] = useState(false);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [note, setNote] = useState("");
  const [lines, setLines] = useState([{ product_id: "", qty: "" }]);
  const [error, setError] = useState<string | null>(null);
  const whNames = useMemo(() => new Map(warehouses.map((w) => [w.id, w.name])), [warehouses]);
  const productNames = useMemo(() => new Map((report?.rows ?? []).map((r) => [r.product_id, r.name])), [report]);
  const available = (productId: string) => report?.rows.find((r) => r.product_id === productId)?.locations.find((l) => l.warehouse_id === from)?.qty;
  const atSource = (report?.rows ?? []).filter((r) => r.locations.some((l) => l.warehouse_id === from && num(l.qty) > 0));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await create.mutateAsync({ from_warehouse_id: from, to_warehouse_id: to, note, lines: lines.filter((l) => l.product_id && num(l.qty) > 0) });
      setShow(false);
      setLines([{ product_id: "", qty: "" }]);
      setNote("");
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-500">Move stock between shops. It keeps its cost — a transfer never changes what stock is worth.</p>
        {canWrite && <Button onClick={() => setShow(true)} disabled={warehouses.length < 2}><ArrowRightLeft /> New transfer</Button>}
      </div>
      <Card>
        {isLoading ? <Loading /> : !transfers?.length ? (
          <div className="p-6"><EmptyState icon={<ArrowRightLeft />} title="No transfers yet" description={warehouses.length < 2 ? "Add a second shop or warehouse to move stock between them." : undefined} /></div>
        ) : (
          <Table>
            <thead><tr><Th>Date</Th><Th>From</Th><Th>To</Th><Th>Items</Th><Th>Note</Th></tr></thead>
            <tbody>
              {transfers.map((t) => (
                <tr key={t.id}>
                  <Td className="whitespace-nowrap">{fmtDate(t.created_at)}</Td>
                  <Td>{whNames.get(t.from_warehouse_id) ?? "—"}</Td>
                  <Td>{whNames.get(t.to_warehouse_id) ?? "—"}</Td>
                  <Td>{t.lines.map((l) => `${fmtQty(l.qty)} × ${productNames.get(l.product_id) ?? "item"}`).join(", ")}</Td>
                  <Td className="text-slate-500">{t.note || "—"}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <Modal open={show} onClose={() => setShow(false)} title="Transfer stock" wide>
        <form onSubmit={submit} className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="From">
              <Select required value={from} onChange={(e) => { setFrom(e.target.value); setLines([{ product_id: "", qty: "" }]); }}>
                <option value="">Select…</option>
                {warehouses.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
              </Select>
            </Field>
            <Field label="To">
              <Select required value={to} onChange={(e) => setTo(e.target.value)}>
                <option value="">Select…</option>
                {warehouses.filter((w) => w.id !== from).map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
              </Select>
            </Field>
          </div>
          {from && lines.map((line, i) => (
            <div key={i} className="grid grid-cols-12 gap-2">
              <div className="col-span-8">
                <Select value={line.product_id} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, product_id: e.target.value } : x)))}>
                  <option value="">Product…</option>
                  {atSource.map((r) => <option key={r.product_id} value={r.product_id}>{r.sku} — {r.name}</option>)}
                </Select>
              </div>
              <div className="col-span-3">
                <Input type="number" step="any" min="0" max={available(line.product_id)} placeholder={line.product_id ? `max ${fmtQty(available(line.product_id))}` : "Qty"} value={line.qty} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, qty: e.target.value } : x)))} />
              </div>
              <button type="button" className="col-span-1 text-slate-400 hover:text-red-600" onClick={() => setLines(lines.length > 1 ? lines.filter((_, j) => j !== i) : lines)}>✕</button>
            </div>
          ))}
          {from && <Button type="button" variant="secondary" className="px-3 py-1.5 text-xs" onClick={() => setLines([...lines, { product_id: "", qty: "" }])}>+ Add another product</Button>}
          <Field label="Note (optional)"><Input value={note} onChange={(e) => setNote(e.target.value)} /></Field>
          <ErrorBanner message={error} />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setShow(false)}>Cancel</Button>
            <Button type="submit" disabled={create.isPending}>Transfer</Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
