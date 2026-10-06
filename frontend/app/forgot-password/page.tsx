"use client";

import Link from "next/link";
import { useState } from "react";
import { MailCheck } from "lucide-react";
import { AuthLayout } from "@/components/auth/AuthLayout";
import { Button, ErrorBanner, Input, Label } from "@/components/om/primitives";
import { http } from "@/lib/api/http";
import { errorMessage } from "@/lib/api/query";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await http.post("/auth/forgot-password", { email }, { workspaceScoped: false, skipRetry: true });
      setSent(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout>
      {sent ? (
        <div>
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-emerald-50 text-emerald-600"><MailCheck className="h-6 w-6" /></span>
          <h1 className="mt-4 text-2xl font-semibold tracking-tight text-navy-900">Check your email</h1>
          <p className="mt-2 text-sm text-slate-500">
            If <b>{email}</b> has an account, we&apos;ve sent a link to choose a new password. It works once and expires in 2 hours.
          </p>
          <Link href="/login" className="mt-6 inline-block text-sm font-medium text-brand hover:underline">Back to sign in</Link>
        </div>
      ) : (
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-navy-900">Forgot your password?</h1>
          <p className="mt-1 text-sm text-slate-500">Enter your email and we&apos;ll send you a link to reset it.</p>
          <form onSubmit={onSubmit} className="mt-6 space-y-4">
            <div>
              <Label>Email</Label>
              <Input type="email" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <ErrorBanner message={error} />
            <Button type="submit" className="w-full py-2.5" disabled={busy}>{busy ? "Sending…" : "Send reset link"}</Button>
          </form>
          <p className="mt-6 text-center text-sm text-slate-500"><Link href="/login" className="font-medium text-brand hover:underline">Back to sign in</Link></p>
        </div>
      )}
    </AuthLayout>
  );
}
