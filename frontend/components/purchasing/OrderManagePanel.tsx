"use client";

import { useState } from "react";
import {
  useConfirmPurchaseOrder,
  useCreateVendorBill,
  usePurchaseOrderLines,
  useReceiveGoods,
  useRecordVendorPayment,
  useVendorBills,
  useWarehouses,
} from "@/lib/api/hooks";
import { Button, Card, Input, Label, Select, Table, Td, Th, Badge } from "@/components/om/primitives";
import type { PurchaseOrder } from "@/lib/api/types";
import { ApiError } from "@/lib/api/http";

export function OrderManagePanel({ order }: { order: PurchaseOrder }) {
  const { data: lines } = usePurchaseOrderLines(order.id);
  const { data: warehouses } = useWarehouses();
  const { data: bills } = useVendorBills();
  const confirmOrder = useConfirmPurchaseOrder();
  const receiveGoods = useReceiveGoods();
  const createBill = useCreateVendorBill();
  const recordPayment = useRecordVendorPayment();

  const [error, setError] = useState<string | null>(null);
  const [warehouseId, setWarehouseId] = useState("");
  const [receiveQty, setReceiveQty] = useState<Record<string, string>>({});
  const [receiveCost, setReceiveCost] = useState<Record<string, string>>({});
  const [paymentAmount, setPaymentAmount] = useState("");

  const relatedBill = bills?.find((b) => b.po_id === order.id);
  const outstanding = lines?.filter((l) => parseFloat(l.qty_ordered) > parseFloat(l.qty_received)) ?? [];

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

  async function onReceive(e: React.FormEvent) {
    e.preventDefault();
    const receiveLines = outstanding
      .map((l) => ({
        po_line_id: l.id,
        product_id: l.product_id,
        qty_received: receiveQty[l.id],
        actual_unit_cost: receiveCost[l.id] ?? l.unit_cost,
      }))
      .filter((l) => l.qty_received && parseFloat(l.qty_received) > 0);
    if (!warehouseId || receiveLines.length === 0) {
      setError("Select a warehouse and at least one quantity to receive.");
      return;
    }
    await handle(() =>
      receiveGoods.mutateAsync({ po_id: order.id, warehouse_id: warehouseId, lines: receiveLines })
    );
    setReceiveQty({});
    setReceiveCost({});
  }

  async function onBill() {
    await handle(() =>
      createBill.mutateAsync({
        party_id: order.party_id,
        po_id: order.id,
        subtotal: order.subtotal,
        tax_total: order.tax_total,
      })
    );
  }

  async function onPay(e: React.FormEvent) {
    e.preventDefault();
    if (!relatedBill) return;
    await handle(() =>
      recordPayment.mutateAsync({ vendor_bill_id: relatedBill.id, amount: paymentAmount, method: "bank" })
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
              <Th>Received</Th>
              {outstanding.length > 0 && (
                <>
                  <Th>Receive now</Th>
                  <Th>Actual cost</Th>
                </>
              )}
            </tr>
          </thead>
          <tbody>
            {lines.map((line) => (
              <tr key={line.id}>
                <Td className="font-mono text-xs">{line.product_id.slice(0, 8)}…</Td>
                <Td>{line.qty_ordered}</Td>
                <Td>{line.qty_received}</Td>
                {outstanding.some((u) => u.id === line.id) && (
                  <>
                    <Td>
                      <Input
                        type="number"
                        min="0"
                        step="0.01"
                        className="w-24"
                        value={receiveQty[line.id] ?? ""}
                        onChange={(e) => setReceiveQty((prev) => ({ ...prev, [line.id]: e.target.value }))}
                      />
                    </Td>
                    <Td>
                      <Input
                        type="number"
                        min="0"
                        step="0.01"
                        className="w-24"
                        placeholder={line.unit_cost}
                        value={receiveCost[line.id] ?? ""}
                        onChange={(e) => setReceiveCost((prev) => ({ ...prev, [line.id]: e.target.value }))}
                      />
                    </Td>
                  </>
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

        {outstanding.length > 0 && order.status !== "draft" && (
          <form onSubmit={onReceive} className="flex flex-wrap items-end gap-3">
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
            <Button type="submit" disabled={receiveGoods.isPending}>
              Receive goods
            </Button>
          </form>
        )}

        {outstanding.length === 0 && lines && lines.length > 0 && !relatedBill && (
          <Button onClick={onBill} disabled={createBill.isPending}>
            Create vendor bill ({order.total})
          </Button>
        )}

        {relatedBill && relatedBill.status !== "paid" && (
          <form onSubmit={onPay} className="flex flex-wrap items-end gap-3">
            <Badge tone={relatedBill.status === "partially_paid" ? "warning" : "neutral"}>
              Bill {relatedBill.status}
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

        {relatedBill?.status === "paid" && <Badge tone="success">Paid in full</Badge>}
      </div>
    </Card>
  );
}
