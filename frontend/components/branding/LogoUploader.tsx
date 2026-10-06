"use client";

import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ImagePlus, Trash2, UploadCloud } from "lucide-react";
import { http, mediaUrl } from "@/lib/api/http";
import { errorMessage } from "@/lib/api/query";
import type { Branding } from "@/lib/api/types";

/** Drag-and-drop (or click) logo upload. The server re-encodes the image, so
 * what you see afterwards is exactly what prints on documents. */
export function LogoUploader({ logoUrl, onChange }: { logoUrl: string | null; onChange?: (branding: Branding) => void }) {
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function done(branding: Branding) {
    qc.setQueryData(["platform", "branding"], branding);
    onChange?.(branding);
  }

  async function send(file: File | undefined) {
    if (!file) return;
    setError(null);
    if (!/^image\/(png|jpeg|webp)$/.test(file.type)) {
      setError("Please choose a PNG, JPG or WebP image.");
      return;
    }
    if (file.size > 3 * 1024 * 1024) {
      setError("That file is over 3 MB — choose a smaller one.");
      return;
    }
    setBusy(true);
    try {
      await done(await http.upload<Branding>("/workspaces/branding/logo", file));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    try {
      await done(await http.del<Branding>("/workspaces/branding/logo"));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const src = mediaUrl(logoUrl);

  return (
    <div>
      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); send(e.dataTransfer.files[0]); }}
        className={`flex items-center gap-5 rounded-2xl border-2 border-dashed p-5 transition ${
          dragging ? "border-brand bg-brand-50" : "border-slate-200 bg-slate-50/50 dark:border-navy-600 dark:bg-navy-900/40"
        }`}
      >
        <div className="flex h-24 w-40 shrink-0 items-center justify-center rounded-xl bg-white p-3 shadow-card ring-1 ring-slate-200">
          {src ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={src} alt="Company logo" className="max-h-full max-w-full object-contain" />
          ) : (
            <ImagePlus className="h-8 w-8 text-slate-300" />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-navy-900 dark:text-white">{src ? "Your logo" : "Upload your logo"}</p>
          <p className="mt-0.5 text-xs text-slate-500">Drag an image here or choose a file. PNG with a transparent background looks best · up to 3 MB.</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={() => input.current?.click()}
              className="inline-flex items-center gap-2 rounded-lg bg-brand px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-600 disabled:opacity-50"
            >
              <UploadCloud className="h-4 w-4" />
              {busy ? "Uploading…" : src ? "Replace" : "Choose file"}
            </button>
            {src && (
              <button type="button" disabled={busy} onClick={remove} className="inline-flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm text-slate-600 ring-1 ring-slate-200 hover:bg-white">
                <Trash2 className="h-4 w-4" /> Remove
              </button>
            )}
          </div>
        </div>
        <input ref={input} type="file" accept="image/png,image/jpeg,image/webp" className="hidden" onChange={(e) => { send(e.target.files?.[0]); e.target.value = ""; }} />
      </div>
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
    </div>
  );
}
