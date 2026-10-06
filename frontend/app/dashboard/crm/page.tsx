"use client";

import { useMemo, useState } from "react";
import { BellRing, Building2, CalendarClock, ChevronLeft, ChevronRight, Download, Handshake, Mail, MessageSquare, Phone, Plus, Truck, Upload, UserPlus, Users } from "lucide-react";
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
  PageHeader,
  Select,
  StatTile,
  Table,
  Tabs,
  Td,
  Th,
} from "@/components/om/primitives";
import { ImportModal } from "@/components/om/ImportModal";
import { useMe } from "@/lib/api/hooks";
import { errorMessage, openFile, useApi, useApiMutation } from "@/lib/api/query";
import { fmtDate, fmtMoney, humanize, num, today, yearStart } from "@/lib/format";
import type { AgingReport, CrmTask, Deal, Interaction, Invoice, Party } from "@/lib/api/types";

type Tab = "contacts" | "pipeline" | "tasks";
const REFRESH = [["crm"]];
const KIND_TONE: Record<Party["kind"], "neutral" | "success" | "warning" | "info"> = { lead: "warning", customer: "success", vendor: "info", both: "success" };
const KIND_LABEL: Record<Party["kind"], string> = { lead: "Lead", customer: "Customer", vendor: "Supplier", both: "Customer & supplier" };
const STAGES: Deal["stage"][] = ["new", "qualified", "proposal", "won", "lost"];
const STAGE_STYLE: Record<Deal["stage"], string> = {
  new: "border-t-slate-400", qualified: "border-t-sky-500", proposal: "border-t-amber-500", won: "border-t-emerald-500", lost: "border-t-red-400",
};

