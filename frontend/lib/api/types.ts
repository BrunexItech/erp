export interface Workspace {
  id: string;
  name: string;
  currency: string;
  role: "owner" | "admin" | "manager" | "staff" | "viewer";
}

export interface Branding {
  name: string;
  logo_url: string | null;
  address: string;
  phone: string;
  billing_email: string;
  invoice_footer_note: string;
  currency: string;
  tax_pin: string;
  website: string;
  brand_color: string;
  invoice_template: "modern" | "bold" | "classic";
  etims_mode: "off" | "test" | "live";
  bank_details: string;
  mpesa_paybill: string;
  mpesa_till: string;
  default_payment_terms_days: number;
  invoice_terms: string;
}

export interface Me {
  user_id: string;
  workspace_id: string;
  role: string;
  permissions: string[];
  features: string[];
  billing?: { level: "ok" | "grace" | "locked"; message: string };
}

export interface Party {
  id: string;
  name: string;
  kind: "lead" | "customer" | "vendor" | "both";
  is_company: boolean;
  tax_id: string | null;
  email: string | null;
  phone: string | null;
  billing_address: string;
  shipping_address: string;
  created_at: string;
}

export interface Deal {
  id: string;
  party_id: string;
  title: string;
  stage: "new" | "qualified" | "proposal" | "won" | "lost";
  amount: string;
  expected_close_date: string | null;
}

export interface Product {
  id: string;
  sku: string;
  name: string;
  barcode: string | null;
  category: string;
  description: string;
  unit: string;
  valuation_method: "fifo" | "weighted_average";
  sale_price: string;
  tax_rate: string;
  stock_qty: string;
  avg_cost: string;
  low_stock_threshold: string;
  is_active: boolean;
}

export interface Warehouse {
  id: string;
  name: string;
  code: string;
}

export interface WarehouseStock {
  product_id: string;
  warehouse_id: string;
  qty: string;
}

export interface StockTransfer {
  id: string;
  from_warehouse_id: string;
  to_warehouse_id: string;
  status: string;
  note: string;
}

export interface SalesOrder {
  id: string;
  so_no: string;
  party_id: string;
  status: string;
  subtotal: string;
  tax_total: string;
  total: string;
}

export interface SalesOrderLine {
  id: string;
  product_id: string;
  qty: string;
  unit_price: string;
  tax_rate: string;
  qty_delivered: string;
}

export interface PosReceipt {
  order_id: string;
  invoice_id: string;
  invoice_no: string;
  receipt_no: string;
  party_id: string;
  subtotal: string;
  tax_total: string;
  total: string;
  total_cogs: string;
  payment_method: string;
  payment_reference: string;
  amount_tendered: string;
  change_due: string;
  issued_at: string;
}

export interface Invoice {
  id: string;
  invoice_no: string;
  order_id: string | null;
  party_id: string;
  status: string;
  issue_date: string | null;
  due_date: string | null;
  reference: string;
  notes: string;
  terms: string;
  subtotal: string;
  discount_total: string;
  tax_total: string;
  total: string;
  amount_paid: string;
  amount_credited: string;
  channel?: string;
  etims_status?: string;
  etims_reference?: string;
  etims_error?: string;
}

export interface DocumentLine {
  id: string;
  position: number;
  product_id: string | null;
  description: string;
  qty: string;
  unit_price: string;
  discount_pct: string;
  tax_rate: string;
  line_subtotal: string;
  tax_amount: string;
  line_total: string;
}

export interface InvoiceDetail extends Invoice {
  lines: DocumentLine[];
  balance_due: string;
  party_name: string;
}

export interface Payment {
  id: string;
  document_no: string;
  invoice_id: string | null;
  party_id: string;
  amount: string;
  method: string;
  reference: string;
  entry_date: string | null;
}

export interface Quote {
  id: string;
  quote_no: string;
  party_id: string;
  status: "draft" | "sent" | "accepted" | "declined" | "converted";
  issue_date: string;
  valid_until: string | null;
  reference: string;
  notes: string;
  terms: string;
  subtotal: string;
  discount_total: string;
  tax_total: string;
  total: string;
  converted_invoice_id: string | null;
}

export interface CreditNote {
  id: string;
  credit_note_no: string;
  invoice_id: string;
  party_id: string;
  issue_date: string;
  reason: string;
  subtotal: string;
  tax_total: string;
  total: string;
}

export interface AgingRow {
  party_id: string;
  party_name: string;
  current: string;
  days_1_30: string;
  days_31_60: string;
  days_61_90: string;
  over_90: string;
  total: string;
}

