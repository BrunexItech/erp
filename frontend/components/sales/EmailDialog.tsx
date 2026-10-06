"use client";

import { useState } from "react";
import { Send } from "lucide-react";
import { Button, ErrorBanner, Field, Input, Modal, Textarea } from "@/components/om/primitives";
import { errorMessage, useApiMutation } from "@/lib/api/query";

interface Result {
  to: string;
  delivered: boolean;
}

/** Email an invoice / quote / statement as a PDF. Leaving "To" blank sends to
 * the customer's email on file. */
export function EmailDialog({
  open,
  onClose,
  title,
  endpoint,
  extra,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  endpoint: string;
  extra?: Record<string, unknown>;
}) {
  const send = useApiMutation<Record<string, unknown>, Result>("post", endpoint, [["sales"]]);
  const [to, setTo] = useState("");
  const [cc, setCc] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Result | null>(null);

  function close() {
    setResult(null);
    setError(null);
    onClose();
  }

  return (
    <Modal open={open} onClose={close} title={title}>
      {result ? (
        <div className="space-y-4">
          <p className={`rounded-lg px-3 py-2.5 text-sm ${result.delivered ? "bg-emerald-50 text-emerald-800" : "bg-amber-50 text-amber-900"}`}>
            {result.delivered
              ? `Sent to ${result.to}.`
              : `Outgoing email isn't configured on this server yet, so nothing was delivered. The message to ${result.to} was saved to the outbox — ask your administrator to set up SMTP.`}
          </p>
          <div className="flex justify-end"><Button onClick={close}>Done</Button></div>
        </div>
      ) : (
        <form
          className="space-y-3"
          onSubmit={async (e) => {
            e.preventDefault();
            setError(null);
            try {
              setResult(
                await send.mutateAsync({
                  to: to.trim() || null,
                  cc: cc.split(/[,;\s]+/).filter(Boolean),
                  message,
                  ...extra,
                })
              );
            } catch (err) {
              setError(errorMessage(err));
            }
          }}
        >
          <Field label="To" hint="Leave blank to use the customer's email on file">
            <Input type="email" value={to} onChange={(e) => setTo(e.target.value)} placeholder="customer@example.com" />
          </Field>
          <Field label="CC (optional)"><Input value={cc} onChange={(e) => setCc(e.target.value)} placeholder="Separate addresses with commas" /></Field>
          <Field label="Message (optional)">
            <Textarea value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Added above the standard wording. The PDF is attached automatically." />
          </Field>
          <ErrorBanner message={error} />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={close}>Cancel</Button>
            <Button type="submit" disabled={send.isPending}><Send /> {send.isPending ? "Sending…" : "Send"}</Button>
          </div>
        </form>
      )}
    </Modal>
  );
}