export default function CrmPage() {
  const { data: me } = useMe();
  const canWrite = !!me && (me.permissions.includes("*") || me.permissions.includes("crm.write"));
  const hasSales = !!me?.features.includes("sales");
  const { data: parties, isLoading } = useApi<Party[]>("/crm/parties");
  const { data: deals } = useApi<Deal[]>("/crm/deals");
  const { data: followUps } = useApi<Interaction[]>("/crm/interactions/needs-follow-up");
  const { data: aging } = useApi<AgingReport>(hasSales ? "/sales/reports/ar-aging" : null);
  const [tab, setTab] = useState<Tab>("contacts");
  const [editing, setEditing] = useState<Party | "new" | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [showImport, setShowImport] = useState(false);

  const count = (kinds: Party["kind"][]) => (parties ?? []).filter((p) => kinds.includes(p.kind)).length;
  const pipeline = (deals ?? []).filter((d) => d.stage !== "won" && d.stage !== "lost");
  const owed = useMemo(() => new Map((aging?.rows ?? []).map((r) => [r.party_id, num(r.total)])), [aging]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="CRM"
        description="Customers, suppliers and leads — every conversation, deal and balance in one place."
        actions={
          <>
            <Button variant="secondary" onClick={() => openFile("/crm/parties-export", "contacts.csv")}><Download /> Export</Button>
            {canWrite && <Button variant="secondary" onClick={() => setShowImport(true)}><Upload /> Import</Button>}
            {canWrite && <Button onClick={() => setEditing("new")}><UserPlus /> Add contact</Button>}
          </>
        }
      />

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <StatTile label="Customers" icon={<Users />} tone="emerald" value={String(count(["customer", "both"]))} />
        <StatTile label="Suppliers" icon={<Truck />} tone="sky" value={String(count(["vendor", "both"]))} />
        <StatTile label="Leads" icon={<UserPlus />} tone="amber" value={String(count(["lead"]))} />
        <StatTile label="Open pipeline" icon={<Handshake />} tone="violet" value={fmtMoney(pipeline.reduce((s, d) => s + num(d.amount), 0))} sub={`${pipeline.length} deal(s)`} />
        <StatTile label="Follow-ups due" icon={<BellRing />} tone="rose" value={String(followUps?.length ?? 0)} />
      </div>

      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        tabs={[
          { key: "contacts", label: "Contacts", count: parties?.length },
          { key: "pipeline", label: "Deals pipeline", count: pipeline.length },
          { key: "tasks", label: "Tasks & follow-ups", count: followUps?.length },
        ]}
      />

      {tab === "contacts" && <ContactsTab parties={parties} isLoading={isLoading} owed={owed} hasSales={hasSales} onOpen={setOpenId} onAdd={canWrite ? () => setEditing("new") : undefined} />}
      {tab === "pipeline" && <PipelineTab deals={deals ?? []} parties={parties ?? []} canWrite={canWrite} />}
      {tab === "tasks" && <TasksTab parties={parties ?? []} followUps={followUps ?? []} canWrite={canWrite} onOpenContact={setOpenId} />}

      {editing && <ContactForm party={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
      {openId && parties && (
        <ContactModal
          party={parties.find((p) => p.id === openId)!}
          hasSales={hasSales}
          canWrite={canWrite}
          onEdit={(p) => { setOpenId(null); setEditing(p); }}
          onClose={() => setOpenId(null)}
        />
      )}
      <ImportModal
        open={showImport}
        onClose={() => setShowImport(false)}
        title="Import contacts"
        endpoint="/crm/parties-import"
        templatePath="/crm/parties-template"
        templateName="contacts-template.csv"
        help="Add customers, suppliers and leads from a spreadsheet. Contacts are matched on name, so importing again updates their details instead of creating duplicates."
        invalidate={REFRESH}
      />
    </div>
  );
}

function ContactsTab({ parties, isLoading, owed, hasSales, onOpen, onAdd }: { parties?: Party[]; isLoading: boolean; owed: Map<string, number>; hasSales: boolean; onOpen: (id: string) => void; onAdd?: () => void }) {
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState("");
  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (parties ?? [])
      .filter((p) => (!kind || p.kind === kind || (p.kind === "both" && kind !== "lead")) && (!q || [p.name, p.email, p.phone, p.tax_id].some((v) => (v ?? "").toLowerCase().includes(q))))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [parties, search, kind]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-3">
        <div className="w-full sm:w-80"><Input placeholder="Search name, email, phone or PIN…" value={search} onChange={(e) => setSearch(e.target.value)} /></div>
        <div className="w-44">
          <Select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">Everyone</option><option value="customer">Customers</option><option value="vendor">Suppliers</option><option value="lead">Leads</option>
          </Select>
        </div>
      </div>
      <Card>
        {isLoading ? <Loading rows={6} /> : !parties?.length ? (
          <div className="p-6"><EmptyState icon={<Users />} title="No contacts yet" description="Add the customers you sell to and the suppliers you buy from." action={onAdd && <Button onClick={onAdd}><UserPlus /> Add contact</Button>} /></div>
        ) : !rows.length ? (
          <div className="p-6"><EmptyState title="No contacts match" /></div>
        ) : (
          <Table>
            <thead><tr><Th>Name</Th><Th>Type</Th><Th>Email</Th><Th>Phone</Th><Th>KRA PIN</Th>{hasSales && <Th>Owes you</Th>}</tr></thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.id} onClick={() => onOpen(p.id)} className="cursor-pointer hover:bg-slate-50 dark:hover:bg-navy-700/40">
                  <Td>
                    <div className="flex items-center gap-3">
                      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-50 text-xs font-semibold text-brand">
                        {p.is_company ? <Building2 className="h-4 w-4" /> : p.name.slice(0, 2).toUpperCase()}
                      </span>
                      <span className="font-medium">{p.name}</span>
                    </div>
                  </Td>
                  <Td><Badge tone={KIND_TONE[p.kind]}>{KIND_LABEL[p.kind]}</Badge></Td>
                  <Td className="text-slate-500">{p.email || "—"}</Td>
                  <Td className="text-slate-500">{p.phone || "—"}</Td>
                  <Td className="font-mono text-xs text-slate-500">{p.tax_id || "—"}</Td>
                  {hasSales && <Td className={owed.get(p.id) ? "font-medium" : "text-slate-300"}>{owed.get(p.id) ? fmtMoney(owed.get(p.id)) : "—"}</Td>}
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}

function ContactForm({ party, onClose }: { party: Party | null; onClose: () => void }) {
  const create = useApiMutation("post", "/crm/parties", REFRESH);
  const update = useApiMutation("patch", `/crm/parties/${party?.id}`, REFRESH);
  const [f, setF] = useState({
    name: party?.name ?? "", kind: party?.kind ?? "customer", is_company: party?.is_company ?? true, tax_id: party?.tax_id ?? "",
    email: party?.email ?? "", phone: party?.phone ?? "", billing_address: party?.billing_address ?? "", shipping_address: party?.shipping_address ?? "",
  });
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const body = { ...f, name: f.name.trim(), tax_id: f.tax_id || null, email: f.email || null, phone: f.phone || null };
    try {
      await (party ? update : create).mutateAsync(body);
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <Modal open onClose={onClose} title={party ? `Edit ${party.name}` : "Add contact"} wide>
      <form onSubmit={submit} className="space-y-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div className="sm:col-span-2"><Field label="Name"><Input required autoFocus value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field></div>
          <Field label="Type">
            <Select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value as Party["kind"] })}>
              <option value="customer">Customer</option><option value="vendor">Supplier</option><option value="both">Customer & supplier</option><option value="lead">Lead</option>
            </Select>
          </Field>
          <Field label="Email" hint="Invoices and statements are sent here"><Input type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
          <Field label="Phone"><Input value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} /></Field>
          <Field label="KRA PIN" hint="Printed on their tax invoices"><Input value={f.tax_id} onChange={(e) => setF({ ...f, tax_id: e.target.value.toUpperCase() })} /></Field>
          <div className="sm:col-span-3"><Field label="Billing address"><Input value={f.billing_address} onChange={(e) => setF({ ...f, billing_address: e.target.value })} /></Field></div>
          <div className="sm:col-span-3"><Field label="Delivery address (if different)"><Input value={f.shipping_address} onChange={(e) => setF({ ...f, shipping_address: e.target.value })} /></Field></div>
        </div>
        <Checkbox label="This is a company (not an individual)" checked={f.is_company} onChange={(v) => setF({ ...f, is_company: v })} />
        <ErrorBanner message={error} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={create.isPending || update.isPending}>{party ? "Save changes" : "Add contact"}</Button>
        </div>
      </form>
    </Modal>
  );
}

