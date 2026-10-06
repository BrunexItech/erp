"use client";

import { useState } from "react";
import { Button, Card, ErrorBanner, Field, Input } from "@/components/om/primitives";
import { errorMessage, useApiMutation } from "@/lib/api/query";

export function SecurityTab() {
  const change = useApiMutation("post", "/auth/change-password");
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  return (
    <Card className="max-w-lg p-6">
      <h2 className="text-sm font-semibold text-brand">Change your password</h2>
      <form
        className="mt-4 space-y-4"
        onSubmit={async (e) => {
          e.preventDefault();
          setError(null);
          setDone(false);
          if (next !== again) {
            setError("The two new passwords don't match.");
            return;
          }
          try {
            await change.mutateAsync({ current_password: current, new_password: next });
            setDone(true);
            setCurrent("");
            setNext("");
            setAgain("");
          } catch (err) {
            setError(errorMessage(err));
          }
        }}
      >
        <Field label="Current password"><Input type="password" required autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} /></Field>
        <Field label="New password" hint="At least 8 characters, mixing letters with numbers or symbols">
          <Input type="password" required minLength={8} autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
        </Field>
        <Field label="Repeat new password"><Input type="password" required autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} /></Field>
        <ErrorBanner message={error} />
        {done && <p className="text-sm text-emerald-600">Password changed.</p>}
        <Button type="submit" disabled={change.isPending}>Change password</Button>
      </form>
    </Card>
  );
}
