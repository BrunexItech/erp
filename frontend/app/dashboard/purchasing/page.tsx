"use client";

import { Fragment, useState } from "react";
import { useCreatePurchaseOrder, useMe, useParties, usePurchaseOrders, useProducts, useVendorBills } from "@/lib/api/hooks";

type Tab = "orders" | "bills" | "payables";

export default function PurchasingPage() {
  const [tab, setTab] = useState<Tab>("orders");
  return (
    <div className="space-y-6">
      <PageHeader title="Purchasing & Payables" description="Purchase orders, goods receipts, supplier bills, expenses and payments." />
      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        tabs={[
          { key: "orders", label: "Purchase orders" },
          { key: "bills", label: "Bills & expenses" },
          { key: "payables", label: "Payables aging" },
        ]}
      />
      {tab === "orders" && <OrdersTab />}
      {tab === "bills" && <BillsTab />}
      {tab === "payables" && <PayablesTab />}
    </div>
  );
}
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  Field,
  Input,
  Label,
  Loading,
  Modal,
  PageHeader,
  Select,
  Table,
  Tabs,
  Td,
  Th,
} from "@/components/om/primitives";
import { OrderManagePanel } from "@/components/purchasing/OrderManagePanel";
import { errorMessage, useApi, useApiMutation } from "@/lib/api/query";
import { fmtDate, fmtMoney, humanize, num, today } from "@/lib/format";
import type { Account, AgingReport, VendorBill } from "@/lib/api/types";

const STATUS_TONE: Record<string, "neutral" | "success" | "warning" | "danger"> = {
  draft: "neutral",
  confirmed: "warning",
  received: "success",
  partially_received: "warning",
  paid: "success",
  posted: "warning",
};

