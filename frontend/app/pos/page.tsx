"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  Banknote,
  BarChart3,
  CreditCard,
  Download,
  Maximize,
  Minus,
  Plus,
  Printer,
  ScanBarcode,
  Smartphone,
  Trash2,
  Wifi,
  WifiOff,
  X,
} from "lucide-react";
import { useBranding, useMe, useParties, usePosCheckout, useProducts, useWarehouses, useWarehouseStock } from "@/lib/api/hooks";
import { errorMessage, useApi } from "@/lib/api/query";
import { fmtMoney, num, today } from "@/lib/format";
import { session } from "@/lib/session";
import type { Product } from "@/lib/api/types";
import { Receipt, ReceiptData } from "@/components/pos/Receipt";

interface CartLine {
  product: Product;
  qty: number;
  price: number;
}

type Method = "cash" | "mpesa" | "card";

const TILL_KEY = "erp.pos.warehouse";
const AUTOPRINT_KEY = "erp.pos.autoprint";
const TILE_COLORS = ["bg-teal-600", "bg-sky-600", "bg-violet-600", "bg-amber-600", "bg-rose-600", "bg-emerald-600", "bg-indigo-600", "bg-orange-600"];

function store(key: string, value?: string): string | null {
  try {
    if (value !== undefined) localStorage.setItem(key, value);
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

const round2 = (v: number) => Math.round((v + Number.EPSILON) * 100) / 100;

export default function PosTerminal() {
  const router = useRouter();
  useEffect(() => {
    if (!session.isAuthenticated()) router.replace("/login");
  }, [router]);

  const { data: me } = useMe();
  const { data: branding } = useBranding();
  const { data: products } = useProducts();
  const { data: warehouses } = useWarehouses();
  const { data: parties } = useParties();
  const checkout = usePosCheckout();

  const [tillId, setTillId] = useState("");
  const { data: tillStock } = useWarehouseStock(tillId || undefined);
  const [cart, setCart] = useState<CartLine[]>([]);
  const [customerId, setCustomerId] = useState("");
  const [search, setSearch] = useState("");
  const [flash, setFlash] = useState<string | null>(null);
  const [paying, setPaying] = useState(false);
  const [receipt, setReceipt] = useState<ReceiptData | null>(null);
  const [showSummary, setShowSummary] = useState(false);
  const [online, setOnline] = useState(true);
  const [autoPrint, setAutoPrint] = useState(false);
  const [installPrompt, setInstallPrompt] = useState<{ prompt: () => void } | null>(null);
  const [clock, setClock] = useState("");
  const scanRef = useRef<HTMLInputElement>(null);

  // Restore the till this machine is set up for, and printer preference.
  useEffect(() => {
    setTillId(store(TILL_KEY) ?? "");
    setAutoPrint(store(AUTOPRINT_KEY) === "1");
    setOnline(navigator.onLine);
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    const onInstall = (e: Event) => {
      e.preventDefault();
      setInstallPrompt(e as unknown as { prompt: () => void });
    };
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    window.addEventListener("beforeinstallprompt", onInstall);
    // Client-only: server and browser format dates differently (hydration mismatch).
    const tick = () => {
      const now = new Date();
      setClock(
        `${now.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })} · ` +
          now.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })
      );
    };
    tick();
    const timer = setInterval(tick, 15_000);
    return () => {
      window.removeEventListener("online", up);
      window.removeEventListener("offline", down);
      window.removeEventListener("beforeinstallprompt", onInstall);
      clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    if (!tillId && warehouses?.length === 1) setTillId(warehouses[0].id);
  }, [warehouses, tillId]);

  const stockAtTill = useMemo(() => new Map((tillStock ?? []).map((s) => [s.product_id, num(s.qty)])), [tillStock]);
  const till = warehouses?.find((w) => w.id === tillId);
  const customers = (parties ?? []).filter((p) => p.kind === "customer" || p.kind === "both");

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    const list = (products ?? []).filter((p) => p.is_active);
    if (!q) return list;
    return list.filter((p) => p.name.toLowerCase().includes(q) || p.sku.toLowerCase().includes(q) || (p.barcode ?? "").includes(q));
  }, [products, search]);

  const totals = useMemo(() => {
    let subtotal = 0;
    let tax = 0;
    for (const l of cart) {
      const net = round2(l.qty * l.price);
      subtotal += net;
      tax += round2(net * num(l.product.tax_rate));
    }
    return { subtotal, tax, total: subtotal + tax, items: cart.reduce((s, l) => s + l.qty, 0) };
  }, [cart]);

  const focusScan = useCallback(() => setTimeout(() => scanRef.current?.focus(), 0), []);

  const notify = (message: string) => {
    setFlash(message);
    setTimeout(() => setFlash(null), 2200);
  };

  const add = useCallback(
    (product: Product, qty = 1) => {
      const available = stockAtTill.get(product.id) ?? 0;
      setCart((prev) => {
        const existing = prev.find((l) => l.product.id === product.id);
        const nextQty = (existing?.qty ?? 0) + qty;
        if (tillId && nextQty > available) {
          notify(`Only ${available} × ${product.name} at this till`);
          return prev;
        }
        if (existing) return prev.map((l) => (l.product.id === product.id ? { ...l, qty: nextQty } : l));
        return [...prev, { product, qty, price: num(product.sale_price) }];
      });
      focusScan();
    },
    [stockAtTill, tillId, focusScan]
  );

  function setQty(productId: string, qty: number) {
    setCart((prev) => (qty <= 0 ? prev.filter((l) => l.product.id !== productId) : prev.map((l) => (l.product.id === productId ? { ...l, qty } : l))));
  }

  // Barcode scanners type the code and press Enter.
  function onScanSubmit(e: React.FormEvent) {
    e.preventDefault();
    const code = search.trim();
    if (!code) return;
    const exact = (products ?? []).find(
      (p) => p.barcode === code || p.sku.toLowerCase() === code.toLowerCase()
    );
    const match = exact ?? (visible.length === 1 ? visible[0] : undefined);
    if (match) {
      add(match);
      setSearch("");
    } else {
      notify(`No product matches “${code}”`);
    }
  }

  const canCharge = cart.length > 0 && !!tillId && online;

  // F2 = scan box, F9 = pay, Esc = close dialogs.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "F2") { e.preventDefault(); focusScan(); }
      if (e.key === "F9" && canCharge && !receipt) { e.preventDefault(); setPaying(true); }
      if (e.key === "Escape") { setPaying(false); setShowSummary(false); }
      if (e.key === "Enter" && receipt && !paying) { e.preventDefault(); newSale(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  async function completeSale(method: Method, tendered: number | null, reference: string) {
    const lines = cart.map((l) => ({
      product_id: l.product.id,
      qty: String(l.qty),
      unit_price: String(l.price),
      tax_rate: l.product.tax_rate,
    }));
    const result = await checkout.mutateAsync({
      warehouse_id: tillId,
      party_id: customerId || null,
      payment_method: method,
      payment_reference: reference,
      amount_tendered: tendered !== null ? tendered.toFixed(2) : null,
      lines,
    });
    const data: ReceiptData = {
      ...result,
      lines: cart.map((l) => ({ name: l.product.name, qty: l.qty, price: l.price, total: round2(l.qty * l.price) })),
      customer: customers.find((c) => c.id === customerId)?.name,
      till: till?.name,
    };
    setReceipt(data);
    setPaying(false);
    if (autoPrint) setTimeout(() => window.print(), 250);
  }

  function newSale() {
    setReceipt(null);
    setCart([]);
    setCustomerId("");
    setSearch("");
    focusScan();
  }

  return (
    <div className="flex h-screen flex-col bg-slate-100 text-navy-900 print:bg-white">
      {/* Top bar */}
      <header className="flex items-center gap-3 bg-navy-900 px-4 py-2.5 text-white print:hidden">
        <Link href="/dashboard" className="rounded-lg p-2 text-slate-400 hover:bg-white/10 hover:text-white" title="Back office">
          <ArrowLeft className="h-5 w-5" />
        </Link>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">{branding?.name ?? "Point of Sale"}</p>
          <p className="text-[11px] text-slate-400">{clock}</p>
        </div>
        <select
          value={tillId}
          onChange={(e) => { setTillId(e.target.value); store(TILL_KEY, e.target.value); setCart([]); }}
          className="ml-4 rounded-lg border-0 bg-white/10 px-3 py-2 text-sm text-white ring-1 ring-white/10 focus:ring-brand-200"
        >
          <option value="" className="text-navy-900">Choose till / shop…</option>
          {warehouses?.map((w) => <option key={w.id} value={w.id} className="text-navy-900">{w.name}</option>)}
        </select>
        <div className="ml-auto flex items-center gap-1">
          <span className={`mr-2 flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs ${online ? "bg-emerald-500/15 text-emerald-300" : "bg-red-500/20 text-red-300"}`}>
            {online ? <Wifi className="h-3.5 w-3.5" /> : <WifiOff className="h-3.5 w-3.5" />}
            {online ? "Online" : "Offline"}
          </span>
          <TopButton title="Till summary (cash-up)" onClick={() => setShowSummary(true)} disabled={!tillId}><BarChart3 /></TopButton>
          <TopButton
            title={autoPrint ? "Auto-print receipts: ON" : "Auto-print receipts: OFF"}
            onClick={() => { const v = !autoPrint; setAutoPrint(v); store(AUTOPRINT_KEY, v ? "1" : "0"); }}
            active={autoPrint}
          >
            <Printer />
          </TopButton>
          <TopButton title="Full screen" onClick={() => document.documentElement.requestFullscreen?.().catch(() => undefined)}><Maximize /></TopButton>
          {installPrompt && (
            <button onClick={() => installPrompt.prompt()} className="ml-1 flex items-center gap-1.5 rounded-lg bg-brand px-3 py-2 text-xs font-medium hover:bg-brand-600">
              <Download className="h-4 w-4" /> Install app
            </button>
          )}
          <span className="ml-2 hidden text-xs text-slate-400 md:inline">{me?.role}</span>
        </div>
      </header>

      {!online && (
        <div className="bg-red-600 px-4 py-1.5 text-center text-sm text-white print:hidden">
          No connection — sales are paused so stock and the books stay correct. Reconnect to continue.
        </div>
      )}

      <div className="flex min-h-0 flex-1 print:hidden">
        {/* Products */}
        <section className="flex min-w-0 flex-1 flex-col p-4">
          <form onSubmit={onScanSubmit} className="relative">
            <ScanBarcode className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-slate-400" />
            <input
              ref={scanRef}
              autoFocus
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Scan a barcode or type a name / SKU…   (F2)"
              className="h-14 w-full rounded-2xl border-0 bg-white pl-12 pr-4 text-base shadow-card ring-1 ring-slate-200 focus:outline-none focus:ring-2 focus:ring-brand"
            />
            {flash && (
              <span className="absolute right-3 top-1/2 -translate-y-1/2 rounded-lg bg-amber-100 px-3 py-1.5 text-sm text-amber-800">{flash}</span>
            )}
          </form>

          {!tillId ? (
            <div className="m-auto max-w-sm text-center">
              <p className="text-lg font-semibold">Choose this till&apos;s shop</p>
              <p className="mt-1 text-sm text-slate-500">Pick the warehouse or shop this machine sells from (top bar). It&apos;s remembered on this device.</p>
            </div>
          ) : (
            <div className="mt-4 grid min-h-0 flex-1 auto-rows-min grid-cols-2 gap-3 overflow-y-auto pb-4 sm:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
              {visible.map((p, i) => {
                const stock = stockAtTill.get(p.id) ?? 0;
                const out = stock <= 0;
                return (
                  <button
                    key={p.id}
                    disabled={out}
                    onClick={() => add(p)}
                    className="group flex flex-col rounded-2xl bg-white p-3 text-left shadow-card ring-1 ring-slate-200/70 transition active:scale-[0.98] enabled:hover:-translate-y-0.5 enabled:hover:shadow-lift enabled:hover:ring-brand/40 disabled:opacity-45"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <span className={`flex h-10 w-10 items-center justify-center rounded-xl text-sm font-semibold text-white ${TILE_COLORS[i % TILE_COLORS.length]}`}>
                        {p.name.slice(0, 2).toUpperCase()}
                      </span>
                      <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${out ? "bg-red-50 text-red-600" : stock <= num(p.low_stock_threshold) ? "bg-amber-50 text-amber-700" : "bg-slate-100 text-slate-500"}`}>
                        {out ? "Out" : `${stock} left`}
                      </span>
                    </div>
                    <p className="mt-3 line-clamp-2 min-h-[2.5rem] text-sm font-medium leading-tight">{p.name}</p>
                    <p className="text-[11px] text-slate-400">{p.sku}</p>
                    <p className="mt-2 text-base font-semibold text-brand">{fmtMoney(p.sale_price)}</p>
                  </button>
                );
              })}
              {!visible.length && <p className="col-span-full py-12 text-center text-sm text-slate-500">No products match “{search}”.</p>}
            </div>
          )}
        </section>

        {/* Cart */}
        <aside className="flex w-[380px] shrink-0 flex-col border-l border-slate-200 bg-white xl:w-[420px]">
          <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
            <div>
              <p className="font-semibold">Current sale</p>
              <p className="text-xs text-slate-500">{totals.items} item{totals.items === 1 ? "" : "s"}</p>
            </div>
            {cart.length > 0 && (
              <button onClick={() => setCart([])} className="flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-slate-500 hover:bg-red-50 hover:text-red-600">
                <Trash2 className="h-3.5 w-3.5" /> Clear
              </button>
            )}
          </div>

          <div className="flex-1 overflow-y-auto px-3 py-2">
            {!cart.length && (
              <div className="flex h-full flex-col items-center justify-center text-center text-slate-400">
                <ScanBarcode className="mb-2 h-10 w-10 text-slate-300" />
                <p className="text-sm">Scan or tap a product to start</p>
              </div>
            )}
            {cart.map((l) => (
              <div key={l.product.id} className="flex items-center gap-3 rounded-xl px-2 py-2.5 hover:bg-slate-50">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{l.product.name}</p>
                  <p className="text-xs text-slate-500">{fmtMoney(l.price)} each</p>
                </div>
                <div className="flex items-center rounded-lg ring-1 ring-slate-200">
                  <button onClick={() => setQty(l.product.id, l.qty - 1)} className="p-2 text-slate-500 hover:text-navy-900" aria-label="Less"><Minus className="h-3.5 w-3.5" /></button>
                  <input
                    value={l.qty}
                    inputMode="decimal"
                    onChange={(e) => setQty(l.product.id, num(e.target.value))}
                    className="w-10 bg-transparent text-center text-sm font-medium outline-none"
                  />
                  <button onClick={() => add(l.product)} className="p-2 text-slate-500 hover:text-navy-900" aria-label="More"><Plus className="h-3.5 w-3.5" /></button>
                </div>
                <p className="w-20 text-right text-sm font-semibold tabular-nums">{fmtMoney(l.qty * l.price)}</p>
              </div>
            ))}
          </div>

          <div className="space-y-3 border-t border-slate-100 p-5">
            <select
              value={customerId}
              onChange={(e) => setCustomerId(e.target.value)}
              className="w-full rounded-lg border-slate-200 bg-slate-50 px-3 py-2 text-sm ring-1 ring-slate-200"
            >
              <option value="">Walk-in customer</option>
              {customers.filter((c) => c.name !== "Walk-in Customer").map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
            <div className="space-y-1 text-sm">
              <div className="flex justify-between text-slate-500"><span>Subtotal</span><span className="tabular-nums">{fmtMoney(totals.subtotal)}</span></div>
              <div className="flex justify-between text-slate-500"><span>VAT</span><span className="tabular-nums">{fmtMoney(totals.tax)}</span></div>
              <div className="flex items-end justify-between pt-1">
                <span className="text-base font-semibold">Total</span>
                <span className="text-3xl font-bold tracking-tight tabular-nums">{fmtMoney(totals.total)}</span>
              </div>
            </div>
            <button
              disabled={!canCharge}
              onClick={() => setPaying(true)}
              className="flex h-14 w-full items-center justify-center gap-2 rounded-2xl bg-brand text-lg font-semibold text-white shadow-lift transition hover:bg-brand-600 disabled:cursor-not-allowed disabled:bg-slate-300 disabled:shadow-none"
            >
              Charge {fmtMoney(totals.total, branding?.currency)}
              <kbd className="rounded bg-white/20 px-1.5 text-xs font-normal">F9</kbd>
            </button>
          </div>
        </aside>
      </div>

      {paying && (
        <PaymentDialog
          total={round2(totals.total)}
          currency={branding?.currency}
          busy={checkout.isPending}
          onCancel={() => { setPaying(false); focusScan(); }}
          onComplete={completeSale}
        />
      )}

      {receipt && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-navy-950/60 p-4 backdrop-blur-sm print:static print:block print:bg-white print:p-0">
          <div className="flex max-h-full w-full max-w-md flex-col overflow-hidden rounded-3xl bg-white shadow-lift print:max-w-none print:rounded-none print:shadow-none">
            <div className="bg-emerald-600 px-6 py-5 text-center text-white print:hidden">
              <p className="text-sm opacity-90">Sale complete</p>
              {num(receipt.change_due) > 0 ? (
                <p className="mt-1 text-3xl font-bold">Change {fmtMoney(receipt.change_due)}</p>
              ) : (
                <p className="mt-1 text-3xl font-bold">{fmtMoney(receipt.total, branding?.currency)}</p>
              )}
            </div>
            <div className="overflow-y-auto bg-slate-50 py-4 print:bg-white print:p-0">
              <Receipt data={receipt} branding={branding} />
            </div>
            <div className="grid grid-cols-2 gap-3 p-4 print:hidden">
              <button onClick={() => window.print()} className="flex h-12 items-center justify-center gap-2 rounded-xl font-medium ring-1 ring-slate-200 hover:bg-slate-50">
                <Printer className="h-4 w-4" /> Print receipt
              </button>
              <button onClick={newSale} className="h-12 rounded-xl bg-brand font-semibold text-white hover:bg-brand-600">
                New sale <span className="text-xs font-normal opacity-80">(Enter)</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {showSummary && tillId && <TillSummary tillId={tillId} tillName={till?.name ?? ""} onClose={() => { setShowSummary(false); focusScan(); }} />}

      <style>{`
        @media print {
          @page { size: 80mm auto; margin: 0; }
          body { margin: 0; }
        }
      `}</style>
    </div>
  );
}

function TopButton({ children, title, onClick, disabled, active }: { children: React.ReactNode; title: string; onClick: () => void; disabled?: boolean; active?: boolean }) {
  return (
    <button
      title={title}
      onClick={onClick}
      disabled={disabled}
      className={`rounded-lg p-2 transition disabled:opacity-30 [&_svg]:h-5 [&_svg]:w-5 ${active ? "bg-brand text-white" : "text-slate-400 hover:bg-white/10 hover:text-white"}`}
    >
      {children}
    </button>
  );
}

function PaymentDialog({
  total,
  currency,
  busy,
  onCancel,
  onComplete,
}: {
  total: number;
  currency?: string;
  busy: boolean;
  onCancel: () => void;
  onComplete: (method: Method, tendered: number | null, reference: string) => Promise<void>;
}) {
  const [method, setMethod] = useState<Method>("cash");
  const [tendered, setTendered] = useState(String(total));
  const [reference, setReference] = useState("");
  const [error, setError] = useState<string | null>(null);
  const change = num(tendered) - total;
  const quick = Array.from(new Set([total, Math.ceil(total / 50) * 50, Math.ceil(total / 100) * 100, ...[500, 1000, 2000, 5000].filter((n) => n > total)])).slice(0, 5);
  const valid = method === "cash" ? num(tendered) >= total : true;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!valid) return;
    setError(null);
    try {
      await onComplete(method, method === "cash" ? num(tendered) : null, reference.trim());
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const methods: { key: Method; label: string; icon: typeof Banknote }[] = [
    { key: "cash", label: "Cash", icon: Banknote },
    { key: "mpesa", label: "M-Pesa", icon: Smartphone },
    { key: "card", label: "Card", icon: CreditCard },
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-navy-950/60 p-4 backdrop-blur-sm" onClick={onCancel}>
      <form onSubmit={submit} onClick={(e) => e.stopPropagation()} className="w-full max-w-lg rounded-3xl bg-white p-6 shadow-lift">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-sm text-slate-500">Amount due</p>
            <p className="text-4xl font-bold tracking-tight">{fmtMoney(total, currency)}</p>
          </div>
          <button type="button" onClick={onCancel} className="rounded-lg p-2 text-slate-400 hover:bg-slate-100" aria-label="Cancel"><X className="h-5 w-5" /></button>
        </div>

        <div className="mt-6 grid grid-cols-3 gap-2">
          {methods.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              type="button"
              onClick={() => setMethod(key)}
              className={`flex flex-col items-center gap-1.5 rounded-2xl py-4 text-sm font-medium ring-1 transition ${
                method === key ? "bg-brand-50 text-brand ring-2 ring-brand" : "text-slate-600 ring-slate-200 hover:bg-slate-50"
              }`}
            >
              <Icon className="h-6 w-6" />
              {label}
            </button>
          ))}
        </div>

        {method === "cash" ? (
          <div className="mt-6">
            <label className="text-sm font-medium text-slate-600">Cash received</label>
            <input
              autoFocus
              inputMode="decimal"
              value={tendered}
              onChange={(e) => setTendered(e.target.value)}
              onFocus={(e) => e.target.select()}
              className="mt-1 h-14 w-full rounded-2xl px-4 text-2xl font-semibold ring-1 ring-slate-200 focus:outline-none focus:ring-2 focus:ring-brand"
            />
            <div className="mt-3 flex flex-wrap gap-2">
              {quick.map((q) => (
                <button key={q} type="button" onClick={() => setTendered(String(q))} className="rounded-xl bg-slate-100 px-3 py-2 text-sm font-medium hover:bg-slate-200">
                  {q === total ? "Exact" : fmtMoney(q).replace(".00", "")}
                </button>
              ))}
            </div>
            <div className={`mt-4 flex items-center justify-between rounded-2xl px-4 py-3 ${change >= 0 ? "bg-emerald-50 text-emerald-800" : "bg-red-50 text-red-700"}`}>
              <span className="text-sm font-medium">{change >= 0 ? "Change to give" : "Short by"}</span>
              <span className="text-2xl font-bold tabular-nums">{fmtMoney(Math.abs(change))}</span>
            </div>
          </div>
        ) : (
          <div className="mt-6">
            <label className="text-sm font-medium text-slate-600">{method === "mpesa" ? "M-Pesa confirmation code" : "Card slip / approval number"}</label>
            <input
              autoFocus
              value={reference}
              onChange={(e) => setReference(e.target.value.toUpperCase())}
              placeholder={method === "mpesa" ? "e.g. SJK8H2L1QP" : "e.g. 004512"}
              className="mt-1 h-14 w-full rounded-2xl px-4 font-mono text-xl tracking-wider ring-1 ring-slate-200 focus:outline-none focus:ring-2 focus:ring-brand"
            />
            <p className="mt-2 text-xs text-slate-500">Recorded on the receipt and in the till summary so you can match your M-Pesa statement.</p>
          </div>
        )}

        {error && <p className="mt-4 rounded-xl bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

        <button
          type="submit"
          disabled={!valid || busy}
          className="mt-6 h-14 w-full rounded-2xl bg-brand text-lg font-semibold text-white shadow-lift transition hover:bg-brand-600 disabled:cursor-not-allowed disabled:bg-slate-300 disabled:shadow-none"
        >
          {busy ? "Processing…" : `Complete sale`}
        </button>
      </form>
    </div>
  );
}

interface Summary {
  sales_count: number;
  gross_sales: string;
  vat: string;
  net_sales: string;
  by_method: { method: string; count: number; amount: string }[];
  recent: { id: string; invoice_no: string; total: string; created_at: string }[];
}

function TillSummary({ tillId, tillName, onClose }: { tillId: string; tillName: string; onClose: () => void }) {
  const { data } = useApi<Summary>(`/sales/pos/summary?day=${today()}&warehouse_id=${tillId}`);
  const label = { cash: "Cash", mpesa: "M-Pesa", card: "Card" } as Record<string, string>;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-navy-950/60 p-4 backdrop-blur-sm" onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} className="w-full max-w-md rounded-3xl bg-white p-6 shadow-lift">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-sm text-slate-500">Till summary · {tillName}</p>
            <p className="text-lg font-semibold">{new Date().toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" })}</p>
          </div>
          <button onClick={onClose} className="rounded-lg p-2 text-slate-400 hover:bg-slate-100" aria-label="Close"><X className="h-5 w-5" /></button>
        </div>
        {!data ? (
          <p className="py-8 text-center text-sm text-slate-400">Loading…</p>
        ) : (
          <>
            <div className="mt-5 grid grid-cols-2 gap-3">
              <div className="rounded-2xl bg-slate-50 p-4"><p className="text-xs text-slate-500">Sales</p><p className="text-2xl font-bold">{data.sales_count}</p></div>
              <div className="rounded-2xl bg-slate-50 p-4"><p className="text-xs text-slate-500">Takings</p><p className="text-2xl font-bold">{fmtMoney(data.gross_sales)}</p></div>
            </div>
            <p className="mt-5 text-xs font-semibold uppercase tracking-wider text-slate-500">By payment method — count your drawer against these</p>
            <div className="mt-2 divide-y divide-slate-100">
              {data.by_method.map((m) => (
                <div key={m.method} className="flex justify-between py-2.5 text-sm">
                  <span>{label[m.method] ?? m.method} <span className="text-slate-400">({m.count})</span></span>
                  <span className="font-semibold tabular-nums">{fmtMoney(m.amount)}</span>
                </div>
              ))}
              {!data.by_method.length && <p className="py-3 text-sm text-slate-400">No sales yet today.</p>}
              <div className="flex justify-between py-2.5 text-sm text-slate-500"><span>of which VAT</span><span className="tabular-nums">{fmtMoney(data.vat)}</span></div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
