"use client";

import { useState } from "react";
import {
  useConfirmSalesOrder,
  useCreateDelivery,
  useCreateInvoice,
  useInvoices,
  useRecordCustomerPayment,
  useSalesOrderLines,
  useWarehouses,
} from "@/lib/api/hooks";
import { Button, Card, Input, Label, Select, Table, Td, Th, Badge } from "@/components/om/primitives";
import type { SalesOrder } from "@/lib/api/types";
import { ApiError } from "@/lib/api/http";

export function OrderManagePanel({ order }: { order: SalesOrder }) {
  const { data: lines } = useSalesOrderLines(order.id);
  const { data: warehouses } = useWarehouses();
  const { data: invoices } = useInvoices();
  const confirmOrder = useConfirmSalesOrder();
  const createDelivery = useCreateDelivery();
  const createInvoice = useCreateInvoice();
  const recordPayment = useRecordCustomerPayment();

  const [error, setError] = useState<string | null>(null);
  const [warehouseId, setWarehouseId] = useState("");
  const [deliverQty, setDeliverQty] = useState<Record<string, string>>({});
  const [paymentAmount, setPaymentAmount] = useState("");

  const relatedInvoice = invoices?.find((inv) => inv.order_id === order.id);
  const undelivered = lines?.filter((l) => parseFloat(l.qty) > parseFloat(l.qty_delivered)) ?? [];

  async function handle(fn: () => Promise<unknown>) {
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : "Action failed");
    }
  }

  async function onConfirm() {
    await handle(() => confirmOrder.mutateAsync(order.id));
  }

  async function onDeliver(e: React.FormEvent) {
    e.preventDefault();
    const deliverLines = undelivered
      .map((l) => ({ order_line_id: l.id, product_id: l.product_id, qty_delivered: deliverQty[l.id] }))
      .filter((l) => l.qty_delivered && parseFloat(l.qty_delivered) > 0);
    if (!warehouseId || deliverLines.length === 0) {
      setError("Select a warehouse and at least one quantity to deliver.");
      return;
    }
    await handle(() =>
      createDelivery.mutateAsync({ order_id: order.id, warehouse_id: warehouseId, lines: deliverLines })
    );
    setDeliverQty({});
  }

  async function onInvoice() {
    await handle(() =>
      createInvoice.mutateAsync({
        party_id: order.party_id,
        order_id: order.id,
        subtotal: order.subtotal,
        tax_total: order.tax_total,
      })
    );
  }

  async function onPay(e: React.FormEvent) {
    e.preventDefault();
    if (!relatedInvoice) return;
    await handle(() =>
      recordPayment.mutateAsync({ invoice_id: relatedInvoice.id, amount: paymentAmount, method: "bank" })
    );
    setPaymentAmount("");
  }

  return (
    <Card className="mt-2 p-4">
      {error && <p className="mb-3 text-sm text-red-600">{error}</p>}

      {lines && lines.length > 0 && (
        <Table>
          <thead>
            <tr>
              <Th>Product</Th>
              <Th>Ordered</Th>
              <Th>Delivered</Th>
              {undelivered.length > 0 && <Th>Deliver now</Th>}
            </tr>
          </thead>
          <tbody>
            {lines.map((line) => (
              <tr key={line.id}>
                <Td className="font-mono text-xs">{line.product_id.slice(0, 8)}…</Td>
                <Td>{line.qty}</Td>
                <Td>{line.qty_delivered}</Td>
                {undelivered.some((u) => u.id === line.id) && (
                  <Td>
                    <Input
                      type="number"
                      min="0"
                      step="0.01"
                      className="w-24"
                      value={deliverQty[line.id] ?? ""}
                      onChange={(e) => setDeliverQty((prev) => ({ ...prev, [line.id]: e.target.value }))}
                    />
                  </Td>
                )}
              </tr>
            ))}
          </tbody>
        </Table>
      )}

      <div className="mt-4 flex flex-wrap items-end gap-3">
        {order.status === "draft" && (
          <Button onClick={onConfirm} disabled={confirmOrder.isPending}>
            Confirm order
          </Button>
        )}

        {undelivered.length > 0 && order.status !== "draft" && (
          <form onSubmit={onDeliver} className="flex flex-wrap items-end gap-3">
            <div>
              <Label>Warehouse</Label>
              <Select value={warehouseId} onChange={(e) => setWarehouseId(e.target.value)}>
                <option value="">Select…</option>
                {warehouses?.map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name}
                  </option>
                ))}
              </Select>
            </div>
            <Button type="submit" disabled={createDelivery.isPending}>
              Deliver
            </Button>
          </form>
        )}

        {undelivered.length === 0 && lines && lines.length > 0 && !relatedInvoice && (
          <Button onClick={onInvoice} disabled={createInvoice.isPending}>
            Create invoice ({order.total})
          </Button>
        )}

        {relatedInvoice && relatedInvoice.status !== "paid" && (
          <form onSubmit={onPay} className="flex flex-wrap items-end gap-3">
            <Badge tone={relatedInvoice.status === "partially_paid" ? "warning" : "neutral"}>
              Invoice {relatedInvoice.status}
            </Badge>
            <div>
              <Label>Payment amount</Label>
              <Input
                type="number"
                step="0.01"
                className="w-32"
                value={paymentAmount}
                onChange={(e) => setPaymentAmount(e.target.value)}
              />
            </div>
            <Button type="submit" disabled={recordPayment.isPending}>
              Record payment
            </Button>
          </form>
        )}

        {relatedInvoice?.status === "paid" && <Badge tone="success">Paid in full</Badge>}
      </div>
    </Card>
  );
}
