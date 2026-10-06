"use client";

import { useState } from "react";
import { CheckCircle2, Landmark, Link2, Upload, Wand2 } from "lucide-react";
import { Badge, Button, Card, EmptyState, ErrorBanner, Field, Input, Loading, Modal, Select, Table, Td, Th } from "@/components/om/primitives";
import { ImportModal } from "@/components/om/ImportModal";
import { errorMessage, useApi, useApiMutation } from "@/lib/api/query";
import { fmtDate, fmtMoney, humanize, num } from "@/lib/format";
import type { Account } from "@/lib/api/types";

interface BankAccount { id: string; code: string; name: string; book_balance: string; unmatched: number; last_statement_date: string | null }
interface StatementLine { id: string; date: string; description: string; reference: string; amount: string; status: "unmatched" | "matched" | "ignored" }
interface BookLine { id: string; date: string; entry_no: string; memo: string; amount: string; source_type: string }
interface Workspace {
  account: { id: string; code: string; name: string };
  book_balance: string;
  expected_statement_balance: string;
  unmatched_statement_total: string;
  unmatched_book_total: string;
  statement_lines: StatementLine[];
  book_lines: BookLine[];
}

const REFRESH = [["accounting"]];

export function BankingTab({ canWrite }: { canWrite: boolean }) {
  const { data: accounts, isLoading } = useApi<BankAccount[]>("/accounting/bank/accounts");
  const [openId, setOpenId] = useState<string | null>(null);

  if (openId) return <Reconcile accountId={openId} canWrite={canWrite} onBack={() => setOpenId(null)} />;
  return (
    <div className="space-y-4">
      <p className="max-w-3xl text-sm text-slate-500">
        Cash, M-Pesa and bank each have their own ledger. Import the statement from your bank or M-Pesa portal and match it against what&apos;s in your books —
        whatever is left over is what needs attention.
      </p>
      {isLoading ? <Loading /> : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {accounts?.map((a) => (
            <Card key={a.id} className="p-5">
              <div className="flex items-start justify-between">
                <div><p className="font-semibold">{a.name}</p><p className="font-mono text-xs text-slate-400">{a.code}</p></div>
                <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-50 text-brand"><Landmark className="h-4 w-4" /></span>
              </div>
              <p className="mt-4 text-2xl font-semibold tracking-tight">{fmtMoney(a.book_balance)}</p>
              <p className="text-xs text-slate-500">Balance in your books</p>
              <div className="mt-3 flex items-center justify-between text-xs">
                <span className="text-slate-500">{a.last_statement_date ? `Statement to ${fmtDate(a.last_statement_date)}` : "No statement imported"}</span>
                {a.unmatched > 0 ? <Badge tone="warning">{a.unmatched} to match</Badge> : a.last_statement_date ? <Badge tone="success">Reconciled</Badge> : null}
              </div>
              <Button variant="secondary" className="mt-4 w-full" onClick={() => setOpenId(a.id)}>Reconcile</Button>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

function Reconcile({ accountId, canWrite, onBack }: { accountId: string; canWrite: boolean; onBack: () => void }) {
  const { data, isLoading } = useApi<Workspace>(`/accounting/bank/${accountId}`);
  const { data: allAccounts } = useApi<Account[]>("/accounting/accounts");
  const autoMatch = useApiMutation<undefined, { matched: number }>("post", `/accounting/bank/${accountId}/auto-match`, REFRESH);
  const match = useApiMutation<{ id: string; journal_line_id: string }>("post", (b) => `/accounting/bank/lines/${b.id}/match`, REFRESH);
  const act = useApiMutation<{ id: string; verb: string }>("post", (b) => `/accounting/bank/lines/${b.id}/${b.verb}`, REFRESH);
  const createEntry = useApiMutation<{ id: string; account_id: string; memo: string }>("post", (b) => `/accounting/bank/lines/${b.id}/create-entry`, REFRESH);
  const [showImport, setShowImport] = useState(false);
  const [filter, setFilter] = useState("unmatched");
  const [selected, setSelected] = useState<StatementLine | null>(null);
  const [booking, setBooking] = useState<StatementLine | null>(null);
  const [offset, setOffset] = useState("");
  const [memo, setMemo] = useState("");
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

  if (isLoading || !data) return <Loading />;
  const lines = data.statement_lines.filter((l) => !filter || l.status === filter);
  const candidates = selected ? data.book_lines.filter((b) => num(b.amount) === num(selected.amount)) : data.book_lines;
  const reconciled = num(data.unmatched_statement_total) === 0 && data.statement_lines.length > 0;

  return (
    <div className="space-y-5">
      <button onClick={onBack} className="text-sm text-brand hover:underline">← All accounts</button>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">{data.account.name}</h2>
          <p className="text-sm text-slate-500">Match each statement line to the entry in your books.</p>
        </div>
        {canWrite && (
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => run(async () => { const r = await autoMatch.mutateAsync(undefined); setNotice(r.matched ? `Matched ${r.matched} line(s) automatically.` : "Nothing more could be matched automatically."); })}>
              <Wand2 /> Auto-match
            </Button>
            <Button onClick={() => setShowImport(true)}><Upload /> Import statement</Button>
          </div>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Tile label="Balance in your books" value={fmtMoney(data.book_balance)} />
        <Tile label="On statement, not in books" value={fmtMoney(data.unmatched_statement_total)} warn={num(data.unmatched_statement_total) !== 0} />
        <Tile label="In books, not on statement" value={fmtMoney(data.unmatched_book_total)} hint="Uncleared — or entered by mistake" />
        <Tile label="Statement should show" value={fmtMoney(data.expected_statement_balance)} hint="Compare with your bank's closing balance" />
      </div>
      {reconciled && <p className="flex items-center gap-2 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800"><CheckCircle2 className="h-4 w-4" /> Every statement line is accounted for.</p>}
      <ErrorBanner message={error} />
      {notice && <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{notice}</p>}

      <div className="grid gap-5 xl:grid-cols-2">
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold">Statement</h3>
            <div className="w-40">
              <Select value={filter} onChange={(e) => setFilter(e.target.value)}>
                <option value="unmatched">To match</option><option value="matched">Matched</option><option value="ignored">Ignored</option><option value="">All</option>
              </Select>
            </div>
          </div>
          <Card>
            {!data.statement_lines.length ? (
              <div className="p-6"><EmptyState icon={<Upload />} title="No statement yet" description="Download a CSV statement from your bank or M-Pesa portal and import it." /></div>
            ) : !lines.length ? <p className="p-6 text-sm text-slate-400">Nothing in this view.</p> : (
              <Table>
                <thead><tr><Th>Date</Th><Th>Details</Th><Th>Amount</Th><Th></Th></tr></thead>
                <tbody>
                  {lines.map((l) => (
                    <tr key={l.id} className={selected?.id === l.id ? "bg-brand-50" : ""}>
                      <Td className="whitespace-nowrap text-xs">{fmtDate(l.date)}</Td>
                      <Td><p>{l.description || "—"}</p>{l.reference && <p className="font-mono text-xs text-slate-400">{l.reference}</p>}</Td>
                      <Td className={num(l.amount) < 0 ? "text-red-600" : "text-emerald-700"}>{fmtMoney(l.amount)}</Td>
                      <Td>
                        {l.status === "unmatched" && canWrite ? (
                          <div className="flex justify-end gap-1">
                            <Button variant={selected?.id === l.id ? "primary" : "secondary"} className="px-2 py-1 text-xs" onClick={() => setSelected(selected?.id === l.id ? null : l)}><Link2 /> Match</Button>
                            <Button variant="secondary" className="px-2 py-1 text-xs" onClick={() => { setBooking(l); setMemo(l.description); setOffset(""); }}>Record</Button>
                            <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => run(() => act.mutateAsync({ id: l.id, verb: "ignore" }))}>Ignore</Button>
                          </div>
                        ) : l.status !== "unmatched" ? (
                          <div className="flex items-center justify-end gap-2">
                            <Badge tone={l.status === "matched" ? "success" : "neutral"}>{humanize(l.status)}</Badge>
                            {canWrite && <button className="text-xs text-slate-400 hover:text-navy-900" onClick={() => run(() => act.mutateAsync({ id: l.id, verb: "unmatch" }))}>Undo</button>}
                          </div>
                        ) : null}
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </Card>
        </div>

        <div className="space-y-2">
          <h3 className="flex h-10 items-center text-sm font-semibold">
            {selected ? `Pick the entry for ${fmtMoney(selected.amount)} (${fmtDate(selected.date)})` : "In your books, not yet on a statement"}
          </h3>
          <Card>
            {!candidates.length ? (
              <p className="p-6 text-sm text-slate-400">
                {selected ? "No entry in your books has this exact amount. Use “Record” if it's something new (a bank charge, interest, a deposit nobody entered)." : "Everything in your books has appeared on a statement."}
              </p>
            ) : (
              <Table>
                <thead><tr><Th>Date</Th><Th>Entry</Th><Th>Amount</Th><Th></Th></tr></thead>
                <tbody>
                  {candidates.map((b) => (
                    <tr key={b.id}>
                      <Td className="whitespace-nowrap text-xs">{fmtDate(b.date)}</Td>
                      <Td><p>{b.memo}</p><p className="font-mono text-xs text-slate-400">{b.entry_no} · {humanize(b.source_type)}</p></Td>
                      <Td className={num(b.amount) < 0 ? "text-red-600" : "text-emerald-700"}>{fmtMoney(b.amount)}</Td>
                      <Td>
                        {selected && (
                          <Button className="px-2 py-1 text-xs" onClick={() => run(async () => { await match.mutateAsync({ id: selected.id, journal_line_id: b.id }); setSelected(null); })}>
                            This one
                          </Button>
                        )}
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </Card>
        </div>
      </div>

      <ImportModal
        open={showImport}
        onClose={() => setShowImport(false)}
        title={`Import statement — ${data.account.name}`}
        endpoint={`/accounting/bank/${accountId}/import`}
        templatePath="/accounting/bank-statement-template"
        templateName="statement-template.csv"
        help="Upload the CSV your bank or M-Pesa portal gives you. It needs a date column and either one signed amount column or separate money-in / money-out columns (credit/debit, or paid in/withdrawn). Lines already imported are skipped, and anything that clearly matches your books is matched for you."
        invalidate={REFRESH}
      />

      <Modal open={!!booking} onClose={() => setBooking(null)} title="Record this statement line">
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (booking) run(async () => { await createEntry.mutateAsync({ id: booking.id, account_id: offset, memo }); setBooking(null); }); }}>
          <p className="text-sm text-slate-500">
            {booking && (num(booking.amount) < 0 ? `${fmtMoney(Math.abs(num(booking.amount)))} left this account` : `${fmtMoney(booking.amount)} came into this account`)} on {fmtDate(booking?.date)}. Choose what it was for — it&apos;s posted to your books and matched in one step.
          </p>
          <Field label="What was it?">
            <Select required value={offset} onChange={(e) => setOffset(e.target.value)}>
              <option value="">Choose an account…</option>
              {allAccounts?.filter((a) => a.is_active && a.id !== accountId).map((a) => <option key={a.id} value={a.id}>{a.code} · {a.name}</option>)}
            </Select>
          </Field>
          <Field label="Description"><Input value={memo} onChange={(e) => setMemo(e.target.value)} placeholder="e.g. Bank charges March" /></Field>
          <ErrorBanner message={error} />
          <div className="flex justify-end"><Button type="submit" disabled={createEntry.isPending}>Post & match</Button></div>
        </form>
      </Modal>
    </div>
  );
}

function Tile({ label, value, hint, warn }: { label: string; value: string; hint?: string; warn?: boolean }) {
  return (
    <div className={`rounded-xl p-4 ${warn ? "bg-amber-50" : "bg-white shadow-card ring-1 ring-slate-200/80"}`}>
      <p className="text-xs text-slate-500">{label}</p>
      <p className="mt-1 text-lg font-semibold">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-slate-400">{hint}</p>}
    </div>
  );
}
