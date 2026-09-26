"use client";

import { useEffect, useState } from "react";
import { useBranding, useUpdateBranding } from "@/lib/api/hooks";
import { Button, Card, ErrorBanner, Field, Input, PageHeader, Select, Textarea } from "@/components/om/primitives";
import { errorMessage } from "@/lib/api/query";
import type { Branding } from "@/lib/api/types";

type Form = Omit<Branding, "logo_url"> & { logo_url: string };

export default function SettingsPage() {
  const { data: branding, isLoading } = useBranding();
  const updateBranding = useUpdateBranding();
  const [form, setForm] = useState<Form | null>(null);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (branding) setForm({ ...branding, logo_url: branding.logo_url ?? "" });
  }, [branding]);

  if (isLoading || !form) return <p className="text-sm text-slate-400">Loading…</p>;

  const bind = (key: keyof Form) => ({
    value: String(form[key] ?? ""),
    onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
      setForm({ ...form, [key]: e.target.value }),
  });

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form) return;
    setError(null);
    setSaved(false);
    try {
      await updateBranding.mutateAsync({
        ...form,
        logo_url: form.logo_url || null,
        default_payment_terms_days: Number(form.default_payment_terms_days) || 0,
      });
      setSaved(true);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <PageHeader title="Company settings" description="Your letterhead, tax details and payment instructions — printed on every invoice, quote, statement, receipt and payslip." />
      <form onSubmit={onSubmit} className="space-y-6">
        <Card className="space-y-4 p-6">
          <h2 className="text-sm font-semibold text-brand">Company</h2>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Company name"><Input required {...bind("name")} /></Field>
            <Field label="KRA PIN"><Input {...bind("tax_pin")} placeholder="P051234567X" /></Field>
            <Field label="Address"><Input {...bind("address")} /></Field>
            <Field label="Phone"><Input {...bind("phone")} /></Field>
            <Field label="Billing email"><Input type="email" {...bind("billing_email")} /></Field>
            <Field label="Website"><Input {...bind("website")} /></Field>
          </div>
        </Card>

        <Card className="space-y-4 p-6">
          <h2 className="text-sm font-semibold text-brand">Branding</h2>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div className="sm:col-span-2">
              <Field label="Logo URL" hint="PNG or JPG, shown top-left on documents">
                <Input type="url" placeholder="https://…" {...bind("logo_url")} />
              </Field>
              {form.logo_url && (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={form.logo_url} alt="Logo preview" className="mt-2 h-12 object-contain" />
              )}
            </div>
            <Field label="Brand colour">
              <div className="flex items-center gap-2">
                <input
                  type="color"
                  value={form.brand_color || "#1a7a8c"}
                  onChange={(e) => setForm({ ...form, brand_color: e.target.value })}
                  className="h-10 w-12 cursor-pointer rounded border border-slate-300"
                />
                <Input {...bind("brand_color")} />
              </div>
            </Field>
          </div>
        </Card>

        <Card className="space-y-4 p-6">
          <h2 className="text-sm font-semibold text-brand">Invoicing & payments</h2>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <Field label="Currency">
              <Select {...bind("currency")}>
                {["KES", "UGX", "TZS", "RWF", "USD", "EUR", "GBP"].map((c) => <option key={c} value={c}>{c}</option>)}
              </Select>
            </Field>
            <Field label="Default payment terms (days)"><Input type="number" min="0" max="365" {...bind("default_payment_terms_days")} /></Field>
            <div />
            <Field label="M-Pesa Paybill" hint="Invoice number is printed as the account"><Input {...bind("mpesa_paybill")} /></Field>
            <Field label="M-Pesa Till (Buy Goods)"><Input {...bind("mpesa_till")} /></Field>
          </div>
          <Field label="Bank details">
            <Textarea placeholder={"Bank name, branch\nAccount name\nAccount number"} {...bind("bank_details")} />
          </Field>
          <Field label="Default invoice terms & conditions">
            <Textarea {...bind("invoice_terms")} />
          </Field>
          <Field label="Document footer note"><Input placeholder="e.g. Thank you for your business!" {...bind("invoice_footer_note")} /></Field>
        </Card>

        <ErrorBanner message={error} />
        {saved && !error && <p className="text-sm text-emerald-600">Saved — new documents will use these details.</p>}
        <Button type="submit" disabled={updateBranding.isPending}>
          {updateBranding.isPending ? "Saving…" : "Save settings"}
        </Button>
      </form>
    </div>
  );
}
