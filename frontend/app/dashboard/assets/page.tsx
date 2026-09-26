"use client";

import { useMemo, useState } from "react";
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
  PageHeader,
  Select,
  StatTile,
  Table,
  Td,
  Th,
} from "@/components/om/primitives";
import { useMe } from "@/lib/api/hooks";
import { errorMessage, useApi, useApiMutation } from "@/lib/api/query";
import { fmtDate, fmtMoney, humanize, MONTHS, num, today } from "@/lib/format";
import type { AssetCategory, FixedAsset } from "@/lib/api/types";

const REFRESH = [["assets"], ["accounting"]];
const STATUS_TONE: Record<string, "success" | "neutral" | "danger"> = { active: "success", fully_depreciated: "neutral", disposed: "danger" };

interface Register {
  assets: FixedAsset[];
  totals: { cost: string; accumulated_depreciation: string; net_book_value: string };
}

export default function AssetsPage() {
  const { data: me } = useMe();
  const canWrite = !!me && (me.permissions.includes("*") || me.permissions.includes("assets.write"));
  const { data: register, isLoading } = useApi<Register>("/assets/register");
  const { data: categories } = useApi<AssetCategory[]>("/assets/categories");
  const [showNew, setShowNew] = useState(false);
  const [showCategory, setShowCategory] = useState(false);
  const [showRun, setShowRun] = useState(false);
  const [scheduleFor, setScheduleFor] = useState<FixedAsset | null>(null);
  const [disposing, setDisposing] = useState<FixedAsset | null>(null);
  const categoryNames = useMemo(() => new Map((categories ?? []).map((c) => [c.id, c.name])), [categories]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Fixed Assets"
        description="Asset register, monthly depreciation and disposals — all posted to the general ledger."
        actions={
          canWrite && (
            <>
              <Button variant="secondary" onClick={() => setShowCategory(true)}>New category</Button>
              <Button variant="secondary" onClick={() => setShowRun(true)}>Run depreciation</Button>
              <Button onClick={() => setShowNew(true)}>Add asset</Button>
            </>
          )
        }
      />
      {register && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <StatTile label="Cost" value={fmtMoney(register.totals.cost)} />
          <StatTile label="Accumulated depreciation" value={fmtMoney(register.totals.accumulated_depreciation)} />
          <StatTile label="Net book value" value={fmtMoney(register.totals.net_book_value)} />
        </div>
      )}
      <Card>
        {isLoading ? <Loading /> : !register?.assets.length ? (
          <div className="p-6"><EmptyState title="No assets registered" description="Record vehicles, equipment, furniture and computers to depreciate them automatically." /></div>
        ) : (
          <Table>
            <thead>
              <tr><Th>No.</Th><Th>Asset</Th><Th>Category</Th><Th>Acquired</Th><Th>Method</Th><Th>Cost</Th><Th>Acc. dep.</Th><Th>NBV</Th><Th>Status</Th><Th></Th></tr>
            </thead>
            <tbody>
              {register.assets.map((a) => (
                <tr key={a.id}>
                  <Td className="font-mono text-xs">{a.asset_no}</Td>
                  <Td>
                    <p className="font-medium">{a.name}</p>
                    <p className="text-xs text-slate-400">{[a.serial_number, a.location, a.custodian].filter(Boolean).join(" · ")}</p>
                  </Td>
                  <Td>{categoryNames.get(a.category_id ?? "") ?? "—"}</Td>
                  <Td>{fmtDate(a.acquisition_date)}</Td>
                  <Td className="text-xs">
                    {a.method === "straight_line" ? `SL ${a.useful_life_months} mo` : `RB ${num(a.annual_rate) * 100}%`}
                  </Td>
                  <Td className="tabular-nums">{fmtMoney(a.cost)}</Td>
                  <Td className="tabular-nums">{fmtMoney(a.accumulated_depreciation)}</Td>
                  <Td className="tabular-nums font-medium">{fmtMoney(a.status === "disposed" ? 0 : a.net_book_value)}</Td>
                  <Td><Badge tone={STATUS_TONE[a.status]}>{humanize(a.status)}</Badge></Td>
                  <Td>
                    <div className="flex justify-end gap-1">
                      <Button variant="secondary" className="px-2 py-1 text-xs" onClick={() => setScheduleFor(a)}>Schedule</Button>
                      {canWrite && a.status !== "disposed" && (
                        <Button variant="secondary" className="px-2 py-1 text-xs" onClick={() => setDisposing(a)}>Dispose</Button>
                      )}
                    </div>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      {showNew && <AssetForm categories={categories ?? []} onClose={() => setShowNew(false)} />}
      {showCategory && <CategoryForm onClose={() => setShowCategory(false)} />}
      {showRun && <DepreciationRun onClose={() => setShowRun(false)} />}
      {scheduleFor && <Schedule asset={scheduleFor} onClose={() => setScheduleFor(null)} />}
      {disposing && <Disposal asset={disposing} onClose={() => setDisposing(null)} />}
    </div>
  );
}

function AssetForm({ categories, onClose }: { categories: AssetCategory[]; onClose: () => void }) {
  const create = useApiMutation("post", "/assets", REFRESH);
  const [f, setF] = useState({
    name: "", category_id: "", serial_number: "", location: "", custodian: "", acquisition_date: today(),
    cost: "", salvage_value: "0", method: "", useful_life_months: "", annual_rate: "", funding: "cash",
    opening_accumulated_depreciation: "0",
  });
  const [error, setError] = useState<string | null>(null);
  const bind = (k: keyof typeof f) => ({ value: f[k], onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value }) });
  const category = categories.find((c) => c.id === f.category_id);
  const method = f.method || category?.method || "straight_line";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await create.mutateAsync({
        name: f.name,
        category_id: f.category_id || null,
        serial_number: f.serial_number,
        location: f.location,
        custodian: f.custodian,
        acquisition_date: f.acquisition_date,
        cost: f.cost,
        salvage_value: f.salvage_value || "0",
        method: f.method || null,
        useful_life_months: f.useful_life_months ? Number(f.useful_life_months) : null,
        annual_rate: f.annual_rate ? String(num(f.annual_rate) / 100) : null,
        funding: f.funding,
        opening_accumulated_depreciation: f.funding === "opening" ? f.opening_accumulated_depreciation || "0" : "0",
      });
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <Modal open onClose={onClose} title="Add asset" wide>
      <form onSubmit={submit} className="space-y-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div className="sm:col-span-2"><Field label="Name"><Input required {...bind("name")} placeholder="e.g. Toyota Probox KDA 123X" /></Field></div>
          <Field label="Category">
            <Select {...bind("category_id")}>
              <option value="">—</option>
              {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </Select>
          </Field>
          <Field label="Serial / reg. no."><Input {...bind("serial_number")} /></Field>
          <Field label="Location"><Input {...bind("location")} /></Field>
          <Field label="Custodian"><Input {...bind("custodian")} /></Field>
          <Field label="Acquisition date"><Input type="date" required {...bind("acquisition_date")} /></Field>
          <Field label="Cost"><Input type="number" step="0.01" min="0.01" required {...bind("cost")} /></Field>
          <Field label="Salvage value"><Input type="number" step="0.01" min="0" {...bind("salvage_value")} /></Field>
          <Field label="Depreciation method" hint={category ? `Category default: ${humanize(category.method)}` : undefined}>
            <Select {...bind("method")}>
              <option value="">{category ? "Use category default" : "Straight line"}</option>
              <option value="straight_line">Straight line</option>
              <option value="declining_balance">Reducing balance</option>
            </Select>
          </Field>
          {method === "straight_line" ? (
            <Field label="Useful life (months)" hint={category ? `Default ${category.useful_life_months}` : "Default 60"}>
              <Input type="number" min="1" {...bind("useful_life_months")} />
            </Field>
          ) : (
            <Field label="Annual rate %" hint={category ? `Default ${num(category.annual_rate) * 100}%` : undefined}>
              <Input type="number" step="0.01" min="0" max="100" {...bind("annual_rate")} />
            </Field>
          )}
          <Field label="Paid with">
            <Select {...bind("funding")}>
              <option value="cash">Cash / bank</option>
              <option value="payable">On credit (accounts payable)</option>
              <option value="opening">Already owned at go-live</option>
            </Select>
          </Field>
          {f.funding === "opening" && (
            <Field label="Depreciation to date"><Input type="number" step="0.01" min="0" {...bind("opening_accumulated_depreciation")} /></Field>
          )}
        </div>
        <ErrorBanner message={error} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={create.isPending}>Add asset</Button>
        </div>
      </form>
    </Modal>
  );
}

function CategoryForm({ onClose }: { onClose: () => void }) {
  const create = useApiMutation("post", "/assets/categories", REFRESH);
  const [name, setName] = useState("");
  const [method, setMethod] = useState("straight_line");
  const [life, setLife] = useState("60");
  const [rate, setRate] = useState("25");
  const [error, setError] = useState<string | null>(null);
  return (
    <Modal open onClose={onClose} title="New asset category">
      <form
        className="space-y-3"
        onSubmit={async (e) => {
          e.preventDefault();
          setError(null);
          try {
            await create.mutateAsync({ name, method, useful_life_months: Number(life), annual_rate: method === "declining_balance" ? String(num(rate) / 100) : "0" });
            onClose();
          } catch (err) {
            setError(errorMessage(err));
          }
        }}
      >
        <Field label="Name"><Input required value={name} onChange={(e) => setName(e.target.value)} placeholder="Motor vehicles" /></Field>
        <Field label="Method">
          <Select value={method} onChange={(e) => setMethod(e.target.value)}>
            <option value="straight_line">Straight line</option>
            <option value="declining_balance">Reducing balance</option>
          </Select>
        </Field>
        {method === "straight_line" ? (
          <Field label="Useful life (months)"><Input type="number" min="1" value={life} onChange={(e) => setLife(e.target.value)} /></Field>
        ) : (
          <Field label="Annual rate %"><Input type="number" step="0.01" value={rate} onChange={(e) => setRate(e.target.value)} /></Field>
        )}
        <ErrorBanner message={error} />
        <div className="flex justify-end"><Button type="submit" disabled={create.isPending}>Create</Button></div>
      </form>
    </Modal>
  );
}

function DepreciationRun({ onClose }: { onClose: () => void }) {
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const run = useApiMutation<Record<string, number>, { assets_charged: number; total: string }>("post", "/assets/depreciation-runs", REFRESH);
  const [error, setError] = useState<string | null>(null);
  return (
    <Modal open onClose={onClose} title="Month-end depreciation">
      <form
        className="space-y-3"
        onSubmit={async (e) => {
          e.preventDefault();
          setError(null);
          try {
            await run.mutateAsync({ year, month });
          } catch (err) {
            setError(errorMessage(err));
          }
        }}
      >
        <p className="text-sm text-slate-500">Charges every active asset through the end of the chosen month (catching up any skipped months) as one journal entry. Running it twice does nothing extra.</p>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Month">
            <Select value={month} onChange={(e) => setMonth(Number(e.target.value))}>
              {MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
            </Select>
          </Field>
          <Field label="Year"><Input type="number" value={year} onChange={(e) => setYear(Number(e.target.value))} /></Field>
        </div>
        <ErrorBanner message={error} />
        {run.data && (
          <p className="text-sm text-emerald-600">
            {run.data.assets_charged ? `Posted ${fmtMoney(run.data.total)} across ${run.data.assets_charged} asset(s).` : "Nothing new to charge for that period."}
          </p>
        )}
        <div className="flex justify-end"><Button type="submit" disabled={run.isPending}>Run depreciation</Button></div>
      </form>
    </Modal>
  );
}

function Schedule({ asset, onClose }: { asset: FixedAsset; onClose: () => void }) {
  const { data, isLoading } = useApi<{ rows: { period: string; charge: string; accumulated: string; net_book_value: string; posted: boolean }[] }>(
    `/assets/${asset.id}/schedule`
  );
  return (
    <Modal open onClose={onClose} title={`Depreciation schedule — ${asset.name}`} wide>
      {isLoading || !data ? <Loading /> : !data.rows.length ? (
        <EmptyState title="No depreciation" />
      ) : (
        <div className="max-h-[60vh] overflow-y-auto">
          <Table>
            <thead><tr><Th>Period</Th><Th>Charge</Th><Th>Accumulated</Th><Th>Net book value</Th><Th></Th></tr></thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={r.period} className={r.posted ? "" : "text-slate-400"}>
                  <Td>{r.period}</Td>
                  <Td className="tabular-nums">{fmtMoney(r.charge)}</Td>
                  <Td className="tabular-nums">{fmtMoney(r.accumulated)}</Td>
                  <Td className="tabular-nums">{fmtMoney(r.net_book_value)}</Td>
                  <Td>{r.posted ? <Badge tone="success">Posted</Badge> : <span className="text-xs">Projected</span>}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
      )}
    </Modal>
  );
}

function Disposal({ asset, onClose }: { asset: FixedAsset; onClose: () => void }) {
  const dispose = useApiMutation("post", `/assets/${asset.id}/dispose`, REFRESH);
  const [date, setDate] = useState(today());
  const [proceeds, setProceeds] = useState("0");
  const [error, setError] = useState<string | null>(null);
  return (
    <Modal open onClose={onClose} title={`Dispose ${asset.name}`}>
      <form
        className="space-y-3"
        onSubmit={async (e) => {
          e.preventDefault();
          setError(null);
          try {
            await dispose.mutateAsync({ disposal_date: date, proceeds });
            onClose();
          } catch (err) {
            setError(errorMessage(err));
          }
        }}
      >
        <p className="text-sm text-slate-500">
          Depreciation is charged up to the month before disposal. The difference between sale proceeds and net book value
          ({fmtMoney(asset.net_book_value)} today) is posted as a gain or loss.
        </p>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Disposal date"><Input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field>
          <Field label="Sale proceeds"><Input type="number" step="0.01" min="0" value={proceeds} onChange={(e) => setProceeds(e.target.value)} /></Field>
        </div>
        <ErrorBanner message={error} />
        <div className="flex justify-end"><Button type="submit" variant="danger" disabled={dispose.isPending}>Dispose asset</Button></div>
      </form>
    </Modal>
  );
}
