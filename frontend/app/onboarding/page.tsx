"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowRight, Check } from "lucide-react";
import { DesignPicker } from "@/components/branding/DesignPicker";
import { LogoUploader } from "@/components/branding/LogoUploader";
import { Button, ErrorBanner, Field, Input, Textarea } from "@/components/om/primitives";
import { useBranding, useUpdateBranding } from "@/lib/api/hooks";
import { errorMessage } from "@/lib/api/query";
import { session } from "@/lib/session";
import type { Branding } from "@/lib/api/types";

const STEPS = ["Your business", "Logo & design", "Getting paid"];

/** First-run setup: a newly registered business makes the system its own
 * (name, KRA PIN, logo, colour, invoice design, payment details) in about a
 * minute. Everything here can be changed later under Settings. */
export default function OnboardingPage() {
  const router = useRouter();
  const { data: branding } = useBranding();
  const update = useUpdateBranding();
  const [step, setStep] = useState(0);
  const [form, setForm] = useState<Branding | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!session.isAuthenticated()) router.replace("/login");
  }, [router]);

  useEffect(() => {
    if (branding && !form) setForm(branding);
  }, [branding, form]);

  if (!form) return <div className="flex min-h-screen items-center justify-center text-sm text-slate-400">Loading…</div>;

  const bind = (key: keyof Branding) => ({
    value: String(form[key] ?? ""),
    onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setForm({ ...form, [key]: e.target.value }),
  });

  async function next() {
    if (!form) return;
    setError(null);
    try {
      // Save each step so the preview (and anything they skip to) is current.
      const { logo_url: _logo, ...rest } = form;
      void _logo; // the logo is saved by its own upload
      await update.mutateAsync(rest);
      if (step < STEPS.length - 1) setStep(step + 1);
      else router.push("/dashboard");
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <div className="min-h-screen bg-slate-50 px-4 py-10">
      <div className="mx-auto max-w-4xl">
        <p className="text-sm font-medium text-brand">Welcome</p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight text-navy-900">Let&apos;s set up {form.name || "your business"}</h1>
        <p className="mt-2 text-sm text-slate-500">A minute now, and every invoice, receipt and payslip carries your name and logo.</p>

        <ol className="mt-8 flex items-center gap-3">
          {STEPS.map((label, i) => (
            <li key={label} className="flex flex-1 items-center gap-3">
              <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm font-semibold ${
                i < step ? "bg-brand text-white" : i === step ? "bg-brand-50 text-brand ring-2 ring-brand" : "bg-white text-slate-400 ring-1 ring-slate-200"
              }`}>
                {i < step ? <Check className="h-4 w-4" /> : i + 1}
              </span>
              <span className={`hidden text-sm sm:inline ${i === step ? "font-medium text-navy-900" : "text-slate-500"}`}>{label}</span>
              {i < STEPS.length - 1 && <span className="h-px flex-1 bg-slate-200" />}
            </li>
          ))}
        </ol>

        <div className="mt-6 rounded-2xl border border-slate-200/80 bg-white p-6 shadow-card sm:p-8">
          {step === 0 && (
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Business name"><Input required {...bind("name")} /></Field>
              <Field label="KRA PIN" hint="Printed on tax invoices"><Input {...bind("tax_pin")} placeholder="P051234567X" /></Field>
              <Field label="Address"><Input {...bind("address")} placeholder="Street, town" /></Field>
              <Field label="Phone"><Input {...bind("phone")} placeholder="+254 7…" /></Field>
              <Field label="Email for invoices"><Input type="email" {...bind("billing_email")} /></Field>
              <Field label="Website (optional)"><Input {...bind("website")} /></Field>
            </div>
          )}

          {step === 1 && (
            <div className="space-y-6">
              {/* Functional update: the upload finishes later, and must not overwrite
                  a colour or design picked while it was in flight. */}
              <LogoUploader logoUrl={form.logo_url} onChange={(b) => setForm((f) => (f ? { ...f, logo_url: b.logo_url } : f))} />
              <div className="max-w-xs">
                <Field label="Brand colour">
                  <div className="flex items-center gap-2">
                    <input type="color" value={form.brand_color || "#1a7a8c"} onChange={(e) => setForm({ ...form, brand_color: e.target.value })} className="h-10 w-12 cursor-pointer rounded border border-slate-300" />
                    <Input {...bind("brand_color")} />
                  </div>
                </Field>
              </div>
              <div>
                <p className="mb-3 text-sm font-medium text-navy-900">Choose your invoice design</p>
                <DesignPicker
                  value={form.invoice_template}
                  color={form.brand_color}
                  refreshKey={String(form.logo_url)}
                  onChange={(invoice_template) => setForm({ ...form, invoice_template })}
                />
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="M-Pesa Paybill" hint="Customers use the invoice number as the account"><Input {...bind("mpesa_paybill")} /></Field>
              <Field label="M-Pesa Till (Buy Goods)"><Input {...bind("mpesa_till")} /></Field>
              <div className="sm:col-span-2">
                <Field label="Bank details"><Textarea placeholder={"Bank name, branch\nAccount name\nAccount number"} {...bind("bank_details")} /></Field>
              </div>
              <div className="sm:col-span-2">
                <Field label="Invoice terms (optional)"><Textarea placeholder="e.g. Payment due within 30 days." {...bind("invoice_terms")} /></Field>
              </div>
            </div>
          )}

          <div className="mt-6"><ErrorBanner message={error} /></div>
          <div className="mt-6 flex items-center justify-between">
            <button type="button" onClick={() => (step === 0 ? router.push("/dashboard") : setStep(step - 1))} className="text-sm text-slate-500 hover:text-navy-900">
              {step === 0 ? "Skip for now" : "Back"}
            </button>
            <Button onClick={next} disabled={update.isPending || !form.name.trim()}>
              {step === STEPS.length - 1 ? "Finish setup" : "Continue"} <ArrowRight />
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
