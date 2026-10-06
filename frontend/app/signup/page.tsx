"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { http, ApiError } from "@/lib/api/http";
import { session } from "@/lib/session";
import { Button, ErrorBanner, Input, Label } from "@/components/om/primitives";
import { AuthLayout } from "@/components/auth/AuthLayout";
import type { Workspace } from "@/lib/api/types";

export default function SignupPage() {
  const router = useRouter();
  const [fullName, setFullName] = useState("");
  const [workspaceName, setWorkspaceName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const tokens = await http.post<{ access_token: string; refresh_token: string }>(
        "/auth/signup",
        { email, password, full_name: fullName, workspace_name: workspaceName },
        { workspaceScoped: false }
      );
      session.setTokens(tokens.access_token, tokens.refresh_token);

      const workspaces = await http.get<Workspace[]>("/workspaces", { workspaceScoped: false });
      if (workspaces.length > 0) {
        session.setWorkspaceId(workspaces[0].id);
      }
      router.push("/onboarding");
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : "Sign up failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthLayout>
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-navy-900 dark:text-white">Create your workspace</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">Start on the Starter package — upgrade anytime.</p>

        <form onSubmit={onSubmit} className="mt-6 space-y-4">
          <div>
            <Label>Company / workspace name</Label>
            <Input required value={workspaceName} onChange={(e) => setWorkspaceName(e.target.value)} />
          </div>
          <div>
            <Label>Your full name</Label>
            <Input required value={fullName} onChange={(e) => setFullName(e.target.value)} />
          </div>
          <div>
            <Label>Email</Label>
            <Input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div>
            <Label>Password</Label>
            <Input type="password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
          <ErrorBanner message={error} />
          <Button type="submit" className="w-full py-2.5" disabled={loading}>
            {loading ? "Creating…" : "Create workspace"}
          </Button>
        </form>

        <p className="mt-6 text-center text-sm text-slate-500 dark:text-slate-400">
          Already have an account?{" "}
          <Link href="/login" className="font-medium text-brand hover:underline">
            Sign in
          </Link>
        </p>
      </div>
    </AuthLayout>
  );
}
