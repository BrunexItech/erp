"use client";

import { useState } from "react";
import {
  Badge,
  Button,
  Checkbox,
  ErrorBanner,
  Field,
  Input,
  Loading,
  Modal,
  Select,
  Table,
  Td,
  Th,
} from "@/components/om/primitives";
import { errorMessage, openFile, useApi, useApiMutation } from "@/lib/api/query";
import { EmailDialog } from "./EmailDialog";
import { fmtDate, fmtMoney, fmtQty, humanize, num, today } from "@/lib/format";
import type { CreditNote, InvoiceDetail as InvoiceDetailT, Payment, Warehouse } from "@/lib/api/types";

export const INVOICE_TONE: Record<string, "neutral" | "success" | "warning" | "danger"> = {
  draft: "neutral",
  posted: "warning",
  partially_paid: "warning",
  paid: "success",
  void: "danger",
};

const REFRESH = [["sales"], ["accounting"], ["inventory"]];

export function isOverdue(inv: { status: string; due_date: string | null }) {
  return (inv.status === "posted" || inv.status === "partially_paid") && !!inv.due_date && inv.due_date < today();
}

export function InvoiceDetailModal({ invoiceId, onClose, currency }: { invoiceId: string | null; onClose: () => void; currency?: string }) {
  const { data: invoice, isLoading } = useApi<InvoiceDetailT>(invoiceId ? `/sales/invoices/${invoiceId}` : null);
  const { data: payments } = useApi<Payment[]>(invoiceId ? `/sales/payments?invoice_id=${invoiceId}` : null);
  const { data: credits } = useApi<CreditNote[]>(invoiceId ? `/sales/credit-notes?invoice_id=${invoiceId}` : null);
  const { data: warehouses } = useApi<Warehouse[]>("/inventory/warehouses");

  const pay = useApiMutation("post", "/sales/invoices/payments", REFRESH);
  const credit = useApiMutation("post", "/sales/credit-notes", REFRESH);
  const resubmit = useApiMutation<undefined>("post", () => `/sales/invoices/${invoiceId}/etims`, REFRESH);
  const voidInvoice = useApiMutation<{ reason: string }>("post", () => `/sales/invoices/${invoiceId}/void`, REFRESH);

  const [panel, setPanel] = useState<"none" | "pay" | "credit" | "void">("none");
  const [emailing, setEmailing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState("mpesa");
  const [payDate, setPayDate] = useState(today());
  const [reference, setReference] = useState("");
  const [creditQty, setCreditQty] = useState<Record<string, string>>({});
  const [wholeInvoice, setWholeInvoice] = useState(true);
  const [reason, setReason] = useState("");
  const [restockWarehouse, setRestockWarehouse] = useState("");

  async function run(fn: () => Promise<unknown>) {
    setError(null);
    try {
      await fn();
      setPanel("none");
      setAmount("");
      setReference("");
      setReason("");
      setCreditQty({});
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const balance = num(invoice?.balance_due);
  const open = invoice && invoice.status !== "void" && invoice.status !== "paid";
  const hasProducts = invoice?.lines.some((l) => l.product_id);

  return (
    <Modal open={!!invoiceId} onClose={onClose} title={invoice ? `Invoice ${invoice.invoice_no}` : "Invoice"} wide>
      {isLoading || !invoice ? (
        <Loading />
      ) : (
        <div className="space-y-5">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="text-lg font-semibold text-navy-900 dark:text-white">{invoice.party_name}</p>
              <p className="text-sm text-slate-500">
                Issued {fmtDate(invoice.issue_date)} · Due {fmtDate(invoice.due_date)}
                {invoice.reference && ` · Ref ${invoice.reference}`}
              </p>
              <div className="mt-2 flex gap-2">
                <Badge tone={INVOICE_TONE[invoice.status] ?? "neutral"}>{humanize(invoice.status)}</Badge>
                {isOverdue(invoice) && <Badge tone="danger">Overdue</Badge>}
                {invoice.etims_status === "submitted" && <Badge tone="info">KRA {invoice.etims_reference}</Badge>}
                {invoice.etims_status === "failed" && <Badge tone="warning">Not yet sent to KRA</Badge>}
              </div>
              {invoice.etims_status === "failed" && (
                <p className="mt-2 max-w-md text-xs text-amber-700">
                  {invoice.etims_error}{" "}
                  <button className="font-medium underline" onClick={() => run(() => resubmit.mutateAsync(undefined))}>Try again</button>
                </p>
              )}
            </div>
            <div className="text-right">
              <p className="text-xs uppercase tracking-wide text-slate-500">Balance due</p>
              <p className="text-2xl font-semibold text-navy-900 dark:text-white">{fmtMoney(balance, currency)}</p>
              <p className="text-xs text-slate-500">of {fmtMoney(invoice.total, currency)}</p>
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={() => openFile(`/sales/invoices/${invoice.id}/pdf`)}>
              Download PDF
            </Button>
            {invoice.status !== "void" && <Button variant="secondary" onClick={() => setEmailing(true)}>Email to customer</Button>}
            {open && <Button onClick={() => { setAmount(String(balance)); setPanel("pay"); }}>Record payment</Button>}
            {invoice.status !== "void" && num(invoice.amount_credited) < num(invoice.total) && (
              <Button variant="secondary" onClick={() => setPanel("credit")}>Issue credit note</Button>
            )}
            {invoice.status === "posted" && num(invoice.amount_paid) === 0 && num(invoice.amount_credited) === 0 && (
              <Button variant="danger" onClick={() => setPanel("void")}>Void</Button>
            )}
          </div>

          <ErrorBanner message={error} />

          {panel === "pay" && (
            <form
              className="grid grid-cols-1 gap-3 rounded-lg bg-slate-50 p-4 dark:bg-navy-900 sm:grid-cols-5"
              onSubmit={(e) => {
                e.preventDefault();
                run(() => pay.mutateAsync({ invoice_id: invoice.id, amount, method, payment_date: payDate, reference }));
              }}
            >
              <Field label="Amount">
                <Input type="number" step="0.01" min="0.01" max={balance} required value={amount} onChange={(e) => setAmount(e.target.value)} />
              </Field>
              <Field label="Method">
                <Select value={method} onChange={(e) => setMethod(e.target.value)}>
                  <option value="mpesa">M-Pesa</option>
                  <option value="bank">Bank transfer</option>
                  <option value="cash">Cash</option>
                  <option value="cheque">Cheque</option>
                  <option value="card">Card</option>
                </Select>
              </Field>
              <Field label="Date">
                <Input type="date" value={payDate} onChange={(e) => setPayDate(e.target.value)} />
              </Field>
              <Field label="Reference">
                <Input placeholder="e.g. M-Pesa code" value={reference} onChange={(e) => setReference(e.target.value)} />
              </Field>
              <div className="flex items-end">
                <Button type="submit" disabled={pay.isPending} className="w-full">Save payment</Button>
              </div>
            </form>
          )}

          {panel === "credit" && (
            <form
              className="space-y-3 rounded-lg bg-slate-50 p-4 dark:bg-navy-900"
              onSubmit={(e) => {
                e.preventDefault();
                const lines = wholeInvoice
                  ? null
                  : invoice.lines
                      .filter((l) => num(creditQty[l.id]) > 0)
                      .map((l) => ({ invoice_line_id: l.id, qty: creditQty[l.id] }));
                if (lines && !lines.length) {
                  setError("Enter a quantity to credit on at least one line.");
                  return;
                }
                run(() =>
                  credit.mutateAsync({
                    invoice_id: invoice.id,
                    reason,
                    lines,
                    restock_warehouse_id: restockWarehouse || null,
                    issue_date: today(),
                  })
                );
              }}
            >
              {invoice.lines.length > 0 && (
                <Checkbox label="Credit the whole invoice" checked={wholeInvoice} onChange={setWholeInvoice} />
              )}
              {!wholeInvoice && (
                <div className="space-y-2">
                  {invoice.lines.map((l) => (
                    <div key={l.id} className="flex items-center gap-3 text-sm">
                      <span className="flex-1 text-navy-900 dark:text-slate-200">{l.description} (invoiced {fmtQty(l.qty)})</span>
                      <div className="w-24">
                        <Input type="number" min="0" max={l.qty} step="any" placeholder="Qty" value={creditQty[l.id] ?? ""} onChange={(e) => setCreditQty({ ...creditQty, [l.id]: e.target.value })} />
                      </div>
                    </div>
                  ))}
                </div>
              )}
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                <Field label="Reason">
                  <Input required placeholder="e.g. Damaged goods returned" value={reason} onChange={(e) => setReason(e.target.value)} />
                </Field>
                {hasProducts && (
                  <Field label="Return goods to stock at" hint="Leave empty if nothing comes back">
                    <Select value={restockWarehouse} onChange={(e) => setRestockWarehouse(e.target.value)}>
                      <option value="">Don't restock</option>
                      {warehouses?.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
                    </Select>
                  </Field>
                )}
                <div className="flex items-end">
                  <Button type="submit" disabled={credit.isPending} className="w-full">Issue credit note</Button>
                </div>
              </div>
            </form>
          )}

          {panel === "void" && (
            <form
              className="flex flex-wrap items-end gap-3 rounded-lg bg-red-50 p-4 dark:bg-red-950/30"
              onSubmit={(e) => {
                e.preventDefault();
                run(() => voidInvoice.mutateAsync({ reason }));
              }}
            >
              <div className="min-w-[16rem] flex-1">
                <Field label="Reason for voiding">
                  <Input required value={reason} onChange={(e) => setReason(e.target.value)} />
                </Field>
              </div>
              <Button type="submit" variant="danger" disabled={voidInvoice.isPending}>Void invoice</Button>
            </form>
          )}

          <Table>
            <thead>
              <tr>
                <Th>Description</Th>
                <Th>Qty</Th>
                <Th>Unit price</Th>
                <Th>Disc</Th>
                <Th>VAT</Th>
                <Th>Amount</Th>
              </tr>
            </thead>
            <tbody>
              {invoice.lines.length === 0 && (
                <tr>
                  <Td colSpan={6} className="text-slate-500">Not itemised — total {fmtMoney(invoice.subtotal)}</Td>
                </tr>
              )}
              {invoice.lines.map((l) => (
                <tr key={l.id}>
                  <Td>{l.description}</Td>
                  <Td>{fmtQty(l.qty)}</Td>
                  <Td>{fmtMoney(l.unit_price)}</Td>
                  <Td>{num(l.discount_pct) ? `${num(l.discount_pct)}%` : "—"}</Td>
                  <Td>{num(l.tax_rate) ? `${num(l.tax_rate) * 100}%` : "—"}</Td>
                  <Td className="tabular-nums">{fmtMoney(l.line_subtotal)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>

          <div className="ml-auto w-full max-w-xs space-y-1 text-sm text-slate-600 dark:text-slate-300">
            <Line label="Subtotal" value={fmtMoney(num(invoice.subtotal) + num(invoice.discount_total))} />
            {num(invoice.discount_total) > 0 && <Line label="Discount" value={`-${fmtMoney(invoice.discount_total)}`} />}
            <Line label="VAT" value={fmtMoney(invoice.tax_total)} />
            <Line label="Total" value={fmtMoney(invoice.total, currency)} bold />
            {num(invoice.amount_paid) > 0 && <Line label="Paid" value={`-${fmtMoney(invoice.amount_paid)}`} />}
            {num(invoice.amount_credited) > 0 && <Line label="Credited" value={`-${fmtMoney(invoice.amount_credited)}`} />}
            <Line label="Balance due" value={fmtMoney(balance, currency)} bold />
          </div>

          {!!payments?.length && (
            <div>
              <h3 className="mb-2 text-sm font-semibold text-slate-500">Payments</h3>
              <Table>
                <tbody>
                  {payments.map((p) => (
                    <tr key={p.id}>
                      <Td>{p.document_no}</Td>
                      <Td>{fmtDate(p.entry_date)}</Td>
                      <Td>{humanize(p.method || "—")}</Td>
                      <Td>{p.reference || "—"}</Td>
                      <Td className="tabular-nums">{fmtMoney(p.amount)}</Td>
                      <Td>
                        <Button variant="secondary" className="px-2 py-1 text-xs" onClick={() => openFile(`/sales/payments/${p.id}/receipt`)}>
                          Receipt
                        </Button>
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </div>
          )}

          {!!credits?.length && (
            <div>
              <h3 className="mb-2 text-sm font-semibold text-slate-500">Credit notes</h3>
              <Table>
                <tbody>
                  {credits.map((c) => (
                    <tr key={c.id}>
                      <Td>{c.credit_note_no}</Td>
                      <Td>{fmtDate(c.issue_date)}</Td>
                      <Td>{c.reason || "—"}</Td>
                      <Td className="tabular-nums">{fmtMoney(c.total)}</Td>
                      <Td>
                        <Button variant="secondary" className="px-2 py-1 text-xs" onClick={() => openFile(`/sales/credit-notes/${c.id}/pdf`)}>
                          PDF
                        </Button>
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </div>
          )}

          <EmailDialog open={emailing} onClose={() => setEmailing(false)} title={`Email ${invoice.invoice_no}`} endpoint={`/sales/invoices/${invoice.id}/email`} />

          {(invoice.notes || invoice.terms) && (
            <div className="grid gap-4 text-sm text-slate-600 dark:text-slate-300 sm:grid-cols-2">
              {invoice.notes && <div><p className="font-medium">Notes</p><p className="whitespace-pre-line">{invoice.notes}</p></div>}
              {invoice.terms && <div><p className="font-medium">Terms</p><p className="whitespace-pre-line">{invoice.terms}</p></div>}
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}

function Line({ label, value, bold }: { label: string; value: string; bold?: boolean }) {
  return (
    <div className={`flex justify-between ${bold ? "border-t border-slate-200 pt-1 font-semibold text-navy-900 dark:border-navy-700 dark:text-white" : ""}`}>
      <span>{label}</span>
      <span className="tabular-nums">{value}</span>
    </div>
  );
}