export interface AgingReport {
  as_of: string;
  rows: AgingRow[];
  totals: Omit<AgingRow, "party_id" | "party_name">;
}

export interface PurchaseOrder {
  id: string;
  po_no: string;
  expected_date: string | null;
  party_id: string;
  status: string;
  subtotal: string;
  tax_total: string;
  total: string;
}

export interface PurchaseOrderLine {
  id: string;
  product_id: string;
  qty_ordered: string;
  unit_cost: string;
  qty_received: string;
}

export interface VendorBill {
  id: string;
  bill_no: string;
  vendor_reference: string;
  bill_date: string | null;
  due_date: string | null;
  memo: string;
  po_id: string | null;
  party_id: string;
  status: string;
  subtotal: string;
  tax_total: string;
  total: string;
}

export interface Account {
  id: string;
  code: string;
  name: string;
  type: "asset" | "liability" | "equity" | "revenue" | "expense";
  subtype: string;
  description: string;
  is_system: boolean;
  is_active: boolean;
}

export interface TrialBalanceRow {
  account_id: string;
  code: string;
  name: string;
  type: Account["type"];
  debit: string;
  credit: string;
}

export interface ReportLine {
  account_id: string | null;
  code: string;
  name: string;
  amount: string;
}

export interface ProfitAndLoss {
  start: string;
  end: string;
  revenue: ReportLine[];
  cost_of_sales: ReportLine[];
  operating_expenses: ReportLine[];
  other_income: ReportLine[];
  total_revenue: string;
  total_cost_of_sales: string;
  gross_profit: string;
  gross_margin_pct: string;
  total_operating_expenses: string;
  operating_profit: string;
  total_other_income: string;
  net_profit: string;
}

export interface BalanceSheet {
  as_of: string;
  current_assets: ReportLine[];
  fixed_assets: ReportLine[];
  current_liabilities: ReportLine[];
  long_term_liabilities: ReportLine[];
  equity: ReportLine[];
  total_assets: string;
  total_liabilities: string;
  total_equity: string;
  balanced: boolean;
}

export interface LedgerLine {
  entry_id: string;
  entry_no: string;
  date: string;
  memo: string;
  source_type: string;
  debit: string;
  credit: string;
  balance: string;
}

export interface GeneralLedger {
  account_id: string;
  code: string;
  name: string;
  opening_balance: string;
  closing_balance: string;
  lines: LedgerLine[];
}

export interface JournalEntryRow {
  id: string;
  entry_no: string;
  date: string;
  memo: string;
  source_type: string;
  source_id: string;
  reversal_of_id: string | null;
  reversed_by_id: string | null;
  total: string;
  lines: { account_id: string; account_code: string; account_name: string; debit: string; credit: string; memo: string }[];
}

export interface TrendPoint {
  period: string;
  revenue: string;
  expenses: string;
  profit: string;
}

export interface Department {
  id: string;
  name: string;
  code: string;
}

export interface Employee {
  id: string;
  employee_no: string;
  full_name: string;
  first_name: string;
  last_name: string;
  other_names: string;
  email: string;
  phone: string;
  gender: string;
  date_of_birth: string | null;
  national_id: string;
  kra_pin: string;
  nssf_no: string;
  shif_no: string;
  department_id: string | null;
  job_title: string;
  employment_type: "permanent" | "contract" | "casual" | "intern";
  status: "active" | "suspended" | "terminated";
  hire_date: string;
  termination_date: string | null;
  basic_salary: string | null;
  payment_method: "bank" | "mpesa" | "cash";
  bank_name: string;
  bank_branch: string;
  bank_account: string;
  mpesa_phone: string;
  has_disability_exemption: boolean;
  nssf_exempt: boolean;
  housing_levy_exempt: boolean;
}

export interface PayItem {
  id: string;
  employee_id: string;
  kind: "earning" | "deduction";
  name: string;
  amount: string;
  taxable: boolean;
  pre_tax: boolean;
  is_active: boolean;
}

export interface LeaveType {
  id: string;
  name: string;
  days_per_year: string;
  is_paid: boolean;
}

export interface LeaveRequest {
  id: string;
  employee_id: string;
  leave_type_id: string;
  start_date: string;
  end_date: string;
  days: string;
  reason: string;
  status: "pending" | "approved" | "rejected" | "cancelled";
  decision_note: string;
}

export interface LeaveBalance {
  leave_type_id: string;
  leave_type: string;
  entitled: string;
  taken: string;
  pending: string;
  remaining: string | null;
}

