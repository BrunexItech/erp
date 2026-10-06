"use client";

import { useState } from "react";
import { Megaphone, Pencil, Plus } from "lucide-react";
import {
  Badge,
  Button,
  Card,
  Checkbox,
  EmptyState,
  ErrorBanner,
  Field,
  Input,
  Loading,
  Modal,
  Select,
  StatTile,
  Table,
  Td,
  Textarea,
  Th,
} from "@/components/om/primitives";
import { errorMessage, useApi, useApiMutation } from "@/lib/api/query";
import { fmtDate, fmtMoney, humanize, num } from "@/lib/format";

const REFRESH = [["admin"]];

export interface ModuleInfo { key: string; name: string; depends_on: string[] }
export interface PackageDetail {
  id: string; key: string; name: string; description: string; modules: string[]; limits: { max_users?: number | null; max_sku?: number | null };
  price_monthly: string; price_yearly: string; trial_days: number; is_default: boolean; is_active: boolean; sort_order: number;
}

// ---------------------------------------------------------------- packages

export function PackagesTab() {
  const { data: packages, isLoading } = useApi<PackageDetail[]>("/admin/packages/detail");
  const [editing, setEditing] = useState<PackageDetail | "new" | null>(null);
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-500">What you sell: which modules each plan includes, its limits and its price.</p>
        <Button onClick={() => setEditing("new")}><Plus /> New package</Button>
      </div>
      {isLoading ? <Loading /> : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {packages?.map((p) => (
            <Card key={p.id} className={`p-6 ${p.is_active ? "" : "opacity-60"}`}>
              <div className="flex items-start justify-between">
                <div>
                  <p className="text-lg font-semibold">{p.name}</p>
                  <p className="font-mono text-xs text-slate-400">{p.key}</p>
                </div>
                <div className="flex gap-1">
                  {p.is_default && <Badge tone="info">Default for sign-ups</Badge>}
                  {!p.is_active && <Badge>Inactive</Badge>}
                </div>
              </div>
              <p className="mt-3 text-3xl font-semibold tracking-tight">
                {num(p.price_monthly) ? fmtMoney(p.price_monthly) : "Free"}
                {num(p.price_monthly) > 0 && <span className="text-sm font-normal text-slate-500"> / month</span>}
              </p>
              {num(p.price_yearly) > 0 && <p className="text-xs text-slate-500">{fmtMoney(p.price_yearly)} / year · {p.trial_days}-day trial</p>}
              <p className="mt-3 text-sm text-slate-500">{p.description || "—"}</p>
              <p className="mt-3 text-xs text-slate-500">
                {p.limits.max_users == null ? "Unlimited users" : `${p.limits.max_users} users`} · {p.limits.max_sku == null ? "unlimited products" : `${p.limits.max_sku.toLocaleString()} products`}
              </p>
              <div className="mt-3 flex flex-wrap gap-1">
                {p.modules.includes("*") ? <Badge tone="success">All modules</Badge> : p.modules.map((m) => <Badge key={m}>{m}</Badge>)}
              </div>
              <Button variant="secondary" className="mt-4 w-full" onClick={() => setEditing(p)}><Pencil /> Edit</Button>
            </Card>
          ))}
        </div>
      )}
      {editing && <PackageForm pkg={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

function PackageForm({ pkg, onClose }: { pkg: PackageDetail | null; onClose: () => void }) {
  const { data: modules } = useApi<ModuleInfo[]>("/admin/modules");
  const save = useApiMutation<Record<string, unknown>>(pkg ? "patch" : "post", pkg ? `/admin/packages/${pkg.id}` : "/admin/packages", REFRESH);
  const [f, setF] = useState({
    key: pkg?.key ?? "", name: pkg?.name ?? "", description: pkg?.description ?? "",
    price_monthly: String(num(pkg?.price_monthly)), price_yearly: String(num(pkg?.price_yearly)), trial_days: String(pkg?.trial_days ?? 14),
    max_users: pkg?.limits.max_users == null ? "" : String(pkg.limits.max_users),
    max_sku: pkg?.limits.max_sku == null ? "" : String(pkg.limits.max_sku),
    is_default: pkg?.is_default ?? false, is_active: pkg?.is_active ?? true,
  });
  const [all, setAll] = useState(pkg ? pkg.modules.includes("*") : false);
  const [selected, setSelected] = useState<string[]>(pkg?.modules.filter((m) => m !== "*") ?? ["crm", "inventory", "sales", "accounting"]);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await save.mutateAsync({
        ...(pkg ? {} : { key: f.key }),
        name: f.name, description: f.description, modules: all ? ["*"] : selected,
        price_monthly: f.price_monthly || "0", price_yearly: f.price_yearly || "0", trial_days: Number(f.trial_days || 0),
        max_users: f.max_users ? Number(f.max_users) : null, unlimited_users: !f.max_users,
        max_sku: f.max_sku ? Number(f.max_sku) : null, unlimited_sku: !f.max_sku,
        ...(f.is_default && !pkg?.is_default ? { is_default: true } : {}),
        is_active: f.is_active,
      });
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <Modal open onClose={onClose} title={pkg ? `Edit ${pkg.name}` : "New package"} wide>
      <form onSubmit={submit} className="space-y-5">
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Name"><Input required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
          <Field label="Key" hint={pkg ? "Can't be changed" : "lowercase, no spaces"}><Input required disabled={!!pkg} value={f.key} onChange={(e) => setF({ ...f, key: e.target.value.toLowerCase() })} placeholder="pro" /></Field>
          <Field label="Free trial (days)"><Input type="number" min="0" max="365" value={f.trial_days} onChange={(e) => setF({ ...f, trial_days: e.target.value })} /></Field>
          <Field label="Price per month" hint="0 = free, never billed"><Input type="number" min="0" step="0.01" value={f.price_monthly} onChange={(e) => setF({ ...f, price_monthly: e.target.value })} /></Field>
          <Field label="Price per year" hint="0 = 12 × monthly"><Input type="number" min="0" step="0.01" value={f.price_yearly} onChange={(e) => setF({ ...f, price_yearly: e.target.value })} /></Field>
          <div />
          <Field label="Max users" hint="Blank = unlimited"><Input type="number" min="1" value={f.max_users} onChange={(e) => setF({ ...f, max_users: e.target.value })} /></Field>
          <Field label="Max products" hint="Blank = unlimited"><Input type="number" min="1" value={f.max_sku} onChange={(e) => setF({ ...f, max_sku: e.target.value })} /></Field>
        </div>
        <Field label="Description (shown to customers)"><Input value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
        <div>
          <p className="mb-2 text-xs font-medium text-slate-600">Modules included</p>
          <Checkbox label="Every module, including future ones" checked={all} onChange={setAll} />
          {!all && (
            <div className="mt-3 grid gap-2 sm:grid-cols-3">
              {modules?.map((m) => (
                <Checkbox key={m.key} label={m.name} checked={selected.includes(m.key)} onChange={(v) => setSelected(v ? [...selected, m.key] : selected.filter((k) => k !== m.key))} />
              ))}
            </div>
          )}
        </div>
        <div className="flex flex-wrap gap-6">
          <Checkbox label="Offer to new sign-ups (default)" checked={f.is_default} onChange={(v) => setF({ ...f, is_default: v })} />
          <Checkbox label="Active" checked={f.is_active} onChange={(v) => setF({ ...f, is_active: v })} />
        </div>
        <ErrorBanner message={error} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={save.isPending}>Save package</Button>
        </div>
      </form>
    </Modal>
  );
}

// ----------------------------------------------------------------- billing

interface AdminInvoice {
  id: string; number: string; workspace_name: string; package_name: string; cycle: string; period_start: string; period_end: string;
  amount: string; currency: string; status: string; due_date: string; paid_at: string | null; payment_method: string; payment_reference: string;
}

export function BillingTab() {
  const [filter, setFilter] = useState("open");
  const { data: summary } = useApi<{ mrr: number; states: Record<string, number>; open_invoices: number; open_amount: string }>("/admin/billing/summary");
  const { data: invoices, isLoading } = useApi<AdminInvoice[]>(`/admin/billing/invoices${filter ? `?status=${filter}` : ""}`);
  const [paying, setPaying] = useState<AdminInvoice | null>(null);
  const pay = useApiMutation<Record<string, string>>("post", `/admin/billing/invoices/${paying?.id}/pay`, REFRESH);
  const voidInvoice = useApiMutation<{ id: string }>("post", (b) => `/admin/billing/invoices/${b.id}/void`, REFRESH);
  const [method, setMethod] = useState("mpesa");
  const [reference, setReference] = useState("");
  const [error, setError] = useState<string | null>(null);
  const states = summary?.states ?? {};

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatTile label="Monthly recurring revenue" value={fmtMoney(summary?.mrr)} tone="emerald" />
        <StatTile label="Awaiting payment" value={fmtMoney(summary?.open_amount)} sub={`${summary?.open_invoices ?? 0} open invoice(s)`} tone="amber" />
        <StatTile label="On trial" value={String(states.trialing ?? 0)} tone="sky" />
        <StatTile label="Overdue or lapsed" value={String((states.past_due ?? 0) + (states.trial_ended ?? 0))} tone="rose" />
      </div>
      <div className="w-44">
        <Select value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="open">Awaiting payment</option><option value="paid">Paid</option><option value="void">Void</option><option value="">All invoices</option>
        </Select>
      </div>
      <ErrorBanner message={!paying ? error : null} />
      <Card>
        {isLoading ? <Loading /> : !invoices?.length ? (
          <div className="p-6"><EmptyState title="No invoices here" description="Renewal invoices are raised automatically a week before a trial or paid period ends." /></div>
        ) : (
          <Table>
            <thead><tr><Th>Invoice</Th><Th>Customer</Th><Th>Plan</Th><Th>Period</Th><Th>Due</Th><Th>Amount</Th><Th>Status</Th><Th></Th></tr></thead>
            <tbody>
              {invoices.map((i) => (
                <tr key={i.id}>
                  <Td className="font-medium">{i.number}</Td>
                  <Td>{i.workspace_name}</Td>
                  <Td className="text-slate-500">{i.package_name} · {i.cycle}</Td>
                  <Td>{fmtDate(i.period_start)} – {fmtDate(i.period_end)}</Td>
                  <Td>{fmtDate(i.due_date)}</Td>
                  <Td>{fmtMoney(i.amount, i.currency)}</Td>
                  <Td>
                    <Badge tone={i.status === "paid" ? "success" : i.status === "open" ? "warning" : "neutral"}>{humanize(i.status)}</Badge>
                    {i.payment_reference && <p className="mt-0.5 font-mono text-xs text-slate-400">{i.payment_reference}</p>}
                  </Td>
                  <Td>
                    {i.status === "open" && (
                      <div className="flex justify-end gap-1">
                        <Button className="px-2 py-1 text-xs" onClick={() => { setPaying(i); setReference(""); setError(null); }}>Record payment</Button>
                        <Button variant="ghost" className="px-2 py-1 text-xs" onClick={async () => { if (confirm(`Void ${i.number}?`)) { try { await voidInvoice.mutateAsync({ id: i.id }); } catch (err) { setError(errorMessage(err)); } } }}>Void</Button>
                      </div>
                    )}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <Modal open={!!paying} onClose={() => setPaying(null)} title={`Record payment — ${paying?.number ?? ""}`}>
        <form className="space-y-3" onSubmit={async (e) => {
          e.preventDefault();
          setError(null);
          try {
            await pay.mutateAsync({ method, reference });
            setPaying(null);
          } catch (err) {
            setError(errorMessage(err));
          }
        }}>
          <p className="text-sm text-slate-500">
            {paying?.workspace_name} paid <b>{fmtMoney(paying?.amount, paying?.currency)}</b>. Their access is restored (or extended) immediately.
          </p>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Method">
              <Select value={method} onChange={(e) => setMethod(e.target.value)}>
                <option value="mpesa">M-Pesa</option><option value="bank">Bank transfer</option><option value="cash">Cash</option><option value="cheque">Cheque</option>
              </Select>
            </Field>
            <Field label="Reference"><Input value={reference} onChange={(e) => setReference(e.target.value.toUpperCase())} placeholder="M-Pesa code" /></Field>
          </div>
          <ErrorBanner message={error} />
          <div className="flex justify-end"><Button type="submit" disabled={pay.isPending}>Confirm payment</Button></div>
        </form>
      </Modal>
    </div>
  );
}

// ----------------------------------------------------------- announcements

interface AdminAnnouncement { id: string; title: string; body: string; level: string; is_active: boolean; created_at: string }

export function AnnouncementsTab() {
  const { data: items, isLoading } = useApi<AdminAnnouncement[]>("/admin/announcements");
  const create = useApiMutation("post", "/admin/announcements", REFRESH);
  const update = useApiMutation<AdminAnnouncement>("patch", (a) => `/admin/announcements/${a.id}`, REFRESH);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [level, setLevel] = useState("info");
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card className="p-6">
        <h2 className="flex items-center gap-2 text-sm font-semibold"><Megaphone className="h-4 w-4 text-brand" /> New announcement</h2>
        <p className="mt-1 text-xs text-slate-500">Appears as a bar at the top of the app for every signed-in user until they dismiss it or you switch it off.</p>
        <form className="mt-4 space-y-3" onSubmit={async (e) => {
          e.preventDefault();
          setError(null);
          try {
            await create.mutateAsync({ title, body, level, is_active: true });
            setTitle("");
            setBody("");
          } catch (err) {
            setError(errorMessage(err));
          }
        }}>
          <Field label="Headline"><Input required value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Scheduled maintenance Sunday 2am–3am" /></Field>
          <Field label="Details (optional)"><Textarea value={body} onChange={(e) => setBody(e.target.value)} /></Field>
          <Field label="Style">
            <Select value={level} onChange={(e) => setLevel(e.target.value)}><option value="info">Information</option><option value="warning">Warning</option></Select>
          </Field>
          <ErrorBanner message={error} />
          <Button type="submit" disabled={create.isPending}>Publish</Button>
        </form>
      </Card>
      <Card>
        {isLoading ? <Loading /> : !items?.length ? <div className="p-6"><EmptyState title="No announcements yet" /></div> : (
          <ul className="divide-y divide-slate-100">
            {items.map((a) => (
              <li key={a.id} className="flex items-start gap-3 px-5 py-3">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">{a.title}</p>
                  {a.body && <p className="text-sm text-slate-500">{a.body}</p>}
                  <p className="mt-1 text-xs text-slate-400">{fmtDate(a.created_at)}</p>
                </div>
                <Badge tone={a.is_active ? "success" : "neutral"}>{a.is_active ? "Live" : "Off"}</Badge>
                <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => update.mutate({ ...a, is_active: !a.is_active })}>{a.is_active ? "Switch off" : "Switch on"}</Button>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

// ------------------------------------------------------------------- audit

const ACTION_LABEL: Record<string, string> = {
  "workspace.updated": "Changed a customer account", "workspace.created": "Created a customer account", "subscription.updated": "Changed a subscription",
  "payment.recorded": "Recorded a payment", "invoice.voided": "Voided an invoice", "support.impersonated": "Signed in as a customer",
  "support.reset_link": "Created a password-reset link", "package.saved": "Saved a package", "announcement.saved": "Saved an announcement", "settings.updated": "Changed platform settings",
};

export function AuditTab() {
  const { data: entries, isLoading } = useApi<{ id: string; at: string; actor: string; action: string; workspace: string; detail: Record<string, unknown> }[]>("/admin/audit-log");
  return (
    <Card>
      {isLoading ? <Loading /> : !entries?.length ? <div className="p-6"><EmptyState title="Nothing recorded yet" description="Every admin action on a customer account is logged here and can't be edited." /></div> : (
        <Table>
          <thead><tr><Th>When</Th><Th>Admin</Th><Th>Action</Th><Th>Customer</Th><Th>Details</Th></tr></thead>
          <tbody>
            {entries.map((e) => (
              <tr key={e.id}>
                <Td className="whitespace-nowrap text-xs">{new Date(`${e.at}Z`).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" })}</Td>
                <Td className="text-slate-500">{e.actor}</Td>
                <Td><Badge tone={e.action.startsWith("support") ? "warning" : "neutral"}>{ACTION_LABEL[e.action] ?? e.action}</Badge></Td>
                <Td>{e.workspace || "—"}</Td>
                <Td className="max-w-md truncate font-mono text-xs text-slate-500">{Object.entries(e.detail).map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : v}`).join("  ")}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- settings

type Platform = { product_name: string; support_email: string; support_phone: string; currency: string; mpesa_paybill: string; mpesa_till: string; bank_details: string; grace_days: number; invoice_lead_days: number };

export function PlatformSettingsTab() {
  const { data } = useApi<Platform>("/admin/settings");
  const save = useApiMutation<Platform>("put", "/admin/settings", REFRESH);
  const [form, setForm] = useState<Platform | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const f = form ?? data;
  if (!f) return <Loading />;
  const bind = (k: keyof Platform) => ({ value: String(f[k] ?? ""), onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setForm({ ...f, [k]: e.target.value }) });
  return (
    <Card className="max-w-3xl p-6">
      <form className="space-y-5" onSubmit={async (e) => {
        e.preventDefault();
        setError(null);
        setSaved(false);
        try {
          await save.mutateAsync({ ...f, grace_days: Number(f.grace_days), invoice_lead_days: Number(f.invoice_lead_days) });
          setSaved(true);
        } catch (err) {
          setError(errorMessage(err));
        }
      }}>
        <div>
          <h2 className="text-sm font-semibold text-brand">Your product</h2>
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            <Field label="Product name" hint="Shown in emails and authenticator apps"><Input {...bind("product_name")} /></Field>
            <Field label="Support email"><Input type="email" {...bind("support_email")} /></Field>
            <Field label="Support phone"><Input {...bind("support_phone")} /></Field>
          </div>
        </div>
        <div>
          <h2 className="text-sm font-semibold text-brand">How customers pay you</h2>
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            <Field label="M-Pesa Paybill"><Input {...bind("mpesa_paybill")} /></Field>
            <Field label="M-Pesa Till"><Input {...bind("mpesa_till")} /></Field>
            <Field label="Currency"><Input maxLength={3} {...bind("currency")} /></Field>
          </div>
          <div className="mt-3"><Field label="Bank details"><Textarea {...bind("bank_details")} /></Field></div>
        </div>
        <div>
          <h2 className="text-sm font-semibold text-brand">Billing rules</h2>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <Field label="Grace period (days)" hint="After a paid period ends, how long before the account pauses"><Input type="number" min="0" max="90" {...bind("grace_days")} /></Field>
            <Field label="Invoice lead time (days)" hint="How early the renewal invoice appears"><Input type="number" min="0" max="60" {...bind("invoice_lead_days")} /></Field>
          </div>
        </div>
        <ErrorBanner message={error} />
        {saved && <p className="text-sm text-emerald-600">Saved.</p>}
        <Button type="submit" disabled={save.isPending}>Save settings</Button>
      </form>
    </Card>
  );
}
