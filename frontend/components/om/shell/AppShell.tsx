"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { LogOut, Menu, Search, ShieldCheck, X } from "lucide-react";
import { useBranding, useMe } from "@/lib/api/hooks";
import { mediaUrl } from "@/lib/api/http";
import { useApi } from "@/lib/api/query";
import { session } from "@/lib/session";
import { CommandPalette } from "./CommandPalette";
import { NAV_GROUPS, NavItem } from "./nav";

interface CurrentUser {
  email: string;
  full_name: string;
  is_platform_admin: boolean;
}

function initials(name: string) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join("") || "·";
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { data: me, isLoading, isError } = useMe();
  const { data: branding } = useBranding();
  const { data: user } = useApi<CurrentUser>("/auth/user");
  const [mobileOpen, setMobileOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);

  useEffect(() => {
    if (!session.isAuthenticated()) router.replace("/login");
  }, [router]);

  useEffect(() => {
    if (isError) {
      session.clear();
      router.replace("/login");
    }
  }, [isError, router]);

  useEffect(() => setMobileOpen(false), [pathname]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  function logout() {
    session.clear();
    router.push("/login");
  }

  const features = new Set(me?.features ?? []);
  const permissions = new Set(me?.permissions ?? []);
  const visible = (item: NavItem) =>
    (item.moduleKey === null || features.has(item.moduleKey)) &&
    (!item.permission || permissions.has("*") || permissions.has(item.permission));
  const groups = NAV_GROUPS.map((g) => ({ ...g, items: g.items.filter(visible) })).filter((g) => g.items.length);
  const brandName = branding?.name || "ERP";

  const sidebar = (
    <div className="flex h-full flex-col bg-navy-900 px-3 py-5 text-slate-300">
      <div className="mb-5 flex items-center gap-3 px-2">
        {branding?.logo_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={mediaUrl(branding.logo_url) ?? ""} alt="" className="h-9 w-9 rounded-lg bg-white object-contain p-0.5" />
        ) : (
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand text-sm font-semibold text-white">{initials(brandName)}</div>
        )}
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-white">{brandName}</p>
          <p className="text-[11px] capitalize text-slate-400">{me?.role ?? ""}</p>
        </div>
      </div>

      <button
        onClick={() => setPaletteOpen(true)}
        className="mb-4 flex items-center gap-2 rounded-lg bg-navy-800 px-3 py-2 text-left text-sm text-slate-400 ring-1 ring-navy-700 transition hover:text-white"
      >
        <Search className="h-4 w-4" />
        <span className="flex-1">Search…</span>
        <kbd className="rounded bg-navy-700 px-1.5 text-[10px]">Ctrl K</kbd>
      </button>

      <nav className="-mx-1 flex-1 space-y-4 overflow-y-auto px-1">
        {groups.map((group, gi) => (
          <div key={group.label ?? `g${gi}`}>
            {group.label && <p className="mb-1.5 px-3 text-[10px] font-semibold uppercase tracking-widest text-slate-500">{group.label}</p>}
            <div className="space-y-0.5">
              {group.items.map((item) => {
                const active = pathname === item.href || (item.href !== "/dashboard" && pathname?.startsWith(item.href));
                const Icon = item.icon;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={`group flex items-center gap-3 rounded-lg px-3 py-1.5 text-sm font-medium transition ${
                      active ? "bg-white/10 text-white" : "text-slate-400 hover:bg-white/5 hover:text-white"
                    }`}
                  >
                    <Icon className={`h-4 w-4 ${active ? "text-brand-200" : "text-slate-500 group-hover:text-slate-300"}`} />
                    {item.label}
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
        {user?.is_platform_admin && (
          <div>
            <p className="mb-1.5 px-3 text-[10px] font-semibold uppercase tracking-widest text-slate-500">Platform</p>
            <Link href="/admin" className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-amber-300 hover:bg-white/5">
              <ShieldCheck className="h-4 w-4" />
              Admin console
            </Link>
          </div>
        )}
      </nav>

      <div className="mt-4 flex items-center gap-3 border-t border-navy-700 px-2 pt-4">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-navy-700 text-xs font-semibold text-white">
          {initials(user?.full_name || user?.email || "")}
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-xs font-medium text-white">{user?.full_name || "Signed in"}</p>
          <p className="truncate text-[11px] text-slate-500">{user?.email}</p>
        </div>
        <button onClick={logout} title="Sign out" className="rounded-lg p-1.5 text-slate-400 hover:bg-white/5 hover:text-white">
          <LogOut className="h-4 w-4" />
        </button>
      </div>
    </div>
  );

  return (
    <div className="flex min-h-screen bg-slate-50 dark:bg-navy-950">
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 md:block">{sidebar}</aside>

      {mobileOpen && (
        <div className="fixed inset-0 z-40 bg-navy-950/60 md:hidden" onClick={() => setMobileOpen(false)}>
          <aside className="relative h-full w-72" onClick={(e) => e.stopPropagation()}>
            {sidebar}
            <button onClick={() => setMobileOpen(false)} className="absolute right-3 top-5 rounded-lg p-1.5 text-slate-400" aria-label="Close menu">
              <X className="h-5 w-5" />
            </button>
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-slate-200 bg-white/80 px-4 py-3 backdrop-blur md:hidden dark:border-navy-700 dark:bg-navy-900/80">
          <button onClick={() => setMobileOpen(true)} className="rounded-lg p-1.5 text-slate-600" aria-label="Open menu">
            <Menu className="h-5 w-5" />
          </button>
          <span className="flex-1 truncate font-semibold text-navy-900 dark:text-white">{brandName}</span>
          <button onClick={() => setPaletteOpen(true)} className="rounded-lg p-1.5 text-slate-600" aria-label="Search">
            <Search className="h-5 w-5" />
          </button>
        </header>
        <main className="flex-1 px-4 py-6 md:px-10 md:py-8">
          {isLoading ? <p className="text-sm text-slate-400">Loading…</p> : <div className="mx-auto max-w-7xl">{children}</div>}
        </main>
      </div>

      <CommandPalette items={groups.flatMap((g) => g.items)} open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
  );
}
