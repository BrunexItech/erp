export function num(value: string | number | null | undefined): number {
  if (value === null || value === undefined || value === "") return 0;
  return typeof value === "number" ? value : parseFloat(value);
}

export function fmtMoney(value: string | number | null | undefined, currency?: string): string {
  const text = num(value).toLocaleString("en-KE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return currency ? `${currency} ${text}` : text;
}

export function fmtQty(value: string | number | null | undefined): string {
  return num(value).toLocaleString("en-KE", { maximumFractionDigits: 4 });
}

export function fmtDate(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value.length === 10 ? `${value}T00:00:00` : value);
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

// Local calendar dates (YYYY-MM-DD). Never use toISOString() for this: it
// converts to UTC, so in Nairobi (UTC+3) local midnight becomes the previous
// day — "this month" would start on the last day of last month.
function localIso(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function today(): string {
  return localIso(new Date());
}

export function monthStart(): string {
  const d = new Date();
  return localIso(new Date(d.getFullYear(), d.getMonth(), 1));
}

export function yearStart(): string {
  return `${new Date().getFullYear()}-01-01`;
}

export const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

export function humanize(value: string): string {
  return value.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}