function OrdersTab() {
  const { data: orders, isLoading } = usePurchaseOrders();
  const { data: parties } = useParties();
  const { data: products } = useProducts();
  const createOrder = useCreatePurchaseOrder();

  const [showForm, setShowForm] = useState(false);
  const [partyId, setPartyId] = useState("");
  const [productId, setProductId] = useState("");
  const [qty, setQty] = useState("1");
  const [unitCost, setUnitCost] = useState("0");
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const vendors = parties?.filter((p) => p.kind === "vendor" || p.kind === "both") ?? [];

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    await createOrder.mutateAsync({
      party_id: partyId,
      lines: [{ product_id: productId, qty_ordered: qty, unit_cost: unitCost }],
    });
    setShowForm(false);
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-500">PO → receive goods at actual cost → bill → pay.</p>
        <Button onClick={() => setShowForm((v) => !v)}>{showForm ? "Cancel" : "New PO"}</Button>
      </div>

      {showForm && (
        <Card className="p-6">
          <form onSubmit={onSubmit} className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <Label>Vendor</Label>
              <Select required value={partyId} onChange={(e) => setPartyId(e.target.value)}>
                <option value="">Select a vendor…</option>
                {vendors.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.name}
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <Label>Product</Label>
              <Select required value={productId} onChange={(e) => setProductId(e.target.value)}>
                <option value="">Select a product…</option>
                {products?.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.sku} — {p.name}
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <Label>Quantity ordered</Label>
              <Input type="number" min="1" step="1" value={qty} onChange={(e) => setQty(e.target.value)} />
            </div>
            <div>
              <Label>Unit cost</Label>
              <Input type="number" step="0.01" value={unitCost} onChange={(e) => setUnitCost(e.target.value)} />
            </div>
            <div className="flex items-end">
              <Button type="submit" disabled={createOrder.isPending || !vendors.length}>
                {createOrder.isPending ? "Saving…" : "Create PO"}
              </Button>
            </div>
          </form>
          {!vendors.length && (
            <p className="mt-3 text-xs text-amber-600">Add a vendor in CRM before creating a purchase order.</p>
          )}
        </Card>
      )}

      <div>
        <h2 className="mb-2 text-sm font-semibold text-slate-500 dark:text-slate-400">Purchase orders</h2>
        <Card>
          {isLoading ? (
            <p className="p-6 text-sm text-slate-400">Loading…</p>
          ) : !orders?.length ? (
            <div className="p-6">
              <EmptyState title="No purchase orders yet" />
            </div>
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>Number</Th>
                  <Th>Vendor</Th>
                  <Th>Status</Th>
                  <Th>Total</Th>
                  <Th></Th>
                </tr>
              </thead>
              <tbody>
                {orders.map((o) => (
                  <Fragment key={o.id}>
                    <tr>
                      <Td className="font-medium">{o.po_no || o.id.slice(0, 8)}</Td>
                      <Td>{parties?.find((p) => p.id === o.party_id)?.name ?? "—"}</Td>
                      <Td>
                        <Badge tone={STATUS_TONE[o.status] ?? "neutral"}>{humanize(o.status)}</Badge>
                      </Td>
                      <Td className="tabular-nums">{fmtMoney(o.total)}</Td>
                      <Td>
                        <Button
                          variant="secondary"
                          className="px-2 py-1 text-xs"
                          onClick={() => setExpandedId(expandedId === o.id ? null : o.id)}
                        >
                          {expandedId === o.id ? "Close" : "Manage"}
                        </Button>
                      </Td>
                    </tr>
                    {expandedId === o.id && (
                      <tr>
                        <Td colSpan={5} className="bg-slate-50 dark:bg-navy-900">
                          <OrderManagePanel order={o} />
                        </Td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </Table>
          )}
        </Card>
      </div>

    </div>
  );
}

const BILL_TONE: Record<string, "neutral" | "success" | "warning" | "danger"> = {
  posted: "warning",
  partially_paid: "warning",
  paid: "success",
  void: "danger",
};

function BillsTab() {
  const { data: bills, isLoading } = useVendorBills();
  const { data: parties } = useParties();
  const { data: me } = useMe();
  const canSeeAccounts = !!me && (me.permissions.includes("*") || me.permissions.includes("accounting.read"));
  const { data: accounts } = useApi<Account[]>(canSeeAccounts ? "/accounting/accounts" : null);
  const create = useApiMutation("post", "/purchasing/vendor-bills", [["purchasing"], ["accounting"]]);
  const pay = useApiMutation("post", "/purchasing/vendor-bills/payments", [["purchasing"], ["accounting"]]);
  const [showNew, setShowNew] = useState(false);
  const [paying, setPaying] = useState<VendorBill | null>(null);
  const [error, setError] = useState<string | null>(null);
  const vendors = parties?.filter((p) => p.kind === "vendor" || p.kind === "both") ?? [];
  const expenseAccounts = accounts?.filter((a) => a.is_active && (a.type === "expense" || a.type === "asset")) ?? [];
  const [form, setForm] = useState({
    party_id: "", vendor_reference: "", bill_date: today(), due_date: "", expense_account_id: "",
    subtotal: "", vat: "16", memo: "",
  });
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState("bank");
  const names = new Map((parties ?? []).map((p) => [p.id, p.name]));

  const vat = Math.round(num(form.subtotal) * num(form.vat)) / 100;

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
      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-500">Bills from purchase orders appear here; record rent, utilities and other expenses directly.</p>
        <Button onClick={() => setShowNew(true)}>New expense bill</Button>
      </div>
      <ErrorBanner message={!showNew && !paying ? error : null} />
      <Card>
        {isLoading ? <Loading /> : !bills?.length ? (
          <div className="p-6"><EmptyState title="No vendor bills yet" /></div>
        ) : (
          <Table>
            <thead>
              <tr><Th>Number</Th><Th>Vendor</Th><Th>Their ref.</Th><Th>Date</Th><Th>Due</Th><Th>Total</Th><Th>Status</Th><Th></Th></tr>
            </thead>
            <tbody>
              {bills.map((b) => (
                <tr key={b.id}>
                  <Td className="font-medium">{b.bill_no || b.id.slice(0, 8)}</Td>
                  <Td>{names.get(b.party_id) ?? "—"}{b.memo && <p className="text-xs text-slate-400">{b.memo}</p>}</Td>
                  <Td>{b.vendor_reference || "—"}</Td>
                  <Td>{fmtDate(b.bill_date)}</Td>
                  <Td className={b.status !== "paid" && b.due_date && b.due_date < today() ? "text-red-600" : ""}>{fmtDate(b.due_date)}</Td>
                  <Td className="tabular-nums">{fmtMoney(b.total)}</Td>
                  <Td><Badge tone={BILL_TONE[b.status] ?? "neutral"}>{humanize(b.status)}</Badge></Td>
                  <Td>
                    {(b.status === "posted" || b.status === "partially_paid") && (
                      <Button className="px-2 py-1 text-xs" onClick={() => { setPaying(b); setAmount(""); }}>Pay</Button>
                    )}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <Modal open={showNew} onClose={() => setShowNew(false)} title="New expense bill" wide>
        <form
          className="space-y-4"
          onSubmit={async (e) => {
            e.preventDefault();
            const ok = await act(() =>
              create.mutateAsync({
                party_id: form.party_id,
                vendor_reference: form.vendor_reference,
                bill_date: form.bill_date,
                due_date: form.due_date || null,
                expense_account_id: form.expense_account_id || null,
                memo: form.memo,
                subtotal: form.subtotal,
                tax_total: vat.toFixed(2),
              })
            );
            if (ok) setShowNew(false);
          }}
        >
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Field label="Vendor">
              <Select required value={form.party_id} onChange={(e) => setForm({ ...form, party_id: e.target.value })}>
                <option value="">Select…</option>
                {vendors.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
              </Select>
            </Field>
            <Field label="Their invoice no."><Input value={form.vendor_reference} onChange={(e) => setForm({ ...form, vendor_reference: e.target.value })} /></Field>
            <Field label="Expense account">
              <Select value={form.expense_account_id} onChange={(e) => setForm({ ...form, expense_account_id: e.target.value })}>
                <option value="">General & administrative</option>
                {expenseAccounts.map((a) => <option key={a.id} value={a.id}>{a.code} · {a.name}</option>)}
              </Select>
            </Field>
            <Field label="Bill date"><Input type="date" value={form.bill_date} onChange={(e) => setForm({ ...form, bill_date: e.target.value })} /></Field>
            <Field label="Due date" hint="Blank = vendor terms (30 days)"><Input type="date" value={form.due_date} onChange={(e) => setForm({ ...form, due_date: e.target.value })} /></Field>
            <Field label="Description"><Input value={form.memo} onChange={(e) => setForm({ ...form, memo: e.target.value })} placeholder="e.g. October rent" /></Field>
            <Field label="Amount before VAT"><Input type="number" step="0.01" min="0.01" required value={form.subtotal} onChange={(e) => setForm({ ...form, subtotal: e.target.value })} /></Field>
            <Field label="VAT %" hint="Claimable input VAT"><Input type="number" step="0.01" min="0" value={form.vat} onChange={(e) => setForm({ ...form, vat: e.target.value })} /></Field>
            <div className="flex items-end pb-2 text-sm">Total: <strong className="ml-1">{fmtMoney(num(form.subtotal) + vat)}</strong></div>
          </div>
          <ErrorBanner message={error} />
          <div className="flex justify-end"><Button type="submit" disabled={create.isPending}>Record bill</Button></div>
        </form>
      </Modal>

      <Modal open={!!paying} onClose={() => setPaying(null)} title={`Pay ${paying?.bill_no ?? "bill"}`}>
        <form
          className="space-y-3"
          onSubmit={async (e) => {
            e.preventDefault();
            if (!paying) return;
            if (await act(() => pay.mutateAsync({ vendor_bill_id: paying.id, amount: amount || paying.total, method, payment_date: today() }))) setPaying(null);
          }}
        >
          <div className="grid grid-cols-2 gap-3">
            <Field label="Amount" hint={`Bill total ${fmtMoney(paying?.total)}`}>
              <Input type="number" step="0.01" min="0.01" placeholder={paying?.total} value={amount} onChange={(e) => setAmount(e.target.value)} />
            </Field>
            <Field label="Method">
              <Select value={method} onChange={(e) => setMethod(e.target.value)}>
                <option value="bank">Bank transfer</option><option value="mpesa">M-Pesa</option><option value="cash">Cash</option><option value="cheque">Cheque</option>
              </Select>
            </Field>
          </div>
          <ErrorBanner message={error} />
          <div className="flex justify-end"><Button type="submit" disabled={pay.isPending}>Record payment</Button></div>
        </form>
      </Modal>
    </div>
  );
}

function PayablesTab() {
  const [asOf, setAsOf] = useState(today());
  const { data: aging, isLoading } = useApi<AgingReport>(`/purchasing/reports/ap-aging?as_of=${asOf}`);
  const buckets: [keyof AgingReport["totals"], string][] = [
    ["current", "Current"], ["days_1_30", "1–30"], ["days_31_60", "31–60"], ["days_61_90", "61–90"], ["over_90", "90+"], ["total", "Total"],
  ];
  return (
    <div className="space-y-4">
      <Field label="Aged as of"><Input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} /></Field>
      <Card>
        {isLoading ? <Loading /> : !aging?.rows.length ? (
          <div className="p-6"><EmptyState title="Nothing owed to suppliers" /></div>
        ) : (
          <Table>
            <thead><tr><Th>Vendor</Th>{buckets.map(([, l]) => <Th key={l}>{l}</Th>)}</tr></thead>
            <tbody>
              {aging.rows.map((r) => (
                <tr key={r.party_id}>
                  <Td className="font-medium">{r.party_name}</Td>
                  {buckets.map(([k]) => <Td key={k} className={`tabular-nums ${k === "total" ? "font-semibold" : ""}`}>{num(r[k]) ? fmtMoney(r[k]) : "—"}</Td>)}
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <Td className="font-semibold">Total</Td>
                {buckets.map(([k]) => <Td key={k} className="font-semibold tabular-nums">{fmtMoney(aging.totals[k])}</Td>)}
              </tr>
            </tfoot>
          </Table>
        )}
      </Card>
    </div>
  );
}
