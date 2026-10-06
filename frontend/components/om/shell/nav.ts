import {
  BarChart3,
  Boxes,
  Briefcase,
  Building2,
  Factory,
  LayoutDashboard,
  type LucideIcon,
  Receipt,
  Settings,
  ShoppingCart,
  Store,
  Users,
  Wallet,
} from "lucide-react";
import type { ModuleKey } from "@/lib/features";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  moduleKey: ModuleKey | null; // null = always visible
  permission?: string; // hide unless the member's role grants it ("x.write" also satisfies "x.read")
  keywords?: string; // extra words for the command palette
}

export interface NavGroup {
  label: string | null;
  items: NavItem[];
}

export const NAV_GROUPS: NavGroup[] = [
  {
    label: null,
    items: [
      { href: "/dashboard", label: "Overview", icon: LayoutDashboard, moduleKey: null, keywords: "home dashboard kpi" },
      { href: "/pos", label: "Point of Sale", icon: Store, moduleKey: "pos", permission: "sales.write", keywords: "till cashier checkout register" },
    ],
  },
  {
    label: "Customers & Sales",
    items: [
      { href: "/dashboard/crm", label: "CRM", icon: Users, moduleKey: "crm", permission: "crm.read", keywords: "contacts customers leads deals" },
      { href: "/dashboard/sales", label: "Sales & Invoicing", icon: Receipt, moduleKey: "sales", permission: "sales.read", keywords: "invoice quote credit note receivables statement" },
    ],
  },
  {
    label: "Operations",
    items: [
      { href: "/dashboard/purchasing", label: "Purchasing", icon: ShoppingCart, moduleKey: "purchasing", permission: "purchasing.read", keywords: "po bills suppliers payables expenses" },
      { href: "/dashboard/inventory", label: "Inventory", icon: Boxes, moduleKey: "inventory", permission: "inventory.read", keywords: "stock products warehouses transfers" },
      { href: "/dashboard/manufacturing", label: "Manufacturing", icon: Factory, moduleKey: "manufacturing", permission: "manufacturing.read", keywords: "bom work orders production" },
    ],
  },
  {
    label: "Finance",
    items: [
      { href: "/dashboard/accounting", label: "Accounting", icon: BarChart3, moduleKey: "accounting", permission: "accounting.read", keywords: "ledger journal profit loss balance sheet trial" },
      { href: "/dashboard/assets", label: "Fixed Assets", icon: Building2, moduleKey: "assets", permission: "assets.read", keywords: "depreciation register" },
    ],
  },
  {
    label: "People",
    items: [
      { href: "/dashboard/hr", label: "Employees & Leave", icon: Briefcase, moduleKey: "hr", permission: "hr.read", keywords: "staff departments leave" },
      { href: "/dashboard/payroll", label: "Payroll", icon: Wallet, moduleKey: "hr", permission: "payroll.read", keywords: "payslip paye nssf shif p9 salary" },
    ],
  },
  {
    label: null,
    items: [{ href: "/dashboard/settings", label: "Settings", icon: Settings, moduleKey: null, keywords: "branding company logo kra pin" }],
  },
];

export const NAV_ITEMS: NavItem[] = NAV_GROUPS.flatMap((g) => g.items);
