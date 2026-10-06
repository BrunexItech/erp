"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { KeyRound, ShieldCheck, ShieldOff } from "lucide-react";
import { Badge, Button, Card, ErrorBanner, Field, Input } from "@/components/om/primitives";
import { errorMessage, useApi, useApiMutation } from "@/lib/api/query";
import { session } from "@/lib/session";

interface CurrentUser {
  email: string;
  totp_enabled: boolean;
}

export function SecurityTab() {
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <PasswordCard />
      <TwoFactorCard />
    </div>
  );
}

function PasswordCard() {
  const change = useApiMutation<Record<string, string>, { access_token: string; refresh_token: string }>("post", "/auth/change-password");
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  return (
    <Card className="p-6">
      <h2 className="flex items-center gap-2 text-sm font-semibold"><KeyRound className="h-4 w-4 text-brand" /> Change your password</h2>
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
            // The server signs out every other device and returns new tokens
            // for this one.
            const tokens = await change.mutateAsync({ current_password: current, new_password: next });
            session.setTokens(tokens.access_token, tokens.refresh_token);
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
        {done && <p className="text-sm text-emerald-600">Password changed. Other devices have been signed out.</p>}
        <Button type="submit" disabled={change.isPending}>Change password</Button>
      </form>
    </Card>
  );
}

function TwoFactorCard() {
  const qc = useQueryClient();
  const { data: user } = useApi<CurrentUser>("/auth/user");
  const setup = useApiMutation<undefined, { secret: string; qr_svg: string }>("post", "/auth/2fa/setup");
  const enable = useApiMutation<{ code: string }, { recovery_codes: string[] }>("post", "/auth/2fa/enable");
  const disable = useApiMutation<{ password: string }>("post", "/auth/2fa/disable");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [recovery, setRecovery] = useState<string[] | null>(null);
  const [turningOff, setTurningOff] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["auth"] });

  async function run(fn: () => Promise<unknown>) {
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <Card className="p-6">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-sm font-semibold"><ShieldCheck className="h-4 w-4 text-brand" /> Two-step sign-in</h2>
        <Badge tone={user?.totp_enabled ? "success" : "neutral"}>{user?.totp_enabled ? "On" : "Off"}</Badge>
      </div>
      <p className="mt-2 text-sm text-slate-500">
        After your password, sign-in also asks for a 6-digit code from an authenticator app on your phone (Google Authenticator, Microsoft Authenticator, Authy). A stolen password alone can&apos;t get in.
      </p>

      {recovery ? (
        <div className="mt-4 space-y-3">
          <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">Two-step sign-in is on.</p>
          <p className="text-sm font-medium">Save these recovery codes somewhere safe — they are shown only once.</p>
          <p className="text-xs text-slate-500">Each works one time in place of the 6-digit code if you lose your phone.</p>
          <div className="grid grid-cols-2 gap-2 rounded-xl bg-slate-50 p-4 font-mono text-sm dark:bg-navy-900">
            {recovery.map((c) => <span key={c}>{c}</span>)}
          </div>
          <Button variant="secondary" onClick={() => setRecovery(null)}>I&apos;ve saved them</Button>
        </div>
      ) : user?.totp_enabled ? (
        <div className="mt-4">
          {turningOff ? (
            <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); run(async () => { await disable.mutateAsync({ password }); setTurningOff(false); setPassword(""); refresh(); }); }}>
              <Field label="Confirm with your password"><Input type="password" required value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
              <div className="flex gap-2">
                <Button type="submit" variant="danger" disabled={disable.isPending}>Turn off</Button>
                <Button type="button" variant="secondary" onClick={() => setTurningOff(false)}>Cancel</Button>
              </div>
            </form>
          ) : (
            <Button variant="secondary" onClick={() => setTurningOff(true)}><ShieldOff /> Turn off two-step sign-in</Button>
          )}
        </div>
      ) : setup.data ? (
        <form className="mt-4 space-y-4" onSubmit={(e) => { e.preventDefault(); run(async () => { const r = await enable.mutateAsync({ code }); setRecovery(r.recovery_codes); setCode(""); setup.reset(); refresh(); }); }}>
          <p className="text-sm font-medium">1. Scan this with your authenticator app</p>
          <div className="flex flex-wrap items-center gap-4">
            <div className="rounded-xl bg-white p-2 ring-1 ring-slate-200 [&_svg]:h-44 [&_svg]:w-44" dangerouslySetInnerHTML={{ __html: setup.data.qr_svg }} />
            <div className="text-xs text-slate-500">
              <p>Can&apos;t scan? Enter this key by hand:</p>
              <p className="mt-1 break-all font-mono text-sm text-navy-900 dark:text-white">{setup.data.secret}</p>
            </div>
          </div>
          <Field label="2. Enter the 6-digit code it shows">
            <Input required inputMode="numeric" autoComplete="one-time-code" maxLength={7} placeholder="123 456" value={code} onChange={(e) => setCode(e.target.value)} />
          </Field>
          <Button type="submit" disabled={enable.isPending}>Turn on</Button>
        </form>
      ) : (
        <div className="mt-4"><Button onClick={() => run(() => setup.mutateAsync(undefined))} disabled={setup.isPending}>Set up two-step sign-in</Button></div>
      )}
      <div className="mt-4"><ErrorBanner message={error} /></div>
    </Card>
  );
}
