"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AlertTriangle, Megaphone, ShieldAlert, X } from "lucide-react";
import { useApi } from "@/lib/api/query";
import { session } from "@/lib/session";
import type { Me } from "@/lib/api/types";

interface Announcement {
  id: string;
  title: string;
  body: string;
  level: "info" | "warning";
}

const DISMISSED_KEY = "erp.dismissed_announcements";

/** Bars across the top of the app: support-session warning, billing status,
 * and operator announcements (each dismissible, remembered per browser). */
export function Notices({ me }: { me?: Me }) {
  const { data: announcements } = useApi<Announcement[]>("/announcements");
  const [dismissed, setDismissed] = useState<string[]>([]);
  const [impersonating, setImpersonating] = useState<string | null>(null);

  useEffect(() => {
    setImpersonating(session.impersonating());
    try {
      setDismissed(JSON.parse(localStorage.getItem(DISMISSED_KEY) ?? "[]"));
    } catch {
      // ignore unreadable storage
    }
  }, []);

  function dismiss(id: string) {
    const next = [...dismissed, id];
    setDismissed(next);
    try {
      localStorage.setItem(DISMISSED_KEY, JSON.stringify(next.slice(-50)));
    } catch {
      // ignore
    }
  }

  const billing = me?.billing;
  return (
    <>
      {impersonating && (
        <div className="flex items-center justify-center gap-3 bg-red-600 px-4 py-2 text-sm text-white">
          <ShieldAlert className="h-4 w-4 shrink-0" />
          <span>Support session — you are signed in as <b>{impersonating}</b>. Everything you do is recorded.</span>
          <button
            onClick={() => { session.stopImpersonating(); window.location.href = "/admin"; }}
            className="rounded-md bg-white/20 px-2.5 py-1 text-xs font-medium hover:bg-white/30"
          >
            Exit to admin console
          </button>
        </div>
      )}
      {billing && billing.level === "grace" && (
        <div className="flex items-center justify-center gap-3 bg-amber-100 px-4 py-2 text-sm text-amber-900">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span>{billing.message}</span>
          <Link href="/dashboard/settings?tab=billing" className="font-medium underline">Pay now</Link>
        </div>
      )}
      {(announcements ?? []).filter((a) => !dismissed.includes(a.id)).map((a) => (
        <div key={a.id} className={`flex items-center justify-center gap-3 px-4 py-2 text-sm ${a.level === "warning" ? "bg-amber-100 text-amber-900" : "bg-brand-50 text-navy-900"}`}>
          <Megaphone className="h-4 w-4 shrink-0" />
          <span><b>{a.title}</b>{a.body && ` — ${a.body}`}</span>
          <button onClick={() => dismiss(a.id)} aria-label="Dismiss" className="rounded p-0.5 opacity-60 hover:opacity-100"><X className="h-4 w-4" /></button>
        </div>
      ))}
    </>
  );
}
