"use client";

import { Fragment, useMemo, useState } from "react";
import {
  useBranding,
  useCreateSalesOrder,
  useInvoices,
  useParties,
  useProducts,
  useSalesOrders,
} from "@/lib/api/hooks";
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
  PageHeader,
  Select,
  StatTile,
  Table,
  Tabs,
  Td,
  Th,
} from "@/components/om/primitives";
import { OrderManagePanel } from "@/components/sales/OrderManagePanel";
import { DocumentFormModal } from "@/components/sales/DocumentForm";
import { EmailDialog } from "@/components/sales/EmailDialog";
import { INVOICE_TONE, InvoiceDetailModal, isOverdue } from "@/components/sales/InvoiceDetail";
import { errorMessage, openFile, useApi, useApiMutation } from "@/lib/api/query";
import { fmtDate, fmtMoney, fmtQty, humanize, monthStart, num, today, yearStart } from "@/lib/format";
import type { AgingReport, Invoice, Quote } from "@/lib/api/types";

type Tab = "invoices" | "quotes" | "orders" | "receivables" | "reports";

export default function SalesPage() {
  const [tab, setTab] = useState<Tab>("invoices");
  const { data: branding } = useBranding();
  const currency = branding?.currency;

  return (
    <div className="space-y-6">
      <PageHeader title="Sales & Invoicing" description="Quotes, orders, tax invoices, payments, credit notes and receivables." />
      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        tabs={[
          { key: "invoices", label: "Invoices" },
          { key: "quotes", label: "Quotes" },
          { key: "orders", label: "Sales orders" },
          { key: "receivables", label: "Receivables" },
          { key: "reports", label: "Sales report" },
        ]}
      />
      {tab === "invoices" && <InvoicesTab currency={currency} />}
      {tab === "quotes" && <QuotesTab currency={currency} />}
      {tab === "orders" && <OrdersTab />}
      {tab === "receivables" && <ReceivablesTab currency={currency} />}
      {tab === "reports" && <ReportsTab currency={currency} />}
    </div>
  );
}

function usePartyNames() {
  const { data: parties } = useParties();
  return useMemo(() => new Map((parties ?? []).map((p) => [p.id, p.name])), [parties]);
}

// ---------------------------------------------------------------- invoices

