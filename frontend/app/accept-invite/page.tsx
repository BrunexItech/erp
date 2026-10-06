"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AuthLayout } from "@/components/auth/AuthLayout";
import { Button, ErrorBanner, Input, Label } from "@/components/om/primitives";
import { http } from "@/lib/api/http";
import { errorMessage } from "@/lib/api/query";
import { session } from "@/lib/session";
import type { Workspace } from "@/lib/api/types";

interface InvitationInfo {
  email: string;
  workspace_name: string;
  role: string | null;
  has_account: boolean;
}

export default function AcceptInvitePage() {
  const router = useRouter();
  const [token, setToken] = useState("");
  const [info, setInfo] = useState<InvitationInfo | null>(null);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [invalid, setInvalid] = useState(false);

  useEffect(() => {
    const value = new URLSearchParams(window.location.search).get("token") ?? "";
    setToken(value);
    if (!value) {
      setInvalid(true);
      return;
    }
    http
      .get<InvitationInfo>(`/auth/invitations/${encodeURIComponent(value)}`, { workspaceScoped: false, skipRetry: true })
      .then(setInfo)
      .catch(() => setInvalid(true));
  }, []);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const tokens = await http.post<{ access_token: string; refresh_token: string }>(
        "/auth/accept-invite",
        { token, full_name: name, password },
        { workspaceScoped: false, skipRetry: true }
      );
      session.setTokens(tokens.access_token, tokens.refresh_token);
      const workspaces = await http.get<Workspace[]>("/workspaces", { workspaceScoped: false });
      const joined = workspaces.find((w) => w.name === info?.workspace_name) ?? workspaces[0];
      if (joined) session.setWorkspaceId(joined.id);
      router.push("/dashboard");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout>
      {invalid ? (
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-navy-900">This invitation isn&apos;t valid</h1>
          <p className="mt-2 text-sm text-slate-500">It may have expired, been cancelled, or already been used. Ask whoever invited you to send a new one.</p>
          <Link href="/login" className="mt-6 inline-block text-sm font-medium text-brand hover:underline">Go to sign in</Link>
        </div>
      ) : !info ? (
        <p className="text-sm text-slate-400">Checking your invitation…</p>
      ) : (
        <div>
          <p className="text-sm font-medium text-brand">You&apos;re invited</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-navy-900">Join {info.workspace_name}</h1>
          <p className="mt-1 text-sm text-slate-500">
            as <b className="capitalize">{info.role}</b> · {info.email}
          </p>
          <form onSubmit={onSubmit} className="mt-6 space-y-4">
            {!info.has_account && (
              <div>
                <Label>Your full name</Label>
                <Input required autoFocus value={name} onChange={(e) => setName(e.target.value)} />
              </div>
            )}
            <div>
              <Label>{info.has_account ? "Your existing password" : "Choose a password"}</Label>
              <Input type="password" required minLength={info.has_account ? undefined : 8} autoComplete={info.has_account ? "current-password" : "new-password"} value={password} onChange={(e) => setPassword(e.target.value)} />
              <p className="mt-1 text-xs text-slate-400">
                {info.has_account ? "This email already has an account — sign in with its password to join." : "At least 8 characters, mixing letters with numbers or symbols."}
              </p>
            </div>
            <ErrorBanner message={error} />
            <Button type="submit" className="w-full py-2.5" disabled={busy}>{busy ? "Joining…" : `Join ${info.workspace_name}`}</Button>
          </form>
        </div>
      )}
    </AuthLayout>
  );
}