const TYPE_ICON = { call: Phone, email: Mail, meeting: Users, note: MessageSquare };

function ContactModal({ party, hasSales, canWrite, onEdit, onClose }: { party: Party; hasSales: boolean; canWrite: boolean; onEdit: (p: Party) => void; onClose: () => void }) {
  const isCustomer = party.kind !== "vendor" && party.kind !== "lead";
  const { data: timeline } = useApi<Interaction[]>(`/crm/parties/${party.id}/timeline`);
  const { data: terms } = useApi<{ payment_terms_days: number | null; credit_limit: string }>(`/crm/parties/${party.id}/terms`);
  const { data: balance } = useApi<{ balance: string }>(hasSales && isCustomer ? `/sales/customers/${party.id}/balance` : null);
  const { data: invoices } = useApi<Invoice[]>(hasSales && isCustomer ? `/sales/invoices?party_id=${party.id}` : null);
  const log = useApiMutation("post", "/crm/interactions", REFRESH);
  const saveTerms = useApiMutation("put", `/crm/parties/${party.id}/terms`, REFRESH);
  const emailStatement = useApiMutation<Record<string, unknown>, { to: string; delivered: boolean }>("post", `/sales/customers/${party.id}/statement/email`);
  const [type, setType] = useState<Interaction["type"]>("call");
  const [summary, setSummary] = useState("");
  const [followUp, setFollowUp] = useState("");
  const [days, setDays] = useState<string | null>(null);
  const [limit, setLimit] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function run(fn: () => Promise<unknown>) {
    setError(null);
    setNotice(null);
    try {
      await fn();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const termDays = days ?? (terms?.payment_terms_days != null ? String(terms.payment_terms_days) : "");
  const creditLimit = limit ?? String(num(terms?.credit_limit));
  const overLimit = num(creditLimit) > 0 && num(balance?.balance) > num(creditLimit);

  return (
    <Modal open onClose={onClose} title={party.name} wide>
      <div className="space-y-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1 text-sm text-slate-600 dark:text-slate-300">
            <Badge tone={KIND_TONE[party.kind]}>{KIND_LABEL[party.kind]}</Badge>
            {party.email && <p className="flex items-center gap-2 pt-1"><Mail className="h-3.5 w-3.5 text-slate-400" />{party.email}</p>}
            {party.phone && <p className="flex items-center gap-2"><Phone className="h-3.5 w-3.5 text-slate-400" />{party.phone}</p>}
            {party.billing_address && <p>{party.billing_address}</p>}
            {party.tax_id && <p>KRA PIN: <span className="font-mono">{party.tax_id}</span></p>}
          </div>
          <div className="flex flex-wrap gap-2">
            {canWrite && <Button variant="secondary" onClick={() => onEdit(party)}>Edit</Button>}
            {hasSales && isCustomer && (
              <>
                <Button variant="secondary" onClick={() => openFile(`/sales/customers/${party.id}/statement/pdf?start=${yearStart()}&end=${today()}`)}>Statement PDF</Button>
                <Button
                  variant="secondary"
                  disabled={emailStatement.isPending}
                  onClick={() => run(async () => {
                    const r = await emailStatement.mutateAsync({ start: yearStart(), end: today() });
                    setNotice(r.delivered ? `Statement emailed to ${r.to}.` : `Email isn't set up yet — the statement for ${r.to} was saved to the outbox instead.`);
                  })}
                >
                  <Mail /> Email statement
                </Button>
              </>
            )}
          </div>
        </div>
        <ErrorBanner message={error} />
        {notice && <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{notice}</p>}

        {hasSales && isCustomer && (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div className={`rounded-xl p-3 ${overLimit ? "bg-red-50" : "bg-slate-50 dark:bg-navy-900"}`}>
              <p className="text-xs text-slate-500">Owes you</p>
              <p className={`mt-0.5 font-semibold ${overLimit ? "text-red-700" : ""}`}>{fmtMoney(balance?.balance)}</p>
              {overLimit && <p className="text-xs text-red-600">Over credit limit</p>}
            </div>
            <div className="rounded-xl bg-slate-50 p-3 dark:bg-navy-900"><p className="text-xs text-slate-500">Invoices</p><p className="mt-0.5 font-semibold">{invoices?.length ?? "—"}</p></div>
            <form className="col-span-2 flex items-end gap-2 rounded-xl bg-slate-50 p-3 dark:bg-navy-900" onSubmit={(e) => {
              e.preventDefault();
              run(async () => {
                await saveTerms.mutateAsync({ payment_terms_days: Number(termDays || 0), credit_limit: creditLimit || "0" });
                setNotice("Terms saved — new invoices will use them.");
              });
            }}>
              <div className="flex-1"><Field label="Payment terms (days)"><Input type="number" min="0" max="365" placeholder="Default" value={termDays} onChange={(e) => setDays(e.target.value)} disabled={!canWrite} /></Field></div>
              <div className="flex-1"><Field label="Credit limit"><Input type="number" min="0" step="0.01" value={creditLimit} onChange={(e) => setLimit(e.target.value)} disabled={!canWrite} /></Field></div>
              {canWrite && <Button type="submit" variant="secondary" disabled={saveTerms.isPending}>Save</Button>}
            </form>
          </div>
        )}

        <div className="grid gap-6 lg:grid-cols-2">
          <div>
            <h3 className="mb-2 text-sm font-semibold">Activity</h3>
            {canWrite && (
              <form className="mb-3 space-y-2 rounded-xl border border-slate-200 p-3 dark:border-navy-700" onSubmit={(e) => {
                e.preventDefault();
                run(async () => {
                  await log.mutateAsync({ party_id: party.id, type, summary, occurred_at: new Date().toISOString(), follow_up_at: followUp ? new Date(`${followUp}T09:00:00`).toISOString() : null });
                  setSummary("");
                  setFollowUp("");
                });
              }}>
                <div className="flex gap-2">
                  <div className="w-32">
                    <Select value={type} onChange={(e) => setType(e.target.value as Interaction["type"])}>
                      <option value="call">Call</option><option value="meeting">Meeting</option><option value="email">Email</option><option value="note">Note</option>
                    </Select>
                  </div>
                  <Input required placeholder="What was discussed?" value={summary} onChange={(e) => setSummary(e.target.value)} />
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-slate-500">Follow up on</span>
                  <div className="w-44"><Input type="date" min={today()} value={followUp} onChange={(e) => setFollowUp(e.target.value)} /></div>
                  <Button type="submit" className="ml-auto" disabled={log.isPending}>Log</Button>
                </div>
              </form>
            )}
            <ul className="max-h-72 space-y-3 overflow-y-auto">
              {timeline?.map((i) => {
                const Icon = TYPE_ICON[i.type];
                return (
                  <li key={i.id} className="flex gap-3 text-sm">
                    <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-100 text-slate-500 dark:bg-navy-700"><Icon className="h-3.5 w-3.5" /></span>
                    <div>
                      <p>{i.summary}</p>
                      <p className="text-xs text-slate-400">
                        {humanize(i.type)} · {fmtDate(i.occurred_at)}
                        {i.follow_up_at && !i.is_follow_up_done && <span className="ml-2 text-amber-600">Follow up {fmtDate(i.follow_up_at)}</span>}
                      </p>
                    </div>
                  </li>
                );
              })}
              {timeline && !timeline.length && <li className="text-sm text-slate-400">No calls, meetings or notes logged yet.</li>}
            </ul>
          </div>

          {hasSales && isCustomer && (
            <div>
              <h3 className="mb-2 text-sm font-semibold">Recent invoices</h3>
              <div className="max-h-96 overflow-y-auto rounded-xl border border-slate-200 dark:border-navy-700">
                <Table>
                  <tbody>
                    {invoices?.slice(0, 15).map((inv) => (
                      <tr key={inv.id}>
                        <Td className="font-medium">{inv.invoice_no}</Td>
                        <Td className="text-xs text-slate-500">{fmtDate(inv.issue_date)}</Td>
                        <Td>{fmtMoney(inv.total)}</Td>
                        <Td><Badge tone={inv.status === "paid" ? "success" : inv.status === "void" ? "danger" : "warning"}>{humanize(inv.status)}</Badge></Td>
                      </tr>
                    ))}
                    {invoices && !invoices.length && <tr><Td className="text-slate-400">No invoices yet.</Td></tr>}
                  </tbody>
                </Table>
              </div>
            </div>
          )}
        </div>
      </div>
    </Modal>
  );
}

function PipelineTab({ deals, parties, canWrite }: { deals: Deal[]; parties: Party[]; canWrite: boolean }) {
  const create = useApiMutation("post", "/crm/deals", REFRESH);
  const move = useApiMutation<{ id: string; stage: string }>("patch", (b) => `/crm/deals/${b.id}`, REFRESH);
  const [show, setShow] = useState(false);
  const [f, setF] = useState({ party_id: "", title: "", amount: "", expected_close_date: "" });
  const [error, setError] = useState<string | null>(null);
  const names = useMemo(() => new Map(parties.map((p) => [p.id, p.name])), [parties]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-500">Track each opportunity from first contact to won or lost.</p>
        {canWrite && <Button onClick={() => setShow(true)} disabled={!parties.length}><Plus /> New deal</Button>}
      </div>
      <ErrorBanner message={!show ? error : null} />
      <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-5">
        {STAGES.map((stage, si) => {
          const column = deals.filter((d) => d.stage === stage);
          return (
            <div key={stage} className={`rounded-2xl border border-t-4 border-slate-200 bg-slate-50/60 p-3 dark:border-navy-700 dark:bg-navy-900/40 ${STAGE_STYLE[stage]}`}>
              <div className="mb-3 flex items-baseline justify-between">
                <p className="text-sm font-semibold">{humanize(stage)}</p>
                <p className="text-xs text-slate-500">{column.length} · {fmtMoney(column.reduce((s, d) => s + num(d.amount), 0))}</p>
              </div>
              <div className="space-y-2">
                {column.map((d) => (
                  <div key={d.id} className="rounded-xl bg-white p-3 shadow-card ring-1 ring-slate-200/70 dark:bg-navy-800 dark:ring-navy-700">
                    <p className="text-sm font-medium">{d.title}</p>
                    <p className="text-xs text-slate-500">{names.get(d.party_id) ?? "—"}</p>
                    <div className="mt-2 flex items-center justify-between">
                      <span className="text-sm font-semibold">{fmtMoney(d.amount)}</span>
                      {canWrite && (
                        <span className="flex gap-1">
                          <button title="Move back" disabled={si === 0 || move.isPending} onClick={() => move.mutate({ id: d.id, stage: STAGES[si - 1] })} className="rounded p-1 text-slate-400 hover:bg-slate-100 disabled:opacity-30"><ChevronLeft className="h-4 w-4" /></button>
                          <button title="Move forward" disabled={si === STAGES.length - 1 || move.isPending} onClick={() => move.mutate({ id: d.id, stage: STAGES[si + 1] })} className="rounded p-1 text-slate-400 hover:bg-slate-100 disabled:opacity-30"><ChevronRight className="h-4 w-4" /></button>
                        </span>
                      )}
                    </div>
                    {d.expected_close_date && <p className="mt-1 flex items-center gap-1 text-xs text-slate-400"><CalendarClock className="h-3 w-3" />{fmtDate(d.expected_close_date)}</p>}
                  </div>
                ))}
                {!column.length && <p className="py-4 text-center text-xs text-slate-400">Nothing here</p>}
              </div>
            </div>
          );
        })}
      </div>

      <Modal open={show} onClose={() => setShow(false)} title="New deal">
        <form className="space-y-3" onSubmit={async (e) => {
          e.preventDefault();
          setError(null);
          try {
            await create.mutateAsync({ ...f, amount: f.amount || "0", expected_close_date: f.expected_close_date || null });
            setShow(false);
            setF({ party_id: "", title: "", amount: "", expected_close_date: "" });
          } catch (err) {
            setError(errorMessage(err));
          }
        }}>
          <Field label="Contact">
            <Select required value={f.party_id} onChange={(e) => setF({ ...f, party_id: e.target.value })}>
              <option value="">Select…</option>
              {parties.filter((p) => p.kind !== "vendor").map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </Select>
          </Field>
          <Field label="What is the deal?"><Input required value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} placeholder="e.g. Roofing materials for new classroom block" /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Value"><Input type="number" min="0" step="0.01" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} /></Field>
            <Field label="Expected close"><Input type="date" value={f.expected_close_date} onChange={(e) => setF({ ...f, expected_close_date: e.target.value })} /></Field>
          </div>
          <ErrorBanner message={error} />
          <div className="flex justify-end"><Button type="submit" disabled={create.isPending}>Create deal</Button></div>
        </form>
      </Modal>
    </div>
  );
}

function TasksTab({ parties, followUps, canWrite, onOpenContact }: { parties: Party[]; followUps: Interaction[]; canWrite: boolean; onOpenContact: (id: string) => void }) {
  const { data: tasks, isLoading } = useApi<CrmTask[]>("/crm/tasks");
  const create = useApiMutation("post", "/crm/tasks", REFRESH);
  const update = useApiMutation<{ id: string; done: boolean }>("patch", (b) => `/crm/tasks/${b.id}`, REFRESH);
  const followDone = useApiMutation<{ id: string; done: boolean }>("post", (b) => `/crm/interactions/${b.id}/follow-up`, REFRESH);
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");
  const [partyId, setPartyId] = useState("");
  const [showDone, setShowDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const names = useMemo(() => new Map(parties.map((p) => [p.id, p.name])), [parties]);
  const list = (tasks ?? []).filter((t) => showDone || !t.done).sort((a, b) => (a.due_date ?? "9999").localeCompare(b.due_date ?? "9999"));

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <div className="space-y-3">
        <h3 className="text-sm font-semibold">Follow-ups due</h3>
        <Card>
          {!followUps.length ? (
            <div className="p-6"><EmptyState icon={<BellRing />} title="You're all caught up" description="Set a follow-up date when you log a call or meeting and it will appear here when it's due." /></div>
          ) : (
            <ul className="divide-y divide-slate-100 dark:divide-navy-700">
              {followUps.map((i) => (
                <li key={i.id} className="flex items-center gap-3 px-4 py-3">
                  <div className="min-w-0 flex-1">
                    <button className="text-sm font-medium text-brand hover:underline" onClick={() => onOpenContact(i.party_id)}>{names.get(i.party_id) ?? "Contact"}</button>
                    <p className="truncate text-sm text-slate-600 dark:text-slate-300">{i.summary}</p>
                    <p className="text-xs text-amber-600">Due {fmtDate(i.follow_up_at)}</p>
                  </div>
                  {canWrite && <Button variant="secondary" className="px-3 py-1.5 text-xs" onClick={() => followDone.mutate({ id: i.id, done: true })}>Done</Button>}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold">Tasks</h3>
          <Checkbox label="Show completed" checked={showDone} onChange={setShowDone} />
        </div>
        {canWrite && (
          <form className="flex flex-wrap gap-2" onSubmit={async (e) => {
            e.preventDefault();
            setError(null);
            try {
              await create.mutateAsync({ title, due_date: due || null, party_id: partyId || null });
              setTitle("");
              setDue("");
            } catch (err) {
              setError(errorMessage(err));
            }
          }}>
            <div className="min-w-[12rem] flex-1"><Input required placeholder="Add a task…" value={title} onChange={(e) => setTitle(e.target.value)} /></div>
            <div className="w-40"><Input type="date" value={due} onChange={(e) => setDue(e.target.value)} /></div>
            <div className="w-40">
              <Select value={partyId} onChange={(e) => setPartyId(e.target.value)}>
                <option value="">No contact</option>
                {parties.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </Select>
            </div>
            <Button type="submit" disabled={create.isPending}><Plus /> Add</Button>
          </form>
        )}
        <ErrorBanner message={error} />
        <Card>
          {isLoading ? <Loading /> : !list.length ? (
            <div className="p-6"><EmptyState title="No open tasks" /></div>
          ) : (
            <ul className="divide-y divide-slate-100 dark:divide-navy-700">
              {list.map((t) => {
                const overdue = !t.done && t.due_date && t.due_date < today();
                return (
                  <li key={t.id} className="flex items-center gap-3 px-4 py-3">
                    <input type="checkbox" className="h-4 w-4 accent-brand" checked={t.done} disabled={!canWrite} onChange={(e) => update.mutate({ id: t.id, done: e.target.checked })} />
                    <div className="min-w-0 flex-1">
                      <p className={`text-sm ${t.done ? "text-slate-400 line-through" : ""}`}>{t.title}</p>
                      <p className="text-xs text-slate-400">
                        {t.party_id && names.get(t.party_id)}
                        {t.due_date && <span className={overdue ? "ml-2 text-red-600" : "ml-2"}>Due {fmtDate(t.due_date)}</span>}
                      </p>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
