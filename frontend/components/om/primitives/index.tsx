"use client";

import {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TdHTMLAttributes,
  TextareaHTMLAttributes,
  useEffect,
} from "react";
import { AlertCircle, Inbox, X } from "lucide-react";

const FIELD =
  "w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-navy-900 shadow-sm transition placeholder:text-slate-400 " +
  "focus:border-brand focus:outline-none focus:ring-4 focus:ring-brand/10 disabled:bg-slate-50 disabled:text-slate-400 " +
  "dark:border-navy-600 dark:bg-navy-900 dark:text-white";

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-2xl border border-slate-200/80 bg-white shadow-card dark:border-navy-700 dark:bg-navy-800 ${className}`}>
      {children}
    </div>
  );
}

export function Button({
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" | "ghost" }) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition focus:outline-none focus-visible:ring-4 disabled:cursor-not-allowed disabled:opacity-50 [&_svg]:h-4 [&_svg]:w-4";
  const variants = {
    primary: "bg-brand text-white shadow-sm hover:bg-brand-600 focus-visible:ring-brand/25",
    secondary:
      "border border-slate-200 bg-white text-navy-900 shadow-sm hover:border-slate-300 hover:bg-slate-50 focus-visible:ring-slate-200 dark:border-navy-600 dark:bg-navy-700 dark:text-white dark:hover:bg-navy-600",
    danger: "bg-red-600 text-white shadow-sm hover:bg-red-700 focus-visible:ring-red-200",
    ghost: "text-slate-600 hover:bg-slate-100 hover:text-navy-900 dark:text-slate-300 dark:hover:bg-navy-700",
  };
  return <button className={`${base} ${variants[variant]} ${className}`} {...props} />;
}

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  const { className = "", ...rest } = props;
  return <input className={`${FIELD} ${className}`} {...rest} />;
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  const { className = "", ...rest } = props;
  return <select className={`${FIELD} pr-8 ${className}`} {...rest} />;
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const { className = "", ...rest } = props;
  return <textarea rows={3} className={`${FIELD} ${className}`} {...rest} />;
}

export function Label({ children }: { children: ReactNode }) {
  return <label className="mb-1.5 block text-xs font-medium text-slate-600 dark:text-slate-300">{children}</label>;
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <div>
      <Label>{label}</Label>
      {children}
      {hint && <p className="mt-1 text-xs text-slate-400">{hint}</p>}
    </div>
  );
}

export function Checkbox({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex cursor-pointer items-center gap-2 text-sm text-navy-900 dark:text-slate-200">
      <input
        type="checkbox"
        className="h-4 w-4 rounded border-slate-300 accent-brand"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      {label}
    </label>
  );
}

export function Switch({ checked, onChange, disabled, label }: { checked: boolean; onChange: (v: boolean) => void; disabled?: boolean; label?: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition disabled:cursor-not-allowed disabled:opacity-40 ${
        checked ? "bg-brand" : "bg-slate-300 dark:bg-navy-600"
      }`}
    >
      <span className={`inline-block h-5 w-5 transform rounded-full bg-white shadow transition ${checked ? "translate-x-5" : "translate-x-0.5"}`} />
    </button>
  );
}

