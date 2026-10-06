"use client";

import { useEffect, useState } from "react";
import { Check } from "lucide-react";
import { http } from "@/lib/api/http";
import type { Branding } from "@/lib/api/types";

type Template = Branding["invoice_template"];

const DESIGNS: { key: Template; name: string; blurb: string }[] = [
  { key: "modern", name: "Modern", blurb: "Clean, with your colour as the accent" },
  { key: "bold", name: "Bold", blurb: "Full-colour header that leads with your brand" },
  { key: "classic", name: "Classic", blurb: "Centred, formal, black and white" },
];

function Thumb({ kind, color }: { kind: Template; color: string }) {
  const ink = "#111827";
  const accent = kind === "classic" ? ink : color;
  return (
    <div className="relative h-28 w-full overflow-hidden rounded-lg bg-white ring-1 ring-slate-200">
      {kind === "bold" ? (
        <div className="m-2 h-9 rounded" style={{ background: color }} />
      ) : kind === "classic" ? (
        <>
          <div className="h-1" style={{ background: color }} />
          <div className="mx-auto mt-3 h-2 w-16 rounded-sm" style={{ background: ink }} />
          <div className="mx-auto mt-1 h-1 w-24 rounded-sm bg-slate-300" />
          <div className="mx-2 mt-2 border-t-2" style={{ borderColor: ink }} />
        </>
      ) : (
        <>
          <div className="h-1.5" style={{ background: color }} />
          <div className="mt-2 flex justify-between px-2">
            <div className="h-2 w-12 rounded-sm" style={{ background: ink }} />
            <div className="h-2.5 w-14 rounded-sm" style={{ background: color }} />
          </div>
        </>
      )}
      <div className="absolute inset-x-2 bottom-9 h-2 rounded-sm" style={{ background: accent }} />
      <div className="absolute inset-x-2 bottom-6 h-1 rounded-sm bg-slate-200" />
      <div className="absolute inset-x-2 bottom-4 h-1 rounded-sm bg-slate-200" />
      <div className="absolute bottom-1.5 right-2 h-1.5 w-10 rounded-sm" style={{ background: accent }} />
    </div>
  );
}

/** Pick an invoice design and see it on the business's real letterhead. */
export function DesignPicker({
  value,
  color,
  refreshKey,
  onChange,
}: {
  value: Template;
  color: string;
  refreshKey?: string; // change to re-render the preview (e.g. after a logo upload)
  onChange: (template: Template) => void;
}) {
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const validColor = /^#[0-9a-fA-F]{6}$/.test(color) ? color : "#1a7a8c";

  useEffect(() => {
    let cancelled = false;
    let made: string | null = null;
    const timer = setTimeout(async () => {
      try {
        const blob = await http.getBlob(`/sales/documents/preview?template=${value}&brand_color=${encodeURIComponent(validColor)}`);
        if (cancelled) return;
        made = URL.createObjectURL(blob);
        setPreviewUrl(made);
      } catch {
        if (!cancelled) setPreviewUrl(null);
      }
    }, 350);
    return () => {
      cancelled = true;
      clearTimeout(timer);
      if (made) URL.revokeObjectURL(made);
    };
  }, [value, validColor, refreshKey]);

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
      <div className="grid grid-cols-3 gap-3 self-start lg:grid-cols-1 xl:grid-cols-3">
        {DESIGNS.map((d) => {
          const active = d.key === value;
          return (
            <button
              key={d.key}
              type="button"
              onClick={() => onChange(d.key)}
              className={`relative rounded-xl p-2 text-left transition ${active ? "bg-brand-50 ring-2 ring-brand" : "ring-1 ring-slate-200 hover:ring-slate-300"}`}
            >
              {active && (
                <span className="absolute right-3 top-3 z-10 flex h-5 w-5 items-center justify-center rounded-full bg-brand text-white">
                  <Check className="h-3 w-3" />
                </span>
              )}
              <Thumb kind={d.key} color={validColor} />
              <p className="mt-2 text-sm font-medium text-navy-900 dark:text-white">{d.name}</p>
              <p className="text-xs text-slate-500">{d.blurb}</p>
            </button>
          );
        })}
      </div>
      <div>
        <div className="overflow-hidden rounded-xl bg-slate-100 ring-1 ring-slate-200">
          {previewUrl ? (
            <iframe title="Invoice preview" src={`${previewUrl}#toolbar=0&navpanes=0&view=FitH`} className="h-[560px] w-full" />
          ) : (
            <div className="flex h-[560px] items-center justify-center text-sm text-slate-400">Preparing preview…</div>
          )}
        </div>
        {/* Phones and some browsers can't show a PDF inline. */}
        {previewUrl && (
          <a href={previewUrl} target="_blank" rel="noreferrer" className="mt-2 inline-block text-sm text-brand hover:underline">
            Open the preview in a new tab
          </a>
        )}
      </div>
    </div>
  );
}