export interface PayrollRun {
  id: string;
  run_no: string;
  period_year: number;
  period_month: number;
  pay_date: string;
  status: "draft" | "approved" | "paid";
  notes: string;
  employee_count: number;
  gross_pay: string;
  paye: string;
  nssf_employee: string;
  nssf_employer: string;
  shif: string;
  housing_levy_employee: string;
  housing_levy_employer: string;
  nita: string;
  other_deductions: string;
  net_pay: string;
  employer_cost: string;
}

export interface PayslipItem {
  name: string;
  amount: string;
  taxable?: boolean;
  pre_tax?: boolean;
  one_off?: boolean;
  kind?: "earning" | "deduction";
}

export interface Payslip {
  id: string;
  run_id: string;
  employee_id: string;
  employee_no: string;
  employee_name: string;
  department: string;
  days_worked: number;
  days_in_period: number;
  basic_salary: string;
  earnings: PayslipItem[];
  deductions: PayslipItem[];
  adjustments: PayslipItem[];
  gross_pay: string;
  taxable_pay: string;
  nssf_employee: string;
  shif: string;
  housing_levy_employee: string;
  paye: string;
  other_deductions: string;
  total_deductions: string;
  net_pay: string;
  employer_cost: string;
}

export interface StatutoryReport {
  run_no: string;
  period: string;
  kind: string;
  columns: { key: string; label: string }[];
  rows: Record<string, string | number>[];
  totals: Record<string, string>;
}

export interface AssetCategory {
  id: string;
  name: string;
  method: "straight_line" | "declining_balance";
  useful_life_months: number;
  annual_rate: string;
}

export interface FixedAsset {
  id: string;
  asset_no: string;
  name: string;
  category_id: string | null;
  serial_number: string;
  location: string;
  custodian: string;
  acquisition_date: string;
  depreciation_start: string;
  cost: string;
  salvage_value: string;
  method: "straight_line" | "declining_balance";
  useful_life_months: number;
  annual_rate: string;
  accumulated_depreciation: string;
  depreciated_through: string | null;
  status: "active" | "fully_depreciated" | "disposed";
  disposal_date: string | null;
  disposal_proceeds: string;
  net_book_value: string;
}

export interface Bom {
  id: string;
  product_id: string;
  name: string;
  output_qty: string;
  notes: string;
  is_active: boolean;
}

export interface BomDetail {
  id: string;
  product_id: string;
  product_name: string;
  name: string;
  output_qty: string;
  build_qty: string;
  unit_material_cost: string;
  max_buildable: string;
  lines: {
    id: string;
    component_id: string;
    sku: string;
    name: string;
    qty: string;
    scrap_pct: string;
    required: string;
    on_hand: string;
    shortfall: string;
    unit_cost: string;
    extended_cost: string;
  }[];
}

export interface WorkOrder {
  id: string;
  wo_no: string;
  bom_id: string;
  product_id: string;
  warehouse_id: string;
  qty_planned: string;
  qty_produced: string;
  status: "planned" | "completed" | "cancelled";
  planned_date: string | null;
  material_cost: string;
  conversion_cost: string;
  unit_cost: string;
  notes: string;
}

export interface ValuationRow {
  product_id: string;
  sku: string;
  name: string;
  category: string;
  unit: string;
  is_active: boolean;
  qty: string;
  unit_cost: string;
  value: string;
  sale_price: string;
  retail_value: string;
  low_stock_threshold: string;
  status: "ok" | "low" | "out";
  locations: { warehouse_id: string; warehouse: string; qty: string }[];
}

export interface ValuationReport {
  rows: ValuationRow[];
  totals: { products: number; value: string; retail_value: string; low: number; out: number };
  categories: string[];
}

export interface StockMovement {
  id: string;
  created_at: string;
  product_id: string;
  warehouse_id: string;
  type: string;
  qty_delta: string;
  unit_cost: string;
  balance_after: string;
  ref_type: string;
  ref_id: string;
}

export interface ImportReport {
  created: number;
  updated: number;
  skipped: number;
  errors: { row: number; error: string }[];
}

export interface Member {
  id: string;
  user_id: string;
  email: string;
  full_name: string;
  role: "owner" | "admin" | "manager" | "staff" | "viewer";
  is_active: boolean;
  joined_at: string | null;
}

export interface Invitation {
  id: string;
  email: string;
  role: string | null;
  expires_at: string;
  created_at: string;
}

export interface Interaction {
  id: string;
  party_id: string;
  type: "call" | "email" | "meeting" | "note";
  summary: string;
  occurred_at: string;
  follow_up_at: string | null;
  is_follow_up_done: boolean;
}

export interface CrmTask {
  id: string;
  party_id: string | null;
  deal_id: string | null;
  title: string;
  due_date: string | null;
  done: boolean;
}
