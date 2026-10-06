"use client";

import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { FileText, Image as ImageIcon, Paperclip, Trash2, UploadCloud } from "lucide-react";
import { http } from "@/lib/api/http";
import { errorMessage, keyFor, openFile, useApi } from "@/lib/api/query";
import { fmtDate } from "@/lib/format";
import type { Attachment } from "@/lib/api/types";

const MAX_BYTES = 10 * 1024 * 1024;

function fmtSize(bytes: number): string {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** Files kept against a record — the supplier's invoice scan on a bill, a
 * signed delivery note on an invoice. Private to the business. */
export function Attachments({ entityType, entityId, canWrite = true }: { entityType: string; entityId: string; canWrite?: boolean }) {
  const path = `/attachments?entity_type=${entityType}&entity_id=${entityId}`;
  const { data: files, isLoading } = useApi<Attachment[]>(path);
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: [...keyFor(path), path] });

  async function send(list: FileList | null) {
    if (!list?.length) return;
    setError(null);
    setBusy(true);
    try {
      for (const file of Array.from(list)) {
        if (file.size > MAX_BYTES) throw new Error(`${file.name} is over 10 MB — choose a smaller file.`);
        await http.upload<Attachment>(path, file);
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
      refresh();
    }
  }

  async function remove(file: Attachment) {
    if (!window.confirm(`Remove ${file.filename}?`)) return;
    setError(null);
    try {
      await http.del(`/attachments/${file.id}`);
    } catch (err) {
      setError(errorMessage(err));
    }
    refresh();
  }

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold"><Paperclip className="h-4 w-4 text-slate-400" /> Files</h3>
        {canWrite && (
          <button
            type="button"
            disabled={busy}
            onClick={() => input.current?.click()}
            className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-medium text-brand ring-1 ring-brand/30 hover:bg-brand-50 disabled:opacity-50"
          >
            <UploadCloud className="h-3.5 w-3.5" /> {busy ? "Uploading…" : "Attach a file"}
          </button>
        )}
        <input ref={input} type="file" multiple accept=".pdf,.png,.jpg,.jpeg,.webp,.csv,.xlsx,.docx,.txt" className="hidden" onChange={(e) => { send(e.target.files); e.target.value = ""; }} />
      </div>
      {error && <p className="mb-2 text-sm text-red-600">{error}</p>}
      {isLoading ? (
        <p className="text-sm text-slate-400">Loading…</p>
      ) : !files?.length ? (
        <p className="rounded-xl border border-dashed border-slate-200 px-3 py-4 text-center text-xs text-slate-400 dark:border-navy-600">
          Nothing attached yet{canWrite ? " — PDF, images, spreadsheets or documents up to 10 MB." : "."}
        </p>
      ) : (
        <ul className="divide-y divide-slate-100 rounded-xl border border-slate-200 dark:divide-navy-700 dark:border-navy-700">
          {files.map((f) => (
            <li key={f.id} className="flex items-center gap-3 px-3 py-2 text-sm">
              {f.content_type.startsWith("image/") ? <ImageIcon className="h-4 w-4 shrink-0 text-slate-400" /> : <FileText className="h-4 w-4 shrink-0 text-slate-400" />}
              <button
                type="button"
                className="min-w-0 flex-1 truncate text-left font-medium text-brand hover:underline"
                onClick={() => openFile(`/attachments/${f.id}/download`, f.content_type === "application/pdf" || f.content_type.startsWith("image/") ? undefined : f.filename).catch((err) => setError(errorMessage(err)))}
              >
                {f.filename}
              </button>
              <span className="shrink-0 text-xs text-slate-400">{fmtSize(f.size)} · {fmtDate(f.created_at)}</span>
              {canWrite && (
                <button type="button" aria-label={`Remove ${f.filename}`} onClick={() => remove(f)} className="shrink-0 text-slate-400 hover:text-red-600"><Trash2 className="h-4 w-4" /></button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
