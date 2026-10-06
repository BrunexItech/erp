"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, Smartphone } from "lucide-react";
import { Badge, Button, Card, ErrorBanner, Field, Input, Loading, Select, Switch } from "@/components/om/primitives";
import { errorMessage, useApi, useApiMutation } from "@/lib/api/query";
import type { MpesaConfig } from "@/lib/api/types";

/** Safaricom Daraja ("Lipa na M-Pesa Online") details. With these saved, the
 * till and invoices can send a pay prompt straight to the customer's phone. */
export function PaymentsTab() {
  const { data: config, isLoading } = useApi<MpesaConfig>("/sales/mpesa/config");
  const save = useApiMutation<Record<string, unknown>, MpesaConfig>("put", "/sales/mpesa/config", [["sales", "mpesa"]]);
  const [form, setForm] = useState<{ environment: string; shortcode: string; till_number: string; consumer_key: string; consumer_secret: string; passkey: string; is_active: boolean } | null>(null);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (config) {
      setForm((current) => current ?? {
        environment: config.environment ?? "sandbox", shortcode: config.shortcode ?? "", till_number: config.till_number ?? "",
        consumer_key: "", consumer_secret: "", passkey: "", is_active: config.is_active,
      });
    }
  }, [config]);

  if (isLoading || !config || !form) return <Card><Loading /></Card>;

  const callback = `${(config.callback_base ?? "").replace(/\/$/, "")}/api/v1/mpesa/callback/…`;
  const localCallback = /localhost|127\.0\.0\.1/.test(config.callback_base ?? "");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!form) return;
    setError(null);
    setSaved(false);
    try {
      await save.mutateAsync(form);
      // Secrets are write-only: clear the boxes so the masks show again.
      setForm({ ...form, consumer_key: "", consumer_secret: "", passkey: "" });
      setSaved(true);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const secret = (key: "consumer_key" | "consumer_secret" | "passkey", label: string) => (
    <Field label={label} hint={config[key] ? `Saved (${config[key]}) — leave blank to keep it` : "Not set yet"}>
      <Input type="password" autoComplete="new-password" value={form[key]} onChange={(e) => setForm({ ...form, [key]: e.target.value })} placeholder={config[key] ? "••••••••" : ""} />
    </Field>
  );

  return (
    <form onSubmit={submit} className="space-y-6">
      <Card className="space-y-5 p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-emerald-50 text-emerald-600"><Smartphone className="h-5 w-5" /></span>
            <div>
              <h2 className="text-sm font-semibold text-navy-900 dark:text-white">M-Pesa payment prompts</h2>
              <p className="mt-0.5 max-w-xl text-xs text-slate-500">
                Send an &quot;enter your PIN&quot; prompt to the customer&apos;s phone from the till or from an invoice. When they pay, the payment is recorded for you with the M-Pesa code.
              </p>
            </div>
          </div>
          {config.configured ? <Badge tone={config.is_active ? "success" : "neutral"}>{config.is_active ? "Switched on" : "Set up, switched off"}</Badge> : <Badge tone="warning">Not set up</Badge>}
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Field label="Mode" hint="Use Sandbox until Safaricom gives you live keys">
            <Select value={form.environment} onChange={(e) => setForm({ ...form, environment: e.target.value })}>
              <option value="sandbox">Sandbox (testing)</option>
              <option value="production">Live</option>
            </Select>
          </Field>
          <Field label="Paybill / short code"><Input value={form.shortcode} inputMode="numeric" onChange={(e) => setForm({ ...form, shortcode: e.target.value.trim() })} placeholder="e.g. 174379" /></Field>
          <Field label="Till number" hint="Only for Buy Goods tills"><Input value={form.till_number} inputMode="numeric" onChange={(e) => setForm({ ...form, till_number: e.target.value.trim() })} /></Field>
          {secret("consumer_key", "Consumer key")}
          {secret("consumer_secret", "Consumer secret")}
          {secret("passkey", "Passkey")}
        </div>

        <div className="rounded-xl bg-slate-50 p-4 text-xs text-slate-600 dark:bg-navy-900 dark:text-slate-300">
          <p className="font-medium text-navy-900 dark:text-white">Where these come from</p>
          <p className="mt-1">Create an app at developer.safaricom.co.ke (Lipa na M-Pesa Online) to get the consumer key and secret; Safaricom emails the passkey when your paybill goes live. They are stored encrypted and never shown again.</p>
          <p className="mt-2">Safaricom sends payment results to <span className="font-mono">{callback}</span></p>
          {localCallback && <p className="mt-1 text-amber-700">This address is only reachable on this computer. Prompts will be sent, but results can&apos;t come back until the system is on a public https address.</p>}
        </div>

        <div className="flex items-center gap-3">
          <Switch checked={form.is_active} onChange={(v) => setForm({ ...form, is_active: v })} label="Allow M-Pesa prompts" />
          <span className="text-sm">Allow staff to send M-Pesa prompts</span>
        </div>
      </Card>

      <ErrorBanner message={error} />
      {saved && !error && <p className="flex items-center gap-1.5 text-sm text-emerald-600"><CheckCircle2 className="h-4 w-4" /> Saved.</p>}
      <Button type="submit" disabled={save.isPending}>{save.isPending ? "Saving…" : "Save M-Pesa settings"}</Button>
    </form>
  );
}
