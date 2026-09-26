"use client";

import { useState } from "react";
import { useCreateParty, useParties } from "@/lib/api/hooks";
import { Button, Card, EmptyState, Input, Label, Select, Table, Td, Th, Badge } from "@/components/om/primitives";
import type { Party } from "@/lib/api/types";

const KIND_TONE: Record<Party["kind"], "neutral" | "success" | "warning"> = {
  lead: "warning",
  customer: "success",
  vendor: "neutral",
  both: "success",
};

export default function CrmPage() {
  const { data: parties, isLoading } = useParties();
  const createParty = useCreateParty();
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [kind, setKind] = useState<Party["kind"]>("lead");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    await createParty.mutateAsync({ name, kind, email: email || null, phone: phone || null });
    setName("");
    setEmail("");
    setPhone("");
    setShowForm(false);
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-navy-900 dark:text-white">CRM</h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">Contacts, leads, customers and vendors.</p>
        </div>
        <Button onClick={() => setShowForm((v) => !v)}>{showForm ? "Cancel" : "Add contact"}</Button>
      </div>

      {showForm && (
        <Card className="p-6">
          <form onSubmit={onSubmit} className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <Label>Name</Label>
              <Input required value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div>
              <Label>Kind</Label>
              <Select value={kind} onChange={(e) => setKind(e.target.value as Party["kind"])}>
                <option value="lead">Lead</option>
                <option value="customer">Customer</option>
                <option value="vendor">Vendor</option>
                <option value="both">Both</option>
              </Select>
            </div>
            <div>
              <Label>Email</Label>
              <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div>
              <Label>Phone</Label>
              <Input value={phone} onChange={(e) => setPhone(e.target.value)} />
            </div>
            <div className="sm:col-span-2">
              <Button type="submit" disabled={createParty.isPending}>
                {createParty.isPending ? "Saving…" : "Save contact"}
              </Button>
            </div>
          </form>
        </Card>
      )}

      <Card>
        {isLoading ? (
          <p className="p-6 text-sm text-slate-400">Loading…</p>
        ) : !parties?.length ? (
          <div className="p-6">
            <EmptyState title="No contacts yet" description="Add your first lead, customer or vendor." />
          </div>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Name</Th>
                <Th>Kind</Th>
                <Th>Email</Th>
                <Th>Phone</Th>
              </tr>
            </thead>
            <tbody>
              {parties.map((p) => (
                <tr key={p.id}>
                  <Td>{p.name}</Td>
                  <Td>
                    <Badge tone={KIND_TONE[p.kind]}>{p.kind}</Badge>
                  </Td>
                  <Td>{p.email ?? "—"}</Td>
                  <Td>{p.phone ?? "—"}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}
