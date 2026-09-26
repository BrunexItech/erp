"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { CornerDownLeft, Search } from "lucide-react";
import type { NavItem } from "./nav";

/** Ctrl/⌘ + K — jump to any screen by typing a few letters. */
export function CommandPalette({ items, open, onClose }: { items: NavItem[]; open: boolean; onClose: () => void }) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter((i) => `${i.label} ${i.keywords ?? ""}`.toLowerCase().includes(q));
  }, [items, query]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setIndex(0);
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  if (!open) return null;

  function go(item: NavItem | undefined) {
    if (!item) return;
    onClose();
    router.push(item.href);
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-start justify-center bg-navy-950/40 p-4 pt-[15vh] backdrop-blur-sm" onClick={onClose}>
      <div className="w-full max-w-lg overflow-hidden rounded-2xl bg-white shadow-lift ring-1 ring-slate-200 dark:bg-navy-800 dark:ring-navy-700" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-3 border-b border-slate-100 px-4 dark:border-navy-700">
          <Search className="h-4 w-4 text-slate-400" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => { setQuery(e.target.value); setIndex(0); }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") { e.preventDefault(); setIndex((i) => Math.min(i + 1, results.length - 1)); }
              if (e.key === "ArrowUp") { e.preventDefault(); setIndex((i) => Math.max(i - 1, 0)); }
              if (e.key === "Enter") go(results[index]);
              if (e.key === "Escape") onClose();
            }}
            placeholder="Go to… (invoices, payroll, trial balance)"
            className="h-12 flex-1 bg-transparent text-sm text-navy-900 outline-none placeholder:text-slate-400 dark:text-white"
          />
          <kbd className="rounded border border-slate-200 px-1.5 text-[10px] text-slate-400 dark:border-navy-600">ESC</kbd>
        </div>
        <ul className="max-h-80 overflow-y-auto p-2">
          {results.map((item, i) => {
            const Icon = item.icon;
            return (
              <li key={item.href}>
                <button
                  onMouseEnter={() => setIndex(i)}
                  onClick={() => go(item)}
                  className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm ${
                    i === index ? "bg-brand-50 text-brand dark:bg-navy-700 dark:text-white" : "text-slate-700 dark:text-slate-300"
                  }`}
                >
                  <Icon className="h-4 w-4" />
                  <span className="flex-1">{item.label}</span>
                  {i === index && <CornerDownLeft className="h-3.5 w-3.5 opacity-60" />}
                </button>
              </li>
            );
          })}
          {!results.length && <li className="px-3 py-6 text-center text-sm text-slate-400">No matches</li>}
        </ul>
      </div>
    </div>
  );
}
