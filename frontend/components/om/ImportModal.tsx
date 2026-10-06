"use client";

import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Download, FileSpreadsheet, UploadCloud } from "lucide-react";
import { Button, ErrorBanner, Modal } from "@/components/om/primitives";
import { http } from "@/lib/api/http";
import { errorMessage, openFile } from "@/lib/api/query";
import type { ImportReport } from "@/lib/api/types";

/** Upload a CSV, then show exactly what happened: how many rows were added,
 * how many updated, and which rows failed and why. */
export function ImportModal({
  open,
  onClose,
  title,
  endpoint,
  templatePath,
  templateName,
  help,
  invalidate,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  endpoint: string;
  templatePath: string;
  templateName: string;
  help: string;
  invalidate: string[][];
}) {
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);

  async function send(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    setError(null);
    setReport(null);
    try {
      setReport(await http.upload<ImportReport>(endpoint, file));
      for (const key of invalidate) qc.invalidateQueries({ queryKey: key });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  function close() {
    setReport(null);
    setError(null);
    onClose();
  }

  return (
    <Modal open={open} onClose={close} title={title}>
      <div className="space-y-4">
        <p className="text-sm text-slate-600 dark:text-slate-300">{help}</p>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onClick={() => openFile(templatePath, templateName)}>
            <Download /> Download template
          </Button>
          <Button onClick={() => input.current?.click()} disabled={busy}>
            <UploadCloud /> {busy ? "Importing…" : "Choose CSV file"}
          </Button>
          <input ref={input} type="file" accept=".csv,text/csv" className="hidden" onChange={(e) => { send(e.target.files?.[0]); e.target.value = ""; }} />
        </div>
        <p className="flex items-center gap-1.5 text-xs text-slate-400">
          <FileSpreadsheet className="h-3.5 w-3.5" /> In Excel or Google Sheets: File → Save as / Download → CSV.
        </p>
        <ErrorBanner message={error} />
        {report && (
          <div className="space-y-3">
            <div className="flex items-start gap-2 rounded-lg bg-emerald-50 px-3 py-2.5 text-sm text-emerald-800">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
              <span>
                <b>{report.created}</b> added · <b>{report.updated}</b> updated
                {report.skipped > 0 && <> · <b>{report.skipped}</b> skipped</>}
              </span>
            </div>
            {report.errors.length > 0 && (
              <div className="max-h-56 overflow-y-auto rounded-lg border border-amber-200 bg-amber-50 text-sm">
                <p className="border-b border-amber-200 px-3 py-2 font-medium text-amber-900">Rows that need fixing — correct them in your file and import again</p>
                <ul className="divide-y divide-amber-100">
                  {report.errors.map((e) => (
                    <li key={e.row} className="px-3 py-1.5 text-amber-900">
                      <span className="font-mono text-xs">Row {e.row}</span> — {e.error}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
        <div className="flex justify-end">
          <Button variant="secondary" onClick={close}>{report ? "Done" : "Cancel"}</Button>
        </div>
      </div>
    </Modal>
  );
}
