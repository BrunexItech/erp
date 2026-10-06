"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AuthLayout } from "@/components/auth/AuthLayout";
import { Button, ErrorBanner, Input, Label } from "@/components/om/primitives";
import { http } from "@/lib/api/http";
import { errorMessage } from "@/lib/api/query";

export default function ResetPasswordPage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Read from the address bar on the client (keeps this page statically built).
  useEffect(() => setToken(new URLSearchParams(window.location.search).get("token") ?? ""), []);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (password !== again) {
      setError("The two passwords don't match.");
      return;
    }
    setBusy(true);
    try {
      await http.post("/auth/reset-password", { token, password }, { workspaceScoped: false, skipRetry: true });
      setDone(true);
      setTimeout(() => router.push("/login"), 2500);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout>
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-navy-900">Choose a new password</h1>
        {token === "" ? (
          <p className="mt-3 text-sm text-slate-500">
            This link is incomplete. <Link href="/forgot-password" className="font-medium text-brand hover:underline">Request a new one</Link>.
          </p>
        ) : done ? (
          <p className="mt-3 text-sm text-emerald-700">Password changed. Taking you to sign in…</p>
        ) : (
          <form onSubmit={onSubmit} className="mt-6 space-y-4">
            <div>
              <Label>New password</Label>
              <Input type="password" required minLength={8} autoFocus autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
              <p className="mt-1 text-xs text-slate-400">At least 8 characters, mixing letters with numbers or symbols.</p>
            </div>
            <div>
              <Label>Repeat password</Label>
              <Input type="password" required autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} />
            </div>
            <ErrorBanner message={error} />
            <Button type="submit" className="w-full py-2.5" disabled={busy || token === null}>{busy ? "Saving…" : "Set new password"}</Button>
          </form>
        )}
      </div>
    </AuthLayout>
  );
}
