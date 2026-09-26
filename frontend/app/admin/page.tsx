"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, Building2, CheckCircle2, PauseCircle, Search, ShieldCheck, Users } from "lucide-react";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  Loading,
  Modal,
  Select,
  StatTile,
  Switch,
  Table,
  Td,
  Th,
} from "@/components/om/primitives";
import { errorMessage, useApi, useApiMutation } from "@/lib/api/query";
import { fmtDate } from "@/lib/format";
import { session } from "@/lib/session";

interface ModuleInfo { key: string; name: string; depends_on: string[] }
interface PackageInfo { id: string; key: string; name: string; modules: string[] }
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

const REFRESH = [["admin"]];

export default function AdminConsole() {
  const router = useRouter();
  const { data: user, isLoading: userLoading } = useApi<{ is_platform_admin: boolean; email: string }>("/auth/user");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const isAdmin = !!user?.is_platform_admin;
  const { data: overview } = useApi<Overview>(isAdmin ? "/admin/overview" : null);
  const { data: workspaces, isLoading } = useApi<AdminWorkspace[]>(
    isAdmin ? `/admin/workspaces${query ? `?search=${encodeURIComponent(query)}` : ""}` : null
  );

  useEffect(() => {
    if (!session.isAuthenticated()) router.replace("/login");
  }, [router]);

  useEffect(() => {
    const t = setTimeout(() => setQuery(search.trim()), 300);
    return () => clearTimeout(t);
  }, [search]);

  if (userLoading) return <Loading />;
  if (!isAdmin) {
    return (
      <div className="flex min-h-screen items-center justify-center p-6">
        <EmptyState title="Platform admins only" description="This console manages every customer workspace. Ask the platform owner for access." icon={<ShieldCheck />} action={<Link href="/dashboard" className="text-sm text-brand">Back to dashboard</Link>} />
      </div>
    );
  }

  const open = workspaces?.find((w) => w.id === openId) ?? null;

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

      <main className="mx-auto max-w-7xl space-y-6 px-6 py-8">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <StatTile label="Customer workspaces" icon={<Building2 />} value={String(overview?.workspaces ?? "—")} sub={overview ? Object.entries(overview.by_package).map(([k, v]) => `${v} ${k}`).join(" · ") : undefined} />
          <StatTile label="Active" icon={<CheckCircle2 />} tone="emerald" value={String(overview?.active_workspaces ?? "—")} sub={overview ? `${overview.workspaces - overview.active_workspaces} suspended` : undefined} />
          <StatTile label="Users" icon={<Users />} tone="sky" value={String(overview?.users ?? "—")} />
        </div>

        <Card>
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 p-4">
            <p className="font-semibold">Workspaces</p>
            <div className="relative w-full sm:w-80">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search company or owner email…"
                className="w-full rounded-lg border border-slate-200 py-2 pl-9 pr-3 text-sm focus:border-brand focus:outline-none focus:ring-4 focus:ring-brand/10"
              />
            </div>
          </div>
          {isLoading ? <Loading /> : !workspaces?.length ? (
            <div className="p-6"><EmptyState title="No workspaces found" /></div>
          ) : (
            <Table>
              <thead><tr><Th>Company</Th><Th>Owner</Th><Th>Package</Th><Th>Modules</Th><Th>Users</Th><Th>Since</Th><Th>Status</Th></tr></thead>
              <tbody>
                {workspaces.map((w) => {
                  const customised = Object.keys(w.module_overrides).length > 0;
                  return (
                    <tr key={w.id} onClick={() => setOpenId(w.id)} className="cursor-pointer hover:bg-slate-50">
                      <Td className="font-medium">{w.name}</Td>
                      <Td className="text-slate-500">{w.owner_email ?? "—"}</Td>
                      <Td>{w.package_name}</Td>
                      <Td>
                        {w.effective_modules.length} enabled
                        {customised && <span className="ml-2 text-xs text-amber-600">customised</span>}
                      </Td>
                      <Td>{w.member_count}</Td>
                      <Td>{fmtDate(w.created_at)}</Td>
                      <Td><Badge tone={w.is_active ? "success" : "danger"}>{w.is_active ? "Active" : "Suspended"}</Badge></Td>
                    </tr>
                  );
                })}
              </tbody>
            </Table>
          )}
        </Card>
      </main>

      {open && <WorkspaceEditor workspace={open} onClose={() => setOpenId(null)} />}
    </div>
  );
}

