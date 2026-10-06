"use client";

import { useEffect, useState } from "react";
import { useBranding, useMe, useUpdateBranding } from "@/lib/api/hooks";
import { Button, Card, ErrorBanner, Field, Input, PageHeader, Select, Tabs, Textarea } from "@/components/om/primitives";
import { SecurityTab } from "@/components/settings/SecurityTab";
import { TeamTab } from "@/components/settings/TeamTab";
import { errorMessage } from "@/lib/api/query";
import { ActivityTab } from "@/components/accounting/TaxAndYearEnd";
import { BillingPanel } from "@/components/billing/BillingPanel";
import { DesignPicker } from "@/components/branding/DesignPicker";
import { LogoUploader } from "@/components/branding/LogoUploader";
import type { Branding } from "@/lib/api/types";

type Form = Omit<Branding, "logo_url"> & { logo_url: string };

type Tab = "company" | "team" | "billing" | "activity" | "security";

export default function SettingsPage() {
  const { data: me } = useMe();
  const isAdmin = !!me?.permissions.includes("*");
  const [tab, setTab] = useState<Tab | null>(null);
  // Deep link from the "Pay now" banner: /dashboard/settings?tab=billing
  useEffect(() => {
    const wanted = new URLSearchParams(window.location.search).get("tab");
    if (wanted === "billing" || wanted === "team" || wanted === "security" || wanted === "activity") setTab(wanted);
  }, []);
  const active: Tab = tab ?? (isAdmin ? "company" : "security");
  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <PageHeader title="Settings" description="Your company profile, your team, and your own sign-in." />
      <Tabs<Tab>
        value={active}
        onChange={setTab}
        tabs={[
          ...(isAdmin ? [{ key: "company" as Tab, label: "Company & documents" }] : []),
          { key: "team" as Tab, label: "Team" },
          ...(isAdmin ? [{ key: "billing" as Tab, label: "Plan & billing" }, { key: "activity" as Tab, label: "Activity log" }] : []),
          { key: "security" as Tab, label: "Security" },
        ]}
      />
      {active === "company" && <CompanyTab />}
      {active === "team" && <TeamTab />}
      {active === "billing" && <BillingPanel />}
      {active === "activity" && <ActivityTab />}
      {active === "security" && <SecurityTab />}
    </div>
  );
}

function CompanyTab() {
  const { data: branding, isLoading } = useBranding();
  const updateBranding = useUpdateBranding();
  const [form, setForm] = useState<Form | null>(null);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Initialise once — a logo upload refreshes `branding`, and must not wipe
    // edits the user hasn't saved yet.
    if (branding) setForm((current) => current ?? { ...branding, logo_url: branding.logo_url ?? "" });
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
                default_payment_terms_days: Number(form.default_payment_terms_days) || 0,
      });
      setSaved(true);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <div className="space-y-6">
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
          <LogoUploader logoUrl={form.logo_url || null} onChange={(b) => setForm((f) => (f ? { ...f, logo_url: b.logo_url ?? "" } : f))} />
          <div className="max-w-xs">
            <Field label="Brand colour" hint="The accent colour on all your documents">
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
          <div>
            <h2 className="text-sm font-semibold text-brand">Document design</h2>
            <p className="mt-1 text-xs text-slate-500">
              Applies to invoices, quotes, credit notes, receipts, statements and payslips. The preview uses your saved company details with sample figures.
            </p>
          </div>
          <DesignPicker
            value={form.invoice_template}
            color={form.brand_color}
            refreshKey={`${form.logo_url}|${branding?.name}|${branding?.tax_pin}`}
            onChange={(invoice_template) => setForm({ ...form, invoice_template })}
          />
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
          <Field label="KRA eTIMS" hint="Live submission needs your KRA eTIMS device credentials to be connected first. Test mode prints a clearly-marked test code so you can see the workflow.">
            <Select {...bind("etims_mode")}>
              <option value="off">Off — invoices are not sent to KRA</option>
              <option value="test">Test mode (not fiscal)</option>
              <option value="live">Live</option>
            </Select>
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
