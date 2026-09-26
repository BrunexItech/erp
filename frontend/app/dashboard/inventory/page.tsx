"use client";

import { useState } from "react";
import {
  useCreateProduct,
  useCreateTransfer,
  useCreateWarehouse,
  useProducts,
  useWarehouseStock,
  useWarehouses,
} from "@/lib/api/hooks";
import { Button, Card, EmptyState, Input, Label, Select, Table, Td, Th, Badge } from "@/components/om/primitives";
import type { Product } from "@/lib/api/types";
import { ApiError } from "@/lib/api/http";

export default function InventoryPage() {
  const { data: products, isLoading } = useProducts();
  const { data: warehouses } = useWarehouses();
  const { data: warehouseStock } = useWarehouseStock();
  const createProduct = useCreateProduct();
  const createWarehouse = useCreateWarehouse();
  const createTransfer = useCreateTransfer();

  const [showProductForm, setShowProductForm] = useState(false);
  const [sku, setSku] = useState("");
  const [name, setName] = useState("");
  const [valuationMethod, setValuationMethod] = useState<Product["valuation_method"]>("weighted_average");
  const [salePrice, setSalePrice] = useState("0");

  const [showWarehouseForm, setShowWarehouseForm] = useState(false);
  const [whName, setWhName] = useState("");
  const [whCode, setWhCode] = useState("");

  const [showTransferForm, setShowTransferForm] = useState(false);
  const [fromWarehouseId, setFromWarehouseId] = useState("");
  const [toWarehouseId, setToWarehouseId] = useState("");
  const [transferProductId, setTransferProductId] = useState("");
  const [transferQty, setTransferQty] = useState("1");
  const [transferError, setTransferError] = useState<string | null>(null);

  const warehouseById = new Map((warehouses ?? []).map((w) => [w.id, w]));
  const productById = new Map((products ?? []).map((p) => [p.id, p]));
  const availableAtSource = warehouseStock?.find(
    (s) => s.warehouse_id === fromWarehouseId && s.product_id === transferProductId
  );

  async function onSubmitProduct(e: React.FormEvent) {
    e.preventDefault();
    await createProduct.mutateAsync({ sku, name, valuation_method: valuationMethod, sale_price: salePrice });
    setSku("");
    setName("");
    setSalePrice("0");
    setShowProductForm(false);
  }

  async function onSubmitWarehouse(e: React.FormEvent) {
    e.preventDefault();
    await createWarehouse.mutateAsync({ name: whName, code: whCode });
    setWhName("");
    setWhCode("");
    setShowWarehouseForm(false);
  }

  async function onSubmitTransfer(e: React.FormEvent) {
    e.preventDefault();
    setTransferError(null);
    try {
      await createTransfer.mutateAsync({
        from_warehouse_id: fromWarehouseId,
        to_warehouse_id: toWarehouseId,
        lines: [{ product_id: transferProductId, qty: transferQty }],
      });
      setShowTransferForm(false);
      setTransferQty("1");
    } catch (err) {
      setTransferError(err instanceof ApiError ? String(err.detail) : "Transfer failed");
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-navy-900 dark:text-white">Inventory</h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">Products, stock levels and warehouses.</p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => setShowWarehouseForm((v) => !v)}>
            {showWarehouseForm ? "Cancel" : "Add shop/warehouse"}
          </Button>
          <Button
            variant="secondary"
            onClick={() => setShowTransferForm((v) => !v)}
            disabled={(warehouses?.length ?? 0) < 2}
          >
            {showTransferForm ? "Cancel" : "Transfer stock"}
          </Button>
          <Button onClick={() => setShowProductForm((v) => !v)}>{showProductForm ? "Cancel" : "Add product"}</Button>
        </div>
      </div>

      {showWarehouseForm && (
        <Card className="p-6">
          <form onSubmit={onSubmitWarehouse} className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div>
              <Label>Name</Label>
              <Input required value={whName} onChange={(e) => setWhName(e.target.value)} />
            </div>
            <div>
              <Label>Code</Label>
              <Input required value={whCode} onChange={(e) => setWhCode(e.target.value)} />
            </div>
            <div className="flex items-end">
              <Button type="submit" disabled={createWarehouse.isPending}>
                {createWarehouse.isPending ? "Saving…" : "Save warehouse"}
              </Button>
            </div>
          </form>
        </Card>
      )}

      {showTransferForm && (
        <Card className="p-6">
          <form onSubmit={onSubmitTransfer} className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <Label>From shop</Label>
              <Select required value={fromWarehouseId} onChange={(e) => setFromWarehouseId(e.target.value)}>
                <option value="">Select…</option>
                {warehouses?.map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name}
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <Label>To shop</Label>
              <Select required value={toWarehouseId} onChange={(e) => setToWarehouseId(e.target.value)}>
                <option value="">Select…</option>
                {warehouses?.filter((w) => w.id !== fromWarehouseId).map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name}
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <Label>Product</Label>
              <Select required value={transferProductId} onChange={(e) => setTransferProductId(e.target.value)}>
                <option value="">Select…</option>
                {products?.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.sku} — {p.name}
                  </option>
                ))}
              </Select>
              {fromWarehouseId && transferProductId && (
                <p className="mt-1 text-xs text-slate-400">
                  Available at source: {availableAtSource?.qty ?? "0"}
                </p>
              )}
            </div>
            <div>
              <Label>Quantity</Label>
              <Input type="number" min="0.01" step="0.01" value={transferQty} onChange={(e) => setTransferQty(e.target.value)} />
            </div>
            {transferError && <p className="text-sm text-red-600 sm:col-span-2">{transferError}</p>}
            <div className="sm:col-span-2">
              <Button type="submit" disabled={createTransfer.isPending}>
                {createTransfer.isPending ? "Transferring…" : "Transfer"}
              </Button>
            </div>
          </form>
        </Card>
      )}

      {showProductForm && (
        <Card className="p-6">
          <form onSubmit={onSubmitProduct} className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <Label>SKU</Label>
              <Input required value={sku} onChange={(e) => setSku(e.target.value)} />
            </div>
            <div>
              <Label>Name</Label>
              <Input required value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div>
              <Label>Valuation method</Label>
              <Select value={valuationMethod} onChange={(e) => setValuationMethod(e.target.value as Product["valuation_method"])}>
                <option value="weighted_average">Weighted average</option>
                <option value="fifo">FIFO</option>
              </Select>
            </div>
            <div>
              <Label>Sale price</Label>
              <Input type="number" step="0.01" value={salePrice} onChange={(e) => setSalePrice(e.target.value)} />
            </div>
            <div className="sm:col-span-2">
              <Button type="submit" disabled={createProduct.isPending}>
                {createProduct.isPending ? "Saving…" : "Save product"}
              </Button>
            </div>
          </form>
        </Card>
      )}

      {warehouses && warehouses.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {warehouses.map((w) => (
            <Badge key={w.id}>{w.name} ({w.code})</Badge>
          ))}
        </div>
      )}

      {warehouseStock && warehouseStock.length > 0 && (warehouses?.length ?? 0) > 1 && (
        <div>
          <h2 className="mb-2 text-sm font-semibold text-slate-500 dark:text-slate-400">Stock by shop</h2>
          <Card>
            <Table>
              <thead>
                <tr>
                  <Th>Product</Th>
                  <Th>Shop</Th>
                  <Th>Qty</Th>
                </tr>
              </thead>
              <tbody>
                {warehouseStock
                  .filter((s) => parseFloat(s.qty) !== 0)
                  .map((s) => (
                    <tr key={`${s.product_id}-${s.warehouse_id}`}>
                      <Td>{productById.get(s.product_id)?.sku ?? s.product_id.slice(0, 8)}</Td>
                      <Td>{warehouseById.get(s.warehouse_id)?.name ?? s.warehouse_id.slice(0, 8)}</Td>
                      <Td>{s.qty}</Td>
                    </tr>
                  ))}
              </tbody>
            </Table>
          </Card>
        </div>
      )}

      <Card>
        {isLoading ? (
          <p className="p-6 text-sm text-slate-400">Loading…</p>
        ) : !products?.length ? (
          <div className="p-6">
            <EmptyState title="No products yet" description="Add a product to start tracking stock and valuation." />
          </div>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>SKU</Th>
                <Th>Name</Th>
                <Th>Valuation</Th>
                <Th>Stock</Th>
                <Th>Avg/FIFO cost</Th>
                <Th>Sale price</Th>
              </tr>
            </thead>
            <tbody>
              {products.map((p) => {
                const low = parseFloat(p.stock_qty) <= parseFloat(p.low_stock_threshold);
                return (
                  <tr key={p.id}>
                    <Td>{p.sku}</Td>
                    <Td>{p.name}</Td>
                    <Td>
                      <Badge>{p.valuation_method === "fifo" ? "FIFO" : "Weighted avg"}</Badge>
                    </Td>
                    <Td>
                      {low ? <Badge tone="danger">{p.stock_qty} low</Badge> : p.stock_qty}
                    </Td>
                    <Td>{p.avg_cost}</Td>
                    <Td>{p.sale_price}</Td>
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
