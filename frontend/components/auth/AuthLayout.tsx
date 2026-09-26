import { BarChart3, Receipt, ShieldCheck, Store, Wallet } from "lucide-react";

const POINTS = [
  { icon: Receipt, title: "KRA-ready tax invoices", text: "Numbered invoices, credit notes and statements on your own letterhead." },
  { icon: Wallet, title: "Kenyan payroll built in", text: "PAYE, NSSF, SHIF and Housing Levy — payslips and P9s in one click." },
  { icon: Store, title: "Point of sale that syncs", text: "Every till sale updates stock, receivables and the ledger instantly." },
  { icon: BarChart3, title: "Books that balance", text: "Double-entry accounting behind every transaction, always audit-ready." },
];

export function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-screen lg:grid-cols-[1.1fr_1fr]">
      <div className="relative hidden overflow-hidden bg-navy-900 p-12 text-white lg:flex lg:flex-col">
        <div className="pointer-events-none absolute -right-32 -top-32 h-96 w-96 rounded-full bg-brand/30 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-40 -left-20 h-96 w-96 rounded-full bg-brand-600/20 blur-3xl" />
        <div className="relative flex items-center gap-2 text-lg font-semibold">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand">
            <ShieldCheck className="h-5 w-5" />
          </span>
          Business Suite
        </div>
        <div className="relative my-auto max-w-lg">
          <h2 className="text-4xl font-semibold leading-tight tracking-tight">
            Run your whole business from one place.
          </h2>
          <p className="mt-4 text-slate-300">Sales, stock, accounting, payroll and assets — connected, so the numbers always agree.</p>
          <ul className="mt-10 space-y-6">
            {POINTS.map(({ icon: Icon, title, text }) => (
              <li key={title} className="flex gap-4">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white/10 ring-1 ring-white/10">
                  <Icon className="h-5 w-5 text-brand-200" />
                </span>
                <div>
                  <p className="font-medium">{title}</p>
                  <p className="text-sm text-slate-400">{text}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-xs text-slate-500">Built for East African SMEs</p>
      </div>
      <div className="flex items-center justify-center bg-white px-6 py-12 dark:bg-navy-900">
        <div className="w-full max-w-sm">{children}</div>
      </div>
    </div>
  );
}
