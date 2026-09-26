// Mirrors backend/app/core/features.py MODULES — kept as the single source of
// truth for nav labels/keys on the frontend side. If a workspace's Actor.features
// (returned by /auth endpoints via the JWT-derived session) doesn't include a key,
// the corresponding nav item and routes should be hidden/blocked client-side too
// (the backend still enforces it server-side regardless).
export const MODULES = {
  crm: "CRM",
  inventory: "Inventory",
  sales: "Sales",
  purchasing: "Purchasing",
  accounting: "Accounting",
  pos: "POS",
  hr: "HR & Payroll",
  assets: "Fixed Assets",
  manufacturing: "Manufacturing",
} as const;

export type ModuleKey = keyof typeof MODULES;
