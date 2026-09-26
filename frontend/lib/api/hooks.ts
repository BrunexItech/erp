import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { http } from "@/lib/api/http";
import type {
  Account,
  Branding,
  Deal,
  Invoice,
  Me,
  Party,
  PosReceipt,
  Product,
  PurchaseOrder,
  PurchaseOrderLine,
  SalesOrder,
  SalesOrderLine,
  StockTransfer,
  TrialBalanceRow,
  VendorBill,
  Warehouse,
  WarehouseStock,
  Workspace,
} from "@/lib/api/types";

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: () => http.get<Me>("/auth/me") });
}

export function useBranding() {
  return useQuery({ queryKey: ["platform", "branding"], queryFn: () => http.get<Branding>("/workspaces/branding") });
}

export function useUpdateBranding() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Partial<Branding>) => http.patch<Branding>("/workspaces/branding", payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["platform", "branding"] }),
  });
}

export function useWorkspaces() {
  return useQuery({
    queryKey: ["workspaces"],
    queryFn: () => http.get<Workspace[]>("/workspaces", { workspaceScoped: false }),
  });
}

export function useParties() {
  return useQuery({ queryKey: ["crm", "parties"], queryFn: () => http.get<Party[]>("/crm/parties") });
}

export function useCreateParty() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Partial<Party>) => http.post<Party>("/crm/parties", payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["crm", "parties"] }),
  });
}

export function useDeals() {
  return useQuery({ queryKey: ["crm", "deals"], queryFn: () => http.get<Deal[]>("/crm/deals") });
}

export function useCreateDeal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Record<string, unknown>) => http.post<Deal>("/crm/deals", payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["crm", "deals"] }),
  });
}

export function useProducts() {
  return useQuery({ queryKey: ["inventory", "products"], queryFn: () => http.get<Product[]>("/inventory/products") });
}

export function useCreateProduct() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Record<string, unknown>) => http.post<Product>("/inventory/products", payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["inventory", "products"] }),
  });
}

export function useWarehouses() {
  return useQuery({ queryKey: ["inventory", "warehouses"], queryFn: () => http.get<Warehouse[]>("/inventory/warehouses") });
}

export function useCreateWarehouse() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Record<string, unknown>) => http.post<Warehouse>("/inventory/warehouses", payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["inventory", "warehouses"] }),
  });
}

export function useWarehouseStock(warehouseId?: string) {
  return useQuery({
    queryKey: ["inventory", "warehouse-stock", warehouseId ?? "all"],
    queryFn: () =>
      http.get<WarehouseStock[]>(
        warehouseId ? `/inventory/warehouse-stock?warehouse_id=${warehouseId}` : "/inventory/warehouse-stock"
      ),
  });
}

export function useCreateTransfer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Record<string, unknown>) => http.post<StockTransfer>("/inventory/transfers", payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["inventory"] });
    },
  });
}

export function usePosCheckout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Record<string, unknown>) => http.post<PosReceipt>("/sales/pos/checkout", payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sales", "pos"] });
      qc.invalidateQueries({ queryKey: ["inventory"] });
      qc.invalidateQueries({ queryKey: ["sales"] });
      qc.invalidateQueries({ queryKey: ["accounting"] });
      qc.invalidateQueries({ queryKey: ["crm", "parties"] });
    },
  });
}

export function useSalesOrders() {
  return useQuery({ queryKey: ["sales", "orders"], queryFn: () => http.get<SalesOrder[]>("/sales/orders") });
}

export function useCreateSalesOrder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Record<string, unknown>) => http.post<SalesOrder>("/sales/orders", payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sales", "orders"] }),
  });
}

export function useSalesOrderLines(orderId: string | null) {
  return useQuery({
    queryKey: ["sales", "order-lines", orderId],
    queryFn: () => http.get<SalesOrderLine[]>(`/sales/orders/${orderId}/lines`),
    enabled: !!orderId,
  });
}

function invalidateSalesAndAccounting(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: ["sales"] });
  qc.invalidateQueries({ queryKey: ["inventory", "products"] });
  qc.invalidateQueries({ queryKey: ["accounting"] });
}

export function useConfirmSalesOrder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (orderId: string) => http.post<SalesOrder>(`/sales/orders/${orderId}/confirm`),
    onSuccess: () => invalidateSalesAndAccounting(qc),
  });
}

export function useCreateDelivery() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Record<string, unknown>) => http.post("/sales/deliveries", payload),
    onSuccess: () => invalidateSalesAndAccounting(qc),
  });
}

export function useInvoices() {
  return useQuery({ queryKey: ["sales", "invoices"], queryFn: () => http.get<Invoice[]>("/sales/invoices") });
}

export function useCreateInvoice() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Record<string, unknown>) => http.post<Invoice>("/sales/invoices", payload),
    onSuccess: () => invalidateSalesAndAccounting(qc),
  });
}

export function useRecordCustomerPayment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Record<string, unknown>) => http.post("/sales/invoices/payments", payload),
    onSuccess: () => invalidateSalesAndAccounting(qc),
  });
}

export function usePurchaseOrders() {
  return useQuery({ queryKey: ["purchasing", "orders"], queryFn: () => http.get<PurchaseOrder[]>("/purchasing/purchase-orders") });
}

export function useCreatePurchaseOrder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Record<string, unknown>) => http.post<PurchaseOrder>("/purchasing/purchase-orders", payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["purchasing", "orders"] }),
  });
}

export function usePurchaseOrderLines(poId: string | null) {
  return useQuery({
    queryKey: ["purchasing", "order-lines", poId],
    queryFn: () => http.get<PurchaseOrderLine[]>(`/purchasing/purchase-orders/${poId}/lines`),
    enabled: !!poId,
  });
}

function invalidatePurchasingAndAccounting(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: ["purchasing"] });
  qc.invalidateQueries({ queryKey: ["inventory", "products"] });
  qc.invalidateQueries({ queryKey: ["accounting"] });
}

export function useConfirmPurchaseOrder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (poId: string) => http.post<PurchaseOrder>(`/purchasing/purchase-orders/${poId}/confirm`),
    onSuccess: () => invalidatePurchasingAndAccounting(qc),
  });
}

export function useReceiveGoods() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Record<string, unknown>) => http.post("/purchasing/goods-receipts", payload),
    onSuccess: () => invalidatePurchasingAndAccounting(qc),
  });
}

export function useVendorBills() {
  return useQuery({ queryKey: ["purchasing", "bills"], queryFn: () => http.get<VendorBill[]>("/purchasing/vendor-bills") });
}

export function useCreateVendorBill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Record<string, unknown>) => http.post<VendorBill>("/purchasing/vendor-bills", payload),
    onSuccess: () => invalidatePurchasingAndAccounting(qc),
  });
}

export function useRecordVendorPayment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Record<string, unknown>) => http.post("/purchasing/vendor-bills/payments", payload),
    onSuccess: () => invalidatePurchasingAndAccounting(qc),
  });
}

export function useAccounts() {
  return useQuery({ queryKey: ["accounting", "accounts"], queryFn: () => http.get<Account[]>("/accounting/accounts") });
}

export function useTrialBalance() {
  return useQuery({
    queryKey: ["accounting", "trial-balance"],
    queryFn: () => http.get<TrialBalanceRow[]>("/accounting/trial-balance"),
  });
}
