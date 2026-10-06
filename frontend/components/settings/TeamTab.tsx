"use client";

import { useState } from "react";
import { Check, Copy, MailPlus, Trash2 } from "lucide-react";
import { Badge, Button, Card, EmptyState, ErrorBanner, Field, Input, Loading, Select, Table, Td, Th } from "@/components/om/primitives";
import { useMe } from "@/lib/api/hooks";
import { errorMessage, useApi, useApiMutation } from "@/lib/api/query";
import { fmtDate, humanize } from "@/lib/format";
import type { Invitation, Member } from "@/lib/api/types";

const ROLES: { key: Member["role"]; label: string; can: string }[] = [
  { key: "owner", label: "Owner", can: "Everything, including billing, team and deleting data" },
  { key: "admin", label: "Admin", can: "Everything except changing owners" },
  { key: "manager", label: "Manager", can: "Sales, purchasing, stock, CRM, staff records and assets; reads the accounts. No payroll" },
  { key: "staff", label: "Staff", can: "Sells and invoices, manages contacts, uses the POS; sees stock and purchases" },
  { key: "viewer", label: "Viewer", can: "Read-only access; can't change anything" },
];
const REFRESH = [["workspaces"]];

export function TeamTab() {
  const { data: me } = useMe();
  const isAdmin = !!me?.permissions.includes("*");
  const isOwner = me?.role === "owner";
  const { data: members, isLoading } = useApi<Member[]>("/workspaces/members");
  const { data: invitations } = useApi<Invitation[]>(isAdmin ? "/workspaces/invitations" : null);
  const invite = useApiMutation<Record<string, string>, { invite_link: string; email_delivered: boolean; email: string }>("post", "/workspaces/members", REFRESH);
  const changeRole = useApiMutation<{ id: string; role: string }>("patch", (b) => `/workspaces/members/${b.id}`, REFRESH);
  const remove = useApiMutation<{ id: string }>("del", (b) => `/workspaces/members/${b.id}`, REFRESH);
  const revoke = useApiMutation<{ id: string }>("del", (b) => `/workspaces/invitations/${b.id}`, REFRESH);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Member["role"]>("staff");
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState<{ link: string; delivered: boolean; email: string } | null>(null);
  const [copied, setCopied] = useState(false);

  async function run(fn: () => Promise<unknown>) {
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <div className="space-y-6">
      {isAdmin && (
        <Card className="p-6">
          <h2 className="text-sm font-semibold text-brand">Invite someone</h2>
          <form
            className="mt-3 flex flex-wrap items-end gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              setSent(null);
              run(async () => {
                const r = await invite.mutateAsync({ email, role });
                setSent({ link: r.invite_link, delivered: r.email_delivered, email: r.email });
                setEmail("");
              });
            }}
          >
            <div className="min-w-[16rem] flex-1"><Field label="Email address"><Input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@company.co.ke" /></Field></div>
            <div className="w-44">
              <Field label="Role">
                <Select value={role} onChange={(e) => setRole(e.target.value as Member["role"])}>
                  {ROLES.filter((r) => r.key !== "owner" || isOwner).map((r) => <option key={r.key} value={r.key}>{r.label}</option>)}
                </Select>
              </Field>
            </div>
            <Button type="submit" disabled={invite.isPending}><MailPlus /> Send invitation</Button>
          </form>
          <p className="mt-2 text-xs text-slate-500">{ROLES.find((r) => r.key === role)?.can}.</p>
          {sent && (
            <div className="mt-4 rounded-xl bg-emerald-50 p-4 text-sm text-emerald-900">
              <p className="font-medium">
                {sent.delivered ? `Invitation emailed to ${sent.email}.` : `Invitation created for ${sent.email}. Email isn't set up yet, so share this link with them yourself:`}
              </p>
              <div className="mt-2 flex items-center gap-2">
                <input readOnly value={sent.link} onFocus={(e) => e.target.select()} className="min-w-0 flex-1 rounded-lg border border-emerald-200 bg-white px-3 py-1.5 font-mono text-xs" />
                <Button
                  variant="secondary"
                  className="px-3 py-1.5 text-xs"
                  onClick={async () => { await navigator.clipboard.writeText(sent.link); setCopied(true); setTimeout(() => setCopied(false), 2000); }}
                >
                  {copied ? <><Check /> Copied</> : <><Copy /> Copy link</>}
                </Button>
              </div>
              <p className="mt-2 text-xs opacity-80">The link works once and expires in 7 days.</p>
            </div>
          )}
        </Card>
      )}
      <ErrorBanner message={error} />

      <Card>
        <p className="border-b border-slate-100 px-5 py-3 text-sm font-semibold dark:border-navy-700">Team members</p>
        {isLoading ? <Loading /> : (
          <Table>
            <thead><tr><Th>Name</Th><Th>Email</Th><Th>Role</Th><Th>Joined</Th><Th></Th></tr></thead>
            <tbody>
              {members?.map((m) => {
                const self = m.user_id === me?.user_id;
                const locked = !isAdmin || self || (m.role === "owner" && !isOwner);
                return (
                  <tr key={m.id}>
                    <Td className="font-medium">{m.full_name || "—"}{self && <span className="ml-2 text-xs text-slate-400">you</span>}</Td>
                    <Td className="text-slate-500">{m.email}</Td>
                    <Td>
                      {locked ? <Badge tone={m.role === "owner" ? "info" : "neutral"}>{humanize(m.role)}</Badge> : (
                        <div className="w-36">
                          <Select value={m.role} onChange={(e) => run(() => changeRole.mutateAsync({ id: m.id, role: e.target.value }))}>
                            {ROLES.filter((r) => r.key !== "owner" || isOwner).map((r) => <option key={r.key} value={r.key}>{r.label}</option>)}
                          </Select>
                        </div>
                      )}
                    </Td>
                    <Td>{fmtDate(m.joined_at)}</Td>
                    <Td>
                      {!locked && (
                        <Button variant="ghost" className="px-2 py-1 text-xs text-red-600" onClick={() => confirm(`Remove ${m.full_name || m.email} from the team?`) && run(() => remove.mutateAsync({ id: m.id }))}>
                          <Trash2 /> Remove
                        </Button>
                      )}
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        )}
      </Card>

      {isAdmin && !!invitations?.length && (
        <Card>
          <p className="border-b border-slate-100 px-5 py-3 text-sm font-semibold dark:border-navy-700">Pending invitations</p>
          <Table>
            <tbody>
              {invitations.map((i) => (
                <tr key={i.id}>
                  <Td className="font-medium">{i.email}</Td>
                  <Td><Badge tone="warning">{humanize(i.role ?? "staff")}</Badge></Td>
                  <Td className="text-slate-500">Expires {fmtDate(i.expires_at)}</Td>
                  <Td><Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => run(() => revoke.mutateAsync({ id: i.id }))}>Cancel invitation</Button></Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      )}

      <Card className="p-6">
        <h2 className="text-sm font-semibold">What each role can do</h2>
        <dl className="mt-3 space-y-2 text-sm">
          {ROLES.map((r) => (
            <div key={r.key} className="flex gap-3"><dt className="w-20 shrink-0 font-medium">{r.label}</dt><dd className="text-slate-500">{r.can}.</dd></div>
          ))}
        </dl>
      </Card>
      {!members?.length && !isLoading && <EmptyState title="No team members" />}
    </div>
  );
}