type Tone = "neutral" | "success" | "warning" | "danger" | "info";

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: Tone }) {
  const tones: Record<Tone, string> = {
    neutral: "bg-slate-100 text-slate-700 ring-slate-200 dark:bg-navy-700 dark:text-slate-200 dark:ring-navy-600",
    success: "bg-emerald-50 text-emerald-700 ring-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-300 dark:ring-emerald-800",
    warning: "bg-amber-50 text-amber-700 ring-amber-200 dark:bg-amber-900/30 dark:text-amber-300 dark:ring-amber-800",
    danger: "bg-red-50 text-red-700 ring-red-200 dark:bg-red-900/30 dark:text-red-300 dark:ring-red-800",
    info: "bg-sky-50 text-sky-700 ring-sky-200 dark:bg-sky-900/30 dark:text-sky-300 dark:ring-sky-800",
  };
  const dots: Record<Tone, string> = {
    neutral: "bg-slate-400", success: "bg-emerald-500", warning: "bg-amber-500", danger: "bg-red-500", info: "bg-sky-500",
  };
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${tones[tone]}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${dots[tone]}`} />
      {children}
    </span>
  );
}

export function EmptyState({ title, description, icon, action }: { title: string; description?: string; icon?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-slate-200 px-6 py-12 text-center dark:border-navy-600">
      <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-full bg-brand-50 text-brand dark:bg-navy-700 [&_svg]:h-5 [&_svg]:w-5">
        {icon ?? <Inbox />}
      </div>
      <p className="text-sm font-semibold text-navy-900 dark:text-white">{title}</p>
      {description && <p className="mt-1 max-w-sm text-sm text-slate-500 dark:text-slate-400">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Table({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">{children}</table>
    </div>
  );
}

export function Th({ children }: { children?: ReactNode }) {
  return (
    <th className="whitespace-nowrap border-b border-slate-200 bg-slate-50/60 px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500 first:rounded-tl-2xl last:rounded-tr-2xl dark:border-navy-700 dark:bg-navy-900/40 dark:text-slate-400">
      {children}
    </th>
  );
}

export function Td({
  children,
  className = "",
  ...props
}: { children: ReactNode; className?: string } & TdHTMLAttributes<HTMLTableCellElement>) {
  return (
    <td className={`border-b border-slate-100 px-4 py-3 text-navy-900 dark:border-navy-700/60 dark:text-slate-100 ${className}`} {...props}>
      {children}
    </td>
  );
}

export function StatTile({
  label,
  value,
  sub,
  icon,
  tone = "brand",
}: {
  label: string;
  value: string;
  sub?: string;
  icon?: ReactNode;
  tone?: "brand" | "emerald" | "amber" | "rose" | "sky" | "violet";
}) {
  const tones = {
    brand: "bg-brand-50 text-brand",
    emerald: "bg-emerald-50 text-emerald-600",
    amber: "bg-amber-50 text-amber-600",
    rose: "bg-rose-50 text-rose-600",
    sky: "bg-sky-50 text-sky-600",
    violet: "bg-violet-50 text-violet-600",
  };
  return (
    <Card className="p-5">
      <div className="flex items-start justify-between gap-3">
        <p className="text-xs font-medium text-slate-500 dark:text-slate-400">{label}</p>
        {icon && <span className={`flex h-8 w-8 items-center justify-center rounded-lg [&_svg]:h-4 [&_svg]:w-4 ${tones[tone]}`}>{icon}</span>}
      </div>
      <p className="mt-2 truncate text-xl font-semibold tracking-tight text-navy-900 sm:text-2xl dark:text-white" title={value}>{value}</p>
      {sub && <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{sub}</p>}
    </Card>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-navy-900 dark:text-white">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-sm text-slate-500 dark:text-slate-400">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { key: T; label: string; count?: number }[];
  value: T;
  onChange: (key: T) => void;
}) {
  return (
    <div className="-mx-1 flex gap-1 overflow-x-auto border-b border-slate-200 px-1 dark:border-navy-700">
      {tabs.map((tab) => (
        <button
          key={tab.key}
          type="button"
          onClick={() => onChange(tab.key)}
          className={`relative whitespace-nowrap px-3 pb-3 pt-1 text-sm font-medium transition ${
            value === tab.key ? "text-brand" : "text-slate-500 hover:text-navy-900 dark:text-slate-400 dark:hover:text-white"
          }`}
        >
          {tab.label}
          {tab.count !== undefined && (
            <span className="ml-1.5 rounded-full bg-slate-100 px-1.5 text-xs text-slate-600 dark:bg-navy-700 dark:text-slate-300">{tab.count}</span>
          )}
          {value === tab.key && <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-brand" />}
        </button>
      ))}
    </div>
  );
}

export function Modal({
  open,
  onClose,
  title,
  children,
  wide = false,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-navy-950/40 p-4 backdrop-blur-sm sm:p-10"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`w-full ${wide ? "max-w-4xl" : "max-w-lg"} animate-[modal_150ms_ease-out] rounded-2xl bg-white shadow-lift ring-1 ring-slate-200 dark:bg-navy-800 dark:ring-navy-700`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4 dark:border-navy-700">
          <h2 className="text-base font-semibold text-navy-900 dark:text-white">{title}</h2>
          <button onClick={onClose} className="rounded-lg p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-navy-900 dark:hover:bg-navy-700" aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="p-6">{children}</div>
      </div>
      <style>{`@keyframes modal { from { opacity: 0; transform: translateY(8px) scale(.98) } to { opacity: 1; transform: none } }`}</style>
    </div>
  );
}

export function ErrorBanner({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
      <span>{message}</span>
    </div>
  );
}

export function Loading({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-3 p-6" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-4 animate-pulse rounded bg-slate-100 dark:bg-navy-700" style={{ width: `${90 - i * 12}%` }} />
      ))}
    </div>
  );
}

export function SectionTitle({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-3 flex items-center justify-between">
      <h2 className="text-sm font-semibold text-navy-900 dark:text-white">{children}</h2>
      {right}
    </div>
  );
}

/** Grouped bars (e.g. revenue vs expenses per month), dependency-free SVG. */
export function BarChart({
  data,
  series,
  format = (v: number) => v.toLocaleString(),
}: {
  data: { label: string; values: number[] }[];
  series: { name: string; color: string }[];
  format?: (v: number) => string;
}) {
  const max = Math.max(1, ...data.flatMap((d) => d.values.map((v) => Math.abs(v))));
  const gridLines = [0.25, 0.5, 0.75, 1];
  return (
    <div>
      <div className="relative h-56">
        {gridLines.map((g) => (
          <div key={g} className="absolute inset-x-0 border-t border-dashed border-slate-100 dark:border-navy-700" style={{ bottom: `${g * 100}%` }}>
            <span className="absolute -top-2 right-0 bg-white pl-1 text-[10px] text-slate-400 dark:bg-navy-800">{format(max * g)}</span>
          </div>
        ))}
        <div className="absolute inset-0 flex items-end gap-1 border-b border-slate-200 pr-14 dark:border-navy-700">
          {data.map((d) => (
            <div key={d.label} className="group flex h-full flex-1 items-end justify-center gap-0.5">
              {d.values.map((v, s) => (
                <div
                  key={s}
                  title={`${d.label} · ${series[s].name}: ${format(v)}`}
                  className="w-full max-w-[18px] rounded-t-md transition-opacity group-hover:opacity-80"
                  style={{ height: `${(Math.max(v, 0) / max) * 100}%`, background: series[s].color }}
                />
              ))}
            </div>
          ))}
        </div>
      </div>
      <div className="mt-2 flex gap-1 pr-14 text-[10px] text-slate-400">
        {data.map((d) => (
          <span key={d.label} className="flex-1 text-center">{d.label}</span>
        ))}
      </div>
      <div className="mt-3 flex gap-4 text-xs text-slate-500 dark:text-slate-400">
        {series.map((s) => (
          <span key={s.name} className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: s.color }} />
            {s.name}
          </span>
        ))}
      </div>
    </div>
  );
}