function WorkspaceEditor({ workspace, onClose }: { workspace: AdminWorkspace; onClose: () => void }) {
  const { data: modules } = useApi<ModuleInfo[]>("/admin/modules");
  const { data: packages } = useApi<PackageInfo[]>("/admin/packages");
  const update = useApiMutation<Record<string, unknown>>("patch", `/admin/workspaces/${workspace.id}`, REFRESH);
  const [error, setError] = useState<string | null>(null);
  const enabled = useMemo(() => new Set(workspace.effective_modules), [workspace.effective_modules]);
  const names = useMemo(() => new Map((modules ?? []).map((m) => [m.key, m.name])), [modules]);

  async function save(body: Record<string, unknown>) {
    setError(null);
    try {
      await update.mutateAsync(body);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const inPackage = (key: string) => workspace.package_modules.includes("*") || workspace.package_modules.includes(key);

  return (
    <Modal open onClose={onClose} title={workspace.name} wide>
      <div className="space-y-6">
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <p className="mb-1.5 text-xs font-medium text-slate-600">Package</p>
            <Select value={workspace.package_id} onChange={(e) => save({ package_id: e.target.value })} disabled={update.isPending}>
              {packages?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </Select>
          </div>
          <div>
            <p className="mb-1.5 text-xs font-medium text-slate-600">Account status</p>
            <div className="flex items-center gap-3 rounded-lg border border-slate-200 px-3 py-2">
              {workspace.is_active ? <CheckCircle2 className="h-4 w-4 text-emerald-600" /> : <PauseCircle className="h-4 w-4 text-red-600" />}
              <span className="flex-1 text-sm">{workspace.is_active ? "Active — users can sign in" : "Suspended — all access blocked"}</span>
              <Button variant={workspace.is_active ? "danger" : "primary"} className="px-3 py-1.5 text-xs" onClick={() => save({ is_active: !workspace.is_active })} disabled={update.isPending}>
                {workspace.is_active ? "Suspend" : "Reactivate"}
              </Button>
            </div>
          </div>
        </div>

        <div>
          <div className="mb-2 flex items-center justify-between">
            <p className="text-sm font-semibold">Modules</p>
            {Object.keys(workspace.module_overrides).length > 0 && (
              <button
                className="text-xs text-brand hover:underline"
                onClick={() => save({ module_overrides: Object.fromEntries(Object.keys(workspace.module_overrides).map((k) => [k, null])) })}
              >
                Reset to package defaults
              </button>
            )}
          </div>
          <p className="mb-3 text-xs text-slate-500">
            Switching a module off hides it and blocks its API for everyone in this workspace. Nothing is deleted — switching it back on restores all data.
            Modules that depend on a switched-off module go off with it.
          </p>
          <div className="grid gap-2 sm:grid-cols-2">
            {modules?.map((m) => {
              const on = enabled.has(m.key);
              const override = workspace.module_overrides[m.key];
              const blockedBy = m.depends_on.filter((d) => workspace.module_overrides[d] === false);
              return (
                <div key={m.key} className={`flex items-center gap-3 rounded-xl border px-4 py-3 ${on ? "border-slate-200" : "border-slate-200 bg-slate-50"}`}>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium">{m.name}</p>
                    <p className="text-xs text-slate-500">
                      {override === undefined ? (inPackage(m.key) ? "From package" : "Not in package") : override ? "Enabled by you" : "Disabled by you"}
                      {m.depends_on.length > 0 && ` · needs ${m.depends_on.map((d) => names.get(d) ?? d).join(", ")}`}
                    </p>
                    {blockedBy.length > 0 && <p className="text-xs text-amber-600">Off because {blockedBy.map((d) => names.get(d) ?? d).join(", ")} is off</p>}
                  </div>
                  <Switch
                    checked={on}
                    label={`Toggle ${m.name}`}
                    disabled={update.isPending || blockedBy.length > 0}
                    onChange={(value) => save({ module_overrides: { [m.key]: value === inPackage(m.key) ? null : value } })}
                  />
                </div>
              );
            })}
          </div>
        </div>
        <ErrorBanner message={error} />
      </div>
    </Modal>
  );
}
