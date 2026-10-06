"use client";

import { useEffect, useRef, useState } from "react";
import { CheckCircle2, Loader2, Smartphone, XCircle } from "lucide-react";
import { Button, ErrorBanner, Field, Input } from "@/components/om/primitives";
import { http } from "@/lib/api/http";
import { errorMessage } from "@/lib/api/query";
import { fmtMoney } from "@/lib/format";
import type { MpesaRequest } from "@/lib/api/types";

const POLL_MS = 3000;
const GIVE_UP_MS = 120_000;

/** Sends an M-Pesa "enter your PIN" prompt to the customer's phone and waits
 * for Safaricom's answer. With an invoiceId the payment is recorded against
 * that invoice by the server; without one (the till) the caller completes the
 * sale in onPaid using the M-Pesa code. */
export function MpesaPrompt({
  amount,
  invoiceId,
  reference,
  defaultPhone = "",
  onPaid,
  onCancel,
}: {
  amount: number;
  invoiceId?: string;
  reference: string;
  defaultPhone?: string;
  onPaid: (receipt: string) => void;
  onCancel: () => void;
}) {
  const [phone, setPhone] = useState(defaultPhone);
  const [request, setRequest] = useState<MpesaRequest | null>(null);
  const [sending, setSending] = useState(false);
  const [timedOut, setTimedOut] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const paid = useRef(onPaid);
  paid.current = onPaid;

  const pendingId = request?.status === "pending" ? request.id : null;
  useEffect(() => {
    if (!pendingId) return;
    const started = Date.now();
    const timer = setInterval(async () => {
      try {
        const latest = await http.get<MpesaRequest>(`/sales/mpesa/requests/${pendingId}`);
        if (latest.status !== "pending") {
          setRequest(latest);
          if (latest.status === "success") paid.current(latest.mpesa_receipt ?? "");
        } else if (Date.now() - started > GIVE_UP_MS) {
          setTimedOut(true);
          clearInterval(timer);
        }
      } catch {
        // A dropped connection shouldn't end the wait — the next tick retries.
      }
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [pendingId]);

  async function send(e: React.FormEvent) {
    e.preventDefault();
    e.stopPropagation();
    setError(null);
    setTimedOut(false);
    setSending(true);
    try {
      setRequest(await http.post<MpesaRequest>("/sales/mpesa/stk", { phone, amount: amount.toFixed(2), invoice_id: invoiceId ?? null, reference }));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSending(false);
    }
  }

  if (request?.status === "success") {
    return (
      <div className="flex items-center gap-3 rounded-xl bg-emerald-50 p-4 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-200">
        <CheckCircle2 className="h-6 w-6 shrink-0" />
        <div>
          <p className="font-semibold">Payment received — {fmtMoney(request.amount)}</p>
          <p className="text-sm">M-Pesa code {request.mpesa_receipt}</p>
        </div>
      </div>
    );
  }

  if (request?.status === "pending" && !timedOut) {
    return (
      <div className="space-y-3 rounded-xl bg-slate-50 p-4 dark:bg-navy-900">
        <div className="flex items-center gap-3">
          <Loader2 className="h-6 w-6 shrink-0 animate-spin text-brand" />
          <div>
            <p className="font-semibold">Waiting for the customer…</p>
            <p className="text-sm text-slate-500">A prompt for {fmtMoney(request.amount)} was sent to {request.phone}. They enter their M-Pesa PIN to pay.</p>
          </div>
        </div>
        <Button type="button" variant="secondary" onClick={onCancel}>Stop waiting</Button>
      </div>
    );
  }

  return (
    <form onSubmit={send} className="space-y-3 rounded-xl bg-slate-50 p-4 dark:bg-navy-900">
      {request?.status === "failed" && (
        <p className="flex items-center gap-2 text-sm text-red-600"><XCircle className="h-4 w-4 shrink-0" /> {request.result_desc || "The customer didn't complete the payment."}</p>
      )}
      {timedOut && <p className="text-sm text-amber-700">No answer yet. If the customer has paid, it will still be recorded when Safaricom confirms — otherwise send the prompt again.</p>}
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-[12rem] flex-1">
          <Field label="Customer's M-Pesa number">
            <Input required inputMode="tel" autoFocus placeholder="0712 345 678" value={phone} onChange={(e) => setPhone(e.target.value)} />
          </Field>
        </div>
        <Button type="submit" disabled={sending}><Smartphone /> {sending ? "Sending…" : `Request ${fmtMoney(Math.round(amount))}`}</Button>
        <Button type="button" variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
      <ErrorBanner message={error} />
    </form>
  );
}
