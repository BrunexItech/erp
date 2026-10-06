"use client";

import { useState } from "react";
import { Button, ErrorBanner, Field, Input, Modal, Select, Textarea } from "@/components/om/primitives";
import { errorMessage, useApiMutation } from "@/lib/api/query";
import { useBranding, useParties, useProducts, useWarehouses } from "@/lib/api/hooks";
import { today } from "@/lib/format";
import { emptyLine, LineDraft, LineItemsEditor, toPayloadLines } from "./LineItemsEditor";

/** New invoice or quotation — same line-item builder, different endpoint. */
export function DocumentFormModal({
  kind,
  open,
  onClose,
  onCreated,
  currency,
}: {
  kind: "invoice" | "quote";
  open: boolean;
  onClose: () => void;
  onCreated?: (id: string) => void;
  currency?: string;
}) {
  const { data: parties } = useParties();
  const { data: products } = useProducts();
  const { data: warehouses } = useWarehouses();
  const { data: branding } = useBranding();
  const inclusive = !!branding?.prices_include_tax;
  const create = useApiMutation<Record<string, unknown>, { id: string }>(
    "post",
    kind === "invoice" ? "/sales/invoices" : "/sales/quotes",
    [["sales"], ["accounting"], ["inventory"]]
  );

  const [partyId, setPartyId] = useState("");
  const [issueDate, setIssueDate] = useState(today());
  const [secondDate, setSecondDate] = useState("");
  const [reference, setReference] = useState("");
  const [warehouseId, setWarehouseId] = useState("");
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<LineDraft[]>([emptyLine()]);
  const [error, setError] = useState<string | null>(null);

  const customers = parties?.filter((p) => p.kind !== "vendor") ?? [];
  const hasProductLines = lines.some((l) => l.product_id);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const payloadLines = toPayloadLines(lines);
    if (!payloadLines.length) {
      setError("Add at least one line with a product or description.");
      return;
    }
    const body: Record<string, unknown> = {
      party_id: partyId,
      issue_date: issueDate,
      reference,
      notes,
      lines: payloadLines,
    };
    if (kind === "invoice") {
      if (secondDate) body.due_date = secondDate;
      if (warehouseId) body.warehouse_id = warehouseId;
    } else if (secondDate) {
      body.valid_until = secondDate;
    }
    try {
      const created = await create.mutateAsync(body);
      setLines([emptyLine()]);
      setPartyId("");
      setReference("");
      setNotes("");
      setWarehouseId("");
      onCreated?.(created.id);
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <Modal open={open} onClose={onClose} title={kind === "invoice" ? "New invoice" : "New quotation"} wide>
      <form onSubmit={submit} className="space-y-5">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
          <div className="sm:col-span-2">
            <Field label="Customer">
              <Select required value={partyId} onChange={(e) => setPartyId(e.target.value)}>
                <option value="">Select a customer…</option>
                {customers.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </Select>
            </Field>
          </div>
          <Field label={kind === "invoice" ? "Invoice date" : "Quote date"}>
            <Input type="date" value={issueDate} onChange={(e) => setIssueDate(e.target.value)} />
          </Field>
          <Field label={kind === "invoice" ? "Due date" : "Valid until"} hint={kind === "invoice" ? "Blank = customer's terms" : "Blank = 30 days"}>
            <Input type="date" value={secondDate} onChange={(e) => setSecondDate(e.target.value)} />
          </Field>
          <div className="sm:col-span-2">
            <Field label="Reference (customer LPO / PO)">
              <Input value={reference} onChange={(e) => setReference(e.target.value)} />
            </Field>
          </div>
          {kind === "invoice" && hasProductLines && (
            <div className="sm:col-span-2">
              <Field label="Ship goods now from" hint="Deducts stock and posts COGS; leave empty if already delivered">
                <Select value={warehouseId} onChange={(e) => setWarehouseId(e.target.value)}>
                  <option value="">Don't move stock</option>
                  {warehouses?.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
                </Select>
              </Field>
            </div>
          )}
        </div>

        <LineItemsEditor lines={lines} onChange={setLines} products={products ?? []} currency={currency} inclusive={inclusive} />
        {inclusive && <p className="-mt-2 text-xs text-slate-500">Prices you type include VAT — change this under Settings → Company & documents.</p>}

        <Field label="Notes (printed on the document)">
          <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} />
        </Field>

        <ErrorBanner message={error} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={create.isPending}>
            {create.isPending ? "Saving…" : kind === "invoice" ? "Create invoice" : "Create quote"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
