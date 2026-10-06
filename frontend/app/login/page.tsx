"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { http, ApiError } from "@/lib/api/http";
import { session } from "@/lib/session";
import { Button, ErrorBanner, Input, Label } from "@/components/om/primitives";
import { AuthLayout } from "@/components/auth/AuthLayout";
import type { Workspace } from "@/lib/api/types";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [needsCode, setNeedsCode] = useState(false);
  const [code, setCode] = useState("");

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const tokens = await http.post<{ access_token: string; refresh_token: string }>(
        "/auth/login",
        { email, password, totp_code: needsCode ? code : null },
        { workspaceScoped: false, skipRetry: true }
      );
      session.setTokens(tokens.access_token, tokens.refresh_token);

      const workspaces = await http.get<Workspace[]>("/workspaces", { workspaceScoped: false });
      if (workspaces.length > 0) {
        session.setWorkspaceId(workspaces[0].id);
      }
      router.push("/dashboard");
    } catch (err) {
      if (err instanceof ApiError && err.detail === "totp_required") {
        setNeedsCode(true); // password accepted — now ask for the phone code
      } else {
        setError(err instanceof ApiError ? String(err.detail) : "Login failed");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthLayout>
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-navy-900 dark:text-white">Sign in</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">Welcome back to your ERP.</p>

        <form onSubmit={onSubmit} className="mt-6 space-y-4">
          <div>
            <Label>Email</Label>
            <Input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div>
            <div className="flex items-center justify-between">
              <Label>Password</Label>
              <Link href="/forgot-password" className="mb-1.5 text-xs font-medium text-brand hover:underline">Forgot password?</Link>
            </div>
            <Input type="password" required value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
          {needsCode && (
            <div>
              <Label>6-digit code from your authenticator app</Label>
              <Input required autoFocus inputMode="numeric" autoComplete="one-time-code" placeholder="123 456" value={code} onChange={(e) => setCode(e.target.value)} />
              <p className="mt-1 text-xs text-slate-400">Lost your phone? Enter one of your recovery codes instead.</p>
            </div>
          )}
          <ErrorBanner message={error} />
          <Button type="submit" className="w-full py-2.5" disabled={loading}>
            {loading ? "Signing in…" : "Sign in"}
          </Button>
        </form>

        <p className="mt-6 text-center text-sm text-slate-500 dark:text-slate-400">
          No account?{" "}
          <Link href="/signup" className="font-medium text-brand hover:underline">
            Create one
          </Link>
        </p>
      </div>
    </AuthLayout>
  );
}
