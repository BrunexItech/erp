"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, Building2, CheckCircle2, Copy, KeyRound, LogIn, PauseCircle, Plus, Search, ShieldCheck, Users } from "lucide-react";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  Field,
  Input,
  Loading,
  Modal,
  Select,
  StatTile,
  Switch,
  Table,
  Tabs,
  Td,
  Th,
} from "@/components/om/primitives";
import { AnnouncementsTab, AuditTab, BillingTab, ModuleInfo, PackageDetail, PackagesTab, PlatformSettingsTab } from "@/components/admin/AdminTabs";
import { errorMessage, useApi, useApiMutation } from "@/lib/api/query";
import { fmtDate, fmtMoney, humanize } from "@/lib/format";
import { session } from "@/lib/session";

interface AdminWorkspace {
  id: string;
  name: string;
  is_active: boolean;
  created_at: string;
  package_id: string;
  package_name: string;
  package_modules: string[];
  module_overrides: Record<string, boolean>;
  effective_modules: string[];
  owner_email: string | null;
  member_count: number;
}
interface Overview { workspaces: number; active_workspaces: number; users: number; by_package: Record<string, number> }
interface Detail {
  subscription: { status: string; cycle: string; trial_ends_at: string | null; current_period_end: string | null; notes: string };
  access: { level: string; state: string; days_left: number | null; message: string };
  members: { id: string; user_id: string; email: string; full_name: string; role: string }[];
  usage: { products: number; invoices: number; employees: number; members: number; last_invoice_at: string | null };
  invoices: { id: string; number: string; amount: string; status: string; due_date: string }[];
}

type Tab = "customers" | "packages" | "billing" | "announcements" | "audit" | "settings";
const REFRESH = [["admin"]];
const ACCESS_TONE: Record<string, "success" | "warning" | "danger" | "info"> = { ok: "success", grace: "warning", locked: "danger" };