function InvoicesTab({ currency }: { currency?: string }) {
  const { data: invoices, isLoading } = useInvoices();
  const names = usePartyNames();
  const [showNew, setShowNew] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "unpaid" | "overdue" | "paid" | "void">("all");
  const [search, setSearch] = useState("");

  const rows = (invoices ?? []).filter((inv) => {
    const balance = num(inv.total) - num(inv.amount_paid) - num(inv.amount_credited);
    if (filter === "unpaid" && !(inv.status !== "void" && balance > 0)) return false;
    if (filter === "overdue" && !isOverdue(inv)) return false;
    if (filter === "paid" && inv.status !== "paid") return false;
    if (filter === "void" && inv.status !== "void") return false;
    const q = search.toLowerCase();
    return !q || inv.invoice_no.toLowerCase().includes(q) || (names.get(inv.party_id) ?? "").toLowerCase().includes(q);
  });

  const outstanding = (invoices ?? [])
    .filter((i) => i.status !== "void")
    .reduce((s, i) => s + num(i.total) - num(i.amount_paid) - num(i.amount_credited), 0);
  const overdue = (invoices ?? []).filter(isOverdue);
  const overdueTotal = overdue.reduce((s, i) => s + num(i.total) - num(i.amount_paid) - num(i.amount_credited), 0);
  const thisMonth = (invoices ?? []).filter((i) => i.status !== "void" && (i.issue_date ?? "") >= monthStart());

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <StatTile label="Outstanding" value={fmtMoney(outstanding, currency)} />
        <StatTile label="Overdue" value={fmtMoney(overdueTotal, currency)} sub={`${overdue.length} invoice(s)`} />
        <StatTile
          label="Invoiced this month"
          value={fmtMoney(thisMonth.reduce((s, i) => s + num(i.total), 0), currency)}
          sub={`${thisMonth.length} invoice(s)`}
        />
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <div className="w-full sm:w-64">
          <Input placeholder="Search number or customer…" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <div className="w-40">
          <Select value={filter} onChange={(e) => setFilter(e.target.value as typeof filter)}>
            <option value="all">All invoices</option>
            <option value="unpaid">Unpaid</option>
            <option value="overdue">Overdue</option>
            <option value="paid">Paid</option>
            <option value="void">Void</option>
          </Select>
        </div>
        <div className="ml-auto">
          <Button onClick={() => setShowNew(true)}>New invoice</Button>
        </div>
      </div>

      <Card>
        {isLoading ? (
          <Loading />
        ) : !rows.length ? (
          <div className="p-6">
            <EmptyState title="No invoices" description="Create an invoice, convert a quote, or invoice a delivered order." />
          </div>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Number</Th>
                <Th>Customer</Th>
                <Th>Date</Th>
                <Th>Due</Th>
                <Th>Total</Th>
                <Th>Balance</Th>
                <Th>Status</Th>
                <Th></Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((inv) => {
                const balance = inv.status === "void" ? 0 : num(inv.total) - num(inv.amount_paid) - num(inv.amount_credited);
                return (
                  <tr key={inv.id} className="cursor-pointer hover:bg-slate-50 dark:hover:bg-navy-700/40" onClick={() => setOpenId(inv.id)}>
                    <Td className="font-medium">{inv.invoice_no || inv.id.slice(0, 8)}</Td>
                    <Td>{names.get(inv.party_id) ?? "—"}</Td>
                    <Td>{fmtDate(inv.issue_date)}</Td>
                    <Td className={isOverdue(inv) ? "text-red-600" : ""}>{fmtDate(inv.due_date)}</Td>
                    <Td className="tabular-nums">{fmtMoney(inv.total)}</Td>
                    <Td className="tabular-nums">{fmtMoney(balance)}</Td>
                    <Td>
                      <Badge tone={isOverdue(inv) ? "danger" : INVOICE_TONE[inv.status] ?? "neutral"}>
                        {isOverdue(inv) ? "Overdue" : humanize(inv.status)}
                      </Badge>
                    </Td>
                    <Td>
                      <Button
                        variant="secondary"
                        className="px-2 py-1 text-xs"
                        onClick={(e) => {
                          e.stopPropagation();
                          openFile(`/sales/invoices/${inv.id}/pdf`);
                        }}
                      >
                        PDF
                      </Button>
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        )}
      </Card>

      <DocumentFormModal kind="invoice" open={showNew} onClose={() => setShowNew(false)} onCreated={setOpenId} currency={currency} />
      <InvoiceDetailModal invoiceId={openId} onClose={() => setOpenId(null)} currency={currency} />
    </div>
  );
}

// ------------------------------------------------------------------ quotes

const QUOTE_TONE: Record<string, "neutral" | "success" | "warning" | "danger"> = {
  draft: "neutral",
  sent: "warning",
  accepted: "success",
  declined: "danger",
  converted: "success",
};

function QuotesTab({ currency }: { currency?: string }) {
  const { data: quotes, isLoading } = useApi<Quote[]>("/sales/quotes");
  const names = usePartyNames();
  const [showNew, setShowNew] = useState(false);
  const [openInvoice, setOpenInvoice] = useState<string | null>(null);
  const [emailQuote, setEmailQuote] = useState<Quote | null>(null);
  const [error, setError] = useState<string | null>(null);
  const setStatus = useApiMutation<{ id: string; status: string }>("post", (b) => `/sales/quotes/${b.id}/status`, [["sales"]]);
  const convert = useApiMutation<{ id: string }, Invoice>("post", (b) => `/sales/quotes/${b.id}/convert`, [["sales"], ["accounting"]]);

  async function act(fn: () => Promise<unknown>) {
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button onClick={() => setShowNew(true)}>New quote</Button>
      </div>
      <ErrorBanner message={error} />
      <Card>
        {isLoading ? (
          <Loading />
        ) : !quotes?.length ? (
          <div className="p-6">
            <EmptyState title="No quotations yet" description="Send a customer a priced quote, then convert it to an invoice in one click." />
          </div>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Number</Th>
                <Th>Customer</Th>
                <Th>Date</Th>
                <Th>Valid until</Th>
                <Th>Total</Th>
                <Th>Status</Th>
                <Th></Th>
              </tr>
            </thead>
            <tbody>
              {quotes.map((q) => (
                <tr key={q.id}>
                  <Td className="font-medium">{q.quote_no}</Td>
                  <Td>{names.get(q.party_id) ?? "—"}</Td>
                  <Td>{fmtDate(q.issue_date)}</Td>
                  <Td>{fmtDate(q.valid_until)}</Td>
                  <Td className="tabular-nums">{fmtMoney(q.total)}</Td>
                  <Td>
                    <Badge tone={QUOTE_TONE[q.status]}>{humanize(q.status)}</Badge>
                  </Td>
                  <Td>
                    <div className="flex flex-wrap justify-end gap-1">
                      <Button variant="secondary" className="px-2 py-1 text-xs" onClick={() => openFile(`/sales/quotes/${q.id}/pdf`)}>
                        PDF
                      </Button>
                      {q.status !== "converted" && q.status !== "declined" && (
                        <Button variant="secondary" className="px-2 py-1 text-xs" onClick={() => setEmailQuote(q)}>Email</Button>
                      )}
                      {q.status === "draft" && (
                        <Button variant="secondary" className="px-2 py-1 text-xs" onClick={() => act(() => setStatus.mutateAsync({ id: q.id, status: "sent" }))}>
                          Mark sent
                        </Button>
                      )}
                      {(q.status === "draft" || q.status === "sent") && (
                        <Button variant="secondary" className="px-2 py-1 text-xs" onClick={() => act(() => setStatus.mutateAsync({ id: q.id, status: "declined" }))}>
                          Declined
                        </Button>
                      )}
                      {q.status !== "converted" && q.status !== "declined" && (
                        <Button
                          className="px-2 py-1 text-xs"
                          onClick={() =>
                            act(async () => {
                              const inv = await convert.mutateAsync({ id: q.id });
                              setOpenInvoice(inv.id);
                            })
                          }
                        >
                          Convert to invoice
                        </Button>
                      )}
                      {q.converted_invoice_id && (
                        <Button variant="secondary" className="px-2 py-1 text-xs" onClick={() => setOpenInvoice(q.converted_invoice_id)}>
                          View invoice
                        </Button>
                      )}
                    </div>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <DocumentFormModal kind="quote" open={showNew} onClose={() => setShowNew(false)} currency={currency} />
      {emailQuote && (
        <EmailDialog open onClose={() => setEmailQuote(null)} title={`Email ${emailQuote.quote_no}`} endpoint={`/sales/quotes/${emailQuote.id}/email`} />
      )}
      <InvoiceDetailModal invoiceId={openInvoice} onClose={() => setOpenInvoice(null)} currency={currency} />
    </div>
  );
}

// ------------------------------------------------------------------ orders

const ORDER_TONE: Record<string, "neutral" | "success" | "warning" | "danger"> = {
  draft: "neutral",
  confirmed: "warning",
  partially_delivered: "warning",
  delivered: "success",
  invoiced: "success",
};

function OrdersTab() {
  const { data: orders, isLoading } = useSalesOrders();
  const { data: parties } = useParties();
  const { data: products } = useProducts();
  const names = usePartyNames();
  const createOrder = useCreateSalesOrder();

  const [showForm, setShowForm] = useState(false);
  const [partyId, setPartyId] = useState("");
  const [productId, setProductId] = useState("");
  const [qty, setQty] = useState("1");
  const [unitPrice, setUnitPrice] = useState("0");
  const [taxRate, setTaxRate] = useState("16");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const customers = parties?.filter((p) => p.kind === "customer" || p.kind === "both") ?? [];

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await createOrder.mutateAsync({
        party_id: partyId,
        lines: [{ product_id: productId, qty, unit_price: unitPrice, tax_rate: String(num(taxRate) / 100) }],
      });
      setShowForm(false);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-500">Order → deliver from a warehouse → invoice → collect payment.</p>
        <Button onClick={() => setShowForm((v) => !v)}>{showForm ? "Cancel" : "New order"}</Button>
      </div>

      {showForm && (
        <Card className="p-6">
          <form onSubmit={onSubmit} className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div>
              <Label>Customer</Label>
              <Select required value={partyId} onChange={(e) => setPartyId(e.target.value)}>
                <option value="">Select a customer…</option>
                {customers.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </Select>
            </div>
            <div>
              <Label>Product</Label>
              <Select
                required
                value={productId}
                onChange={(e) => {
                  setProductId(e.target.value);
                  const p = products?.find((x) => x.id === e.target.value);
                  if (p) {
                    setUnitPrice(String(num(p.sale_price)));
                    setTaxRate(String(num(p.tax_rate) * 100));
                  }
                }}
              >
                <option value="">Select a product…</option>
                {products?.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.sku} — {p.name} ({fmtQty(p.stock_qty)} in stock)
                  </option>
                ))}
              </Select>
            </div>
            <Field label="Quantity">
              <Input type="number" min="1" step="any" value={qty} onChange={(e) => setQty(e.target.value)} />
            </Field>
            <Field label="Unit price">
              <Input type="number" step="0.01" value={unitPrice} onChange={(e) => setUnitPrice(e.target.value)} />
            </Field>
            <Field label="VAT %">
              <Input type="number" step="0.01" value={taxRate} onChange={(e) => setTaxRate(e.target.value)} />
            </Field>
            <div className="flex items-end">
              <Button type="submit" disabled={createOrder.isPending || !customers.length}>
                {createOrder.isPending ? "Saving…" : "Create order"}
              </Button>
            </div>
          </form>
          <div className="mt-3"><ErrorBanner message={error} /></div>
          {!customers.length && <p className="mt-3 text-xs text-amber-600">Add a customer in CRM before creating an order.</p>}
        </Card>
      )}

      <Card>
        {isLoading ? (
          <Loading />
        ) : !orders?.length ? (
          <div className="p-6">
            <EmptyState title="No sales orders yet" />
          </div>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Number</Th>
                <Th>Customer</Th>
                <Th>Status</Th>
                <Th>Subtotal</Th>
                <Th>Tax</Th>
                <Th>Total</Th>
                <Th></Th>
              </tr>
            </thead>
            <tbody>
              {orders.map((o) => (
                <Fragment key={o.id}>
                  <tr>
                    <Td className="font-medium">{o.so_no || o.id.slice(0, 8)}</Td>
                    <Td>{names.get(o.party_id) ?? "—"}</Td>
                    <Td>
                      <Badge tone={ORDER_TONE[o.status] ?? "neutral"}>{humanize(o.status)}</Badge>
                    </Td>
                    <Td className="tabular-nums">{fmtMoney(o.subtotal)}</Td>
                    <Td className="tabular-nums">{fmtMoney(o.tax_total)}</Td>
                    <Td className="tabular-nums">{fmtMoney(o.total)}</Td>
                    <Td>
                      <Button variant="secondary" className="px-2 py-1 text-xs" onClick={() => setExpandedId(expandedId === o.id ? null : o.id)}>
                        {expandedId === o.id ? "Close" : "Manage"}
                      </Button>
                    </Td>
                  </tr>
                  {expandedId === o.id && (
                    <tr>
                      <Td colSpan={7} className="bg-slate-50 dark:bg-navy-900">
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
  );
}

// ------------------------------------------------------------- receivables

function ReceivablesTab({ currency }: { currency?: string }) {
  const [asOf, setAsOf] = useState(today());
  const [start, setStart] = useState(yearStart());
  const { data: aging, isLoading } = useApi<AgingReport>(`/sales/reports/ar-aging?as_of=${asOf}`);
  const buckets: [keyof AgingReport["totals"], string][] = [
    ["current", "Current"],
    ["days_1_30", "1–30"],
    ["days_31_60", "31–60"],
    ["days_61_90", "61–90"],
    ["over_90", "90+"],
    ["total", "Total"],
  ];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Aged as of">
          <Input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} />
        </Field>
        <Field label="Statement period from">
          <Input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
        </Field>
      </div>
      <Card>
        {isLoading ? (
          <Loading />
        ) : !aging?.rows.length ? (
          <div className="p-6">
            <EmptyState title="Nothing outstanding" description="Every posted invoice is settled." />
          </div>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Customer</Th>
                {buckets.map(([, label]) => <Th key={label}>{label}</Th>)}
                <Th></Th>
              </tr>
            </thead>
            <tbody>
              {aging.rows.map((row) => (
                <tr key={row.party_id}>
                  <Td className="font-medium">{row.party_name}</Td>
                  {buckets.map(([key]) => (
                    <Td key={key} className={`tabular-nums ${key === "over_90" && num(row[key]) > 0 ? "text-red-600" : ""} ${key === "total" ? "font-semibold" : ""}`}>
                      {num(row[key]) ? fmtMoney(row[key]) : "—"}
                    </Td>
                  ))}
                  <Td>
                    <Button
                      variant="secondary"
                      className="px-2 py-1 text-xs"
                      onClick={() => openFile(`/sales/customers/${row.party_id}/statement/pdf?start=${start}&end=${asOf}`)}
                    >
                      Statement
                    </Button>
                  </Td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <Td className="font-semibold">Total {currency ? `(${currency})` : ""}</Td>
                {buckets.map(([key]) => (
                  <Td key={key} className="font-semibold tabular-nums">{fmtMoney(aging.totals[key])}</Td>
                ))}
                <Td>{""}</Td>
              </tr>
            </tfoot>
          </Table>
        )}
      </Card>
    </div>
  );
}

// ----------------------------------------------------------------- reports

interface SalesSummary {
  invoice_count: number;
  total_invoiced: string;
  by_product: { product_id: string | null; description: string; qty: string; revenue: string }[];
  by_customer: { party_id: string; party_name: string; revenue: string }[];
}

function ReportsTab({ currency }: { currency?: string }) {
  const [start, setStart] = useState(monthStart());
  const [end, setEnd] = useState(today());
  const { data, isLoading } = useApi<SalesSummary>(`/sales/reports/summary?start=${start}&end=${end}`);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="From"><Input type="date" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
        <Field label="To"><Input type="date" value={end} onChange={(e) => setEnd(e.target.value)} /></Field>
      </div>
      {isLoading || !data ? (
        <Loading />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <StatTile label="Invoiced (incl. VAT)" value={fmtMoney(data.total_invoiced, currency)} />
            <StatTile label="Invoices" value={String(data.invoice_count)} />
          </div>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Card>
              <p className="border-b border-slate-200 px-4 py-3 text-sm font-semibold dark:border-navy-700">Top products (net of VAT)</p>
              <Table>
                <thead><tr><Th>Item</Th><Th>Qty</Th><Th>Revenue</Th></tr></thead>
                <tbody>
                  {data.by_product.map((r) => (
                    <tr key={r.product_id ?? r.description}>
                      <Td>{r.description}</Td>
                      <Td>{fmtQty(r.qty)}</Td>
                      <Td className="tabular-nums">{fmtMoney(r.revenue)}</Td>
                    </tr>
                  ))}
                  {!data.by_product.length && <tr><Td colSpan={3} className="text-slate-400">No sales in this period</Td></tr>}
                </tbody>
              </Table>
            </Card>
            <Card>
              <p className="border-b border-slate-200 px-4 py-3 text-sm font-semibold dark:border-navy-700">Top customers (net of VAT)</p>
              <Table>
                <thead><tr><Th>Customer</Th><Th>Revenue</Th></tr></thead>
                <tbody>
                  {data.by_customer.map((r) => (
                    <tr key={r.party_id}>
                      <Td>{r.party_name}</Td>
                      <Td className="tabular-nums">{fmtMoney(r.revenue)}</Td>
                    </tr>
                  ))}
                  {!data.by_customer.length && <tr><Td colSpan={2} className="text-slate-400">No sales in this period</Td></tr>}
                </tbody>
              </Table>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