export default function AdminConsole() {
  const router = useRouter();
  const { data: user, isLoading: userLoading } = useApi<{ is_platform_admin: boolean; email: string; totp_enabled: boolean }>("/auth/user");
  const [tab, setTab] = useState<Tab>("customers");
  const isAdmin = !!user?.is_platform_admin;

  useEffect(() => {
    if (!session.isAuthenticated()) router.replace("/login");
  }, [router]);

  if (userLoading) return <Loading />;
  if (!isAdmin) {
    return (
      <div className="flex min-h-screen items-center justify-center p-6">
        <EmptyState title="Platform admins only" description="This console manages every customer workspace. Ask the platform owner for access." icon={<ShieldCheck />} action={<Link href="/dashboard" className="text-sm text-brand">Back to dashboard</Link>} />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="bg-navy-900 text-white">
        <div className="mx-auto flex max-w-7xl items-center gap-4 px-6 py-4">
          <Link href="/dashboard" className="rounded-lg p-2 text-slate-400 hover:bg-white/10 hover:text-white" title="Back to my workspace">
            <ArrowLeft className="h-5 w-5" />
          </Link>
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-amber-500/20 text-amber-300"><ShieldCheck className="h-5 w-5" /></span>
          <div>
            <p className="font-semibold">Platform admin console</p>
            <p className="text-xs text-slate-400">{user?.email}</p>
          </div>
        </div>
      </header>

      {!user?.totp_enabled && (
        <div className="bg-amber-100 px-6 py-2 text-center text-sm text-amber-900">
          This account controls every customer&apos;s data. <Link href="/dashboard/settings?tab=security" className="font-medium underline">Turn on two-step sign-in</Link> to protect it.
        </div>
      )}

      <main className="mx-auto max-w-7xl space-y-6 px-6 py-8">
        <Tabs<Tab>
          value={tab}
          onChange={setTab}
          tabs={[
            { key: "customers", label: "Customers" },
            { key: "packages", label: "Packages" },
            { key: "billing", label: "Billing" },
            { key: "announcements", label: "Announcements" },
            { key: "audit", label: "Audit log" },
            { key: "settings", label: "Platform settings" },
          ]}
        />
        {tab === "customers" && <CustomersTab />}
        {tab === "packages" && <PackagesTab />}
        {tab === "billing" && <BillingTab />}
        {tab === "announcements" && <AnnouncementsTab />}
        {tab === "audit" && <AuditTab />}
        {tab === "settings" && <PlatformSettingsTab />}
      </main>
    </div>
  );
}

function CustomersTab() {
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const { data: overview } = useApi<Overview>("/admin/overview");
  const { data: workspaces, isLoading } = useApi<AdminWorkspace[]>(`/admin/workspaces${query ? `?search=${encodeURIComponent(query)}` : ""}`);

  useEffect(() => {
    const t = setTimeout(() => setQuery(search.trim()), 300);
    return () => clearTimeout(t);
  }, [search]);

  const open = workspaces?.find((w) => w.id === openId) ?? null;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <StatTile label="Customer workspaces" icon={<Building2 />} value={String(overview?.workspaces ?? "—")} sub={overview ? Object.entries(overview.by_package).map(([k, v]) => `${v} ${k}`).join(" · ") : undefined} />
        <StatTile label="Active" icon={<CheckCircle2 />} tone="emerald" value={String(overview?.active_workspaces ?? "—")} sub={overview ? `${overview.workspaces - overview.active_workspaces} suspended` : undefined} />
        <StatTile label="Users" icon={<Users />} tone="sky" value={String(overview?.users ?? "—")} />
      </div>

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 p-4">
          <div className="relative w-full sm:w-80">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search company or owner email…"
              className="w-full rounded-lg border border-slate-200 py-2 pl-9 pr-3 text-sm focus:border-brand focus:outline-none focus:ring-4 focus:ring-brand/10"
            />
          </div>
          <Button onClick={() => setCreating(true)}><Plus /> New customer</Button>
        </div>
        {isLoading ? <Loading /> : !workspaces?.length ? (
          <div className="p-6"><EmptyState title="No workspaces found" /></div>
        ) : (
          <Table>
            <thead><tr><Th>Company</Th><Th>Owner</Th><Th>Package</Th><Th>Modules</Th><Th>Users</Th><Th>Since</Th><Th>Status</Th></tr></thead>
            <tbody>
              {workspaces.map((w) => (
                <tr key={w.id} onClick={() => setOpenId(w.id)} className="cursor-pointer hover:bg-slate-50">
                  <Td className="font-medium">{w.name}</Td>
                  <Td className="text-slate-500">{w.owner_email ?? <span className="text-amber-600">Invitation pending</span>}</Td>
                  <Td>{w.package_name}</Td>
                  <Td>
                    {w.effective_modules.length} enabled
                    {Object.keys(w.module_overrides).length > 0 && <span className="ml-2 text-xs text-amber-600">customised</span>}
                  </Td>
                  <Td>{w.member_count}</Td>
                  <Td>{fmtDate(w.created_at)}</Td>
                  <Td><Badge tone={w.is_active ? "success" : "danger"}>{w.is_active ? "Active" : "Suspended"}</Badge></Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      {open && <WorkspaceEditor workspace={open} onClose={() => setOpenId(null)} />}
      {creating && <NewCustomer onClose={() => setCreating(false)} />}
    </div>
  );
}

function NewCustomer({ onClose }: { onClose: () => void }) {
  const { data: packages } = useApi<PackageDetail[]>("/admin/packages/detail");
  const create = useApiMutation<Record<string, string>, { invite_link: string; email_delivered: boolean }>("post", "/admin/workspaces", REFRESH);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [packageId, setPackageId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ invite_link: string; email_delivered: boolean } | null>(null);
  const chosen = packageId || packages?.find((p) => p.is_default)?.id || "";

  return (
    <Modal open onClose={onClose} title="New customer">
      {result ? (
        <div className="space-y-3">
          <p className="rounded-lg bg-emerald-50 px-3 py-2.5 text-sm text-emerald-800">
            {name} is set up. {result.email_delivered ? `An invitation was emailed to ${email}.` : `Email isn't configured yet — send ${email} this link:`}
          </p>
          <div className="flex gap-2">
            <input readOnly value={result.invite_link} onFocus={(e) => e.target.select()} className="min-w-0 flex-1 rounded-lg border border-slate-200 px-3 py-1.5 font-mono text-xs" />
            <Button variant="secondary" className="px-3 py-1.5 text-xs" onClick={() => navigator.clipboard.writeText(result.invite_link)}><Copy /> Copy</Button>
          </div>
          <p className="text-xs text-slate-500">They choose their own password when they accept, and become the owner.</p>
          <div className="flex justify-end"><Button onClick={onClose}>Done</Button></div>
        </div>
      ) : (
        <form className="space-y-3" onSubmit={async (e) => {
          e.preventDefault();
          setError(null);
          try {
            setResult(await create.mutateAsync({ name, owner_email: email, package_id: chosen }));
          } catch (err) {
            setError(errorMessage(err));
          }
        }}>
          <Field label="Business name"><Input required autoFocus value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <Field label="Owner's email" hint="They receive an invitation to set their password"><Input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
          <Field label="Package">
            <Select required value={chosen} onChange={(e) => setPackageId(e.target.value)}>
              {packages?.filter((p) => p.is_active).map((p) => <option key={p.id} value={p.id}>{p.name} — {Number(p.price_monthly) ? `${fmtMoney(p.price_monthly)}/mo` : "free"}</option>)}
            </Select>
          </Field>
          <ErrorBanner message={error} />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={create.isPending || !chosen}>Create & invite</Button>
          </div>
        </form>
      )}
    </Modal>
  );
}

function WorkspaceEditor({ workspace, onClose }: { workspace: AdminWorkspace; onClose: () => void }) {
  const { data: modules } = useApi<ModuleInfo[]>("/admin/modules");
  const { data: packages } = useApi<PackageDetail[]>("/admin/packages/detail");
  const { data: detail } = useApi<Detail>(`/admin/workspaces/${workspace.id}/detail`);
  const update = useApiMutation<Record<string, unknown>>("patch", `/admin/workspaces/${workspace.id}`, REFRESH);
  const updateSub = useApiMutation<Record<string, unknown>>("patch", `/admin/workspaces/${workspace.id}/subscription`, REFRESH);
  const impersonate = useApiMutation<undefined, { access_token: string; workspace_id: string; as_user: string; workspace_name: string }>("post", `/admin/workspaces/${workspace.id}/impersonate`, REFRESH);
  const resetLink = useApiMutation<{ user_id: string }, { link: string }>("post", (b) => `/admin/workspaces/${workspace.id}/members/${b.user_id}/reset-link`, REFRESH);
  const [section, setSection] = useState<"plan" | "modules" | "support">("plan");
  const [error, setError] = useState<string | null>(null);
  const [link, setLink] = useState<string | null>(null);
  const [trialEnd, setTrialEnd] = useState<string | null>(null);
  const [periodEnd, setPeriodEnd] = useState<string | null>(null);
  const enabled = useMemo(() => new Set(workspace.effective_modules), [workspace.effective_modules]);
  const names = useMemo(() => new Map((modules ?? []).map((m) => [m.key, m.name])), [modules]);
  const inPackage = (key: string) => workspace.package_modules.includes("*") || workspace.package_modules.includes(key);

  async function run(fn: () => Promise<unknown>) {
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const sub = detail?.subscription;

  return (
    <Modal open onClose={onClose} title={workspace.name} wide>
      <div className="space-y-5">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {([
            ["Team members", detail?.usage.members], ["Products", detail?.usage.products],
            ["Invoices raised", detail?.usage.invoices], ["Employees", detail?.usage.employees],
          ] as [string, number | undefined][]).map(([k, v]) => (
            <div key={k} className="rounded-xl bg-slate-50 p-3"><p className="text-xs text-slate-500">{k}</p><p className="mt-0.5 text-lg font-semibold">{v ?? "—"}</p></div>
          ))}
        </div>
        <p className="text-xs text-slate-500">
          Last invoice: {detail?.usage.last_invoice_at ? fmtDate(detail.usage.last_invoice_at) : "none yet"} · Customer since {fmtDate(workspace.created_at)}
        </p>

        <Tabs
          value={section}
          onChange={setSection}
          tabs={[{ key: "plan", label: "Plan & billing" }, { key: "modules", label: "Modules" }, { key: "support", label: "Support" }]}
        />
        <ErrorBanner message={error} />

        {section === "plan" && (
          <div className="space-y-5">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Package">
                <Select value={workspace.package_id} onChange={(e) => run(() => update.mutateAsync({ package_id: e.target.value }))} disabled={update.isPending}>
                  {packages?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                </Select>
              </Field>
              <div>
                <p className="mb-1.5 text-xs font-medium text-slate-600">Account</p>
                <div className="flex items-center gap-3 rounded-lg border border-slate-200 px-3 py-2">
                  {workspace.is_active ? <CheckCircle2 className="h-4 w-4 text-emerald-600" /> : <PauseCircle className="h-4 w-4 text-red-600" />}
                  <span className="flex-1 text-sm">{workspace.is_active ? "Active" : "Suspended — all access blocked"}</span>
                  <Button variant={workspace.is_active ? "danger" : "primary"} className="px-3 py-1.5 text-xs" onClick={() => run(() => update.mutateAsync({ is_active: !workspace.is_active }))} disabled={update.isPending}>
                    {workspace.is_active ? "Suspend" : "Reactivate"}
                  </Button>
                </div>
              </div>
            </div>

            {sub && detail && (
              <div className="rounded-xl border border-slate-200 p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm font-semibold">Subscription</p>
                  <div className="flex gap-2">
                    <Badge tone={ACCESS_TONE[detail.access.level] ?? "info"}>{humanize(detail.access.state)}</Badge>
                    {detail.access.days_left !== null && <span className="text-xs text-slate-500">{detail.access.days_left} day(s) left</span>}
                  </div>
                </div>
                <div className="mt-3 grid gap-3 sm:grid-cols-4">
                  <Field label="Status">
                    <Select value={sub.status} onChange={(e) => run(() => updateSub.mutateAsync({ status: e.target.value }))}>
                      <option value="trialing">Free trial</option><option value="active">Active (paying)</option>
                      <option value="complimentary">Complimentary (never billed)</option><option value="cancelled">Cancelled</option>
                    </Select>
                  </Field>
                  <Field label="Billed">
                    <Select value={sub.cycle} onChange={(e) => run(() => updateSub.mutateAsync({ cycle: e.target.value }))}>
                      <option value="monthly">Monthly</option><option value="yearly">Yearly</option>
                    </Select>
                  </Field>
                  <Field label="Trial ends">
                    <Input type="date" value={trialEnd ?? sub.trial_ends_at ?? ""} onChange={(e) => setTrialEnd(e.target.value)} onBlur={() => trialEnd && run(() => updateSub.mutateAsync({ trial_ends_at: trialEnd }))} />
                  </Field>
                  <Field label="Paid until">
                    <Input type="date" value={periodEnd ?? sub.current_period_end ?? ""} onChange={(e) => setPeriodEnd(e.target.value)} onBlur={() => periodEnd && run(() => updateSub.mutateAsync({ current_period_end: periodEnd }))} />
                  </Field>
                </div>
                <p className="mt-2 text-xs text-slate-500">Dates save when you leave the field. To take a payment, use the Billing tab — it extends &quot;paid until&quot; for you.</p>
                {detail.invoices.length > 0 && (
                  <ul className="mt-3 divide-y divide-slate-100 text-sm">
                    {detail.invoices.slice(0, 4).map((i) => (
                      <li key={i.id} className="flex items-center justify-between py-1.5">
                        <span>{i.number} · due {fmtDate(i.due_date)}</span>
                        <span className="flex items-center gap-2">{fmtMoney(i.amount)} <Badge tone={i.status === "paid" ? "success" : i.status === "open" ? "warning" : "neutral"}>{i.status}</Badge></span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>
        )}

        {section === "modules" && (
          <div>
            <div className="mb-2 flex items-center justify-between">
              <p className="text-xs text-slate-500">
                Switching a module off hides it and blocks it for everyone in this workspace. Nothing is deleted — switching it back on restores all data. Modules that depend on it go off too.
              </p>
              {Object.keys(workspace.module_overrides).length > 0 && (
                <button className="ml-4 whitespace-nowrap text-xs text-brand hover:underline" onClick={() => run(() => update.mutateAsync({ module_overrides: Object.fromEntries(Object.keys(workspace.module_overrides).map((k) => [k, null])) }))}>
                  Reset to package defaults
                </button>
              )}
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              {modules?.map((m) => {
                const on = enabled.has(m.key);
                const override = workspace.module_overrides[m.key];
                const blockedBy = m.depends_on.filter((d) => workspace.module_overrides[d] === false);
                return (
                  <div key={m.key} className={`flex items-center gap-3 rounded-xl border border-slate-200 px-4 py-3 ${on ? "" : "bg-slate-50"}`}>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium">{m.name}</p>
                      <p className="text-xs text-slate-500">
                        {override === undefined ? (inPackage(m.key) ? "From package" : "Not in package") : override ? "Enabled by you" : "Disabled by you"}
                        {m.depends_on.length > 0 && ` · needs ${m.depends_on.map((d) => names.get(d) ?? d).join(", ")}`}
                      </p>
                      {blockedBy.length > 0 && <p className="text-xs text-amber-600">Off because {blockedBy.map((d) => names.get(d) ?? d).join(", ")} is off</p>}
                    </div>
                    <Switch checked={on} label={`Toggle ${m.name}`} disabled={update.isPending || blockedBy.length > 0} onChange={(value) => run(() => update.mutateAsync({ module_overrides: { [m.key]: value === inPackage(m.key) ? null : value } }))} />
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {section === "support" && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4">
              <div className="text-sm text-amber-900">
                <p className="font-semibold">Sign in as this customer</p>
                <p>Opens their account as the owner for 30 minutes so you can see what they see. It is recorded in the audit log.</p>
              </div>
              <Button
                disabled={impersonate.isPending}
                onClick={() => run(async () => {
                  const r = await impersonate.mutateAsync(undefined);
                  session.startImpersonating(r.access_token, r.workspace_id, `${r.as_user} (${r.workspace_name})`);
                  window.location.href = "/dashboard";
                })}
              >
                <LogIn /> Sign in as owner
              </Button>
            </div>
            <div>
              <p className="mb-2 text-sm font-semibold">Team</p>
              <div className="overflow-hidden rounded-xl border border-slate-200">
                <Table>
                  <tbody>
                    {detail?.members.map((m) => (
                      <tr key={m.id}>
                        <Td className="font-medium">{m.full_name || "—"}</Td>
                        <Td className="text-slate-500">{m.email}</Td>
                        <Td><Badge>{humanize(m.role)}</Badge></Td>
                        <Td>
                          <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => run(async () => setLink((await resetLink.mutateAsync({ user_id: m.user_id })).link))}>
                            <KeyRound /> Password reset link
                          </Button>
                        </Td>
                      </tr>
                    ))}
                    {detail && !detail.members.length && <tr><Td className="text-slate-400">No members yet — the owner hasn&apos;t accepted their invitation.</Td></tr>}
                  </tbody>
                </Table>
              </div>
            </div>
            {link && (
              <div className="rounded-xl bg-emerald-50 p-4 text-sm text-emerald-900">
                <p className="font-medium">Send this link to the user. It works once and expires in 2 hours.</p>
                <div className="mt-2 flex gap-2">
                  <input readOnly value={link} onFocus={(e) => e.target.select()} className="min-w-0 flex-1 rounded-lg border border-emerald-200 bg-white px-3 py-1.5 font-mono text-xs" />
                  <Button variant="secondary" className="px-3 py-1.5 text-xs" onClick={() => navigator.clipboard.writeText(link)}><Copy /> Copy</Button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </Modal>
  );
}
