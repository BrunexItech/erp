// Sales rung up while the till has no connection. Each one is kept in this
// browser's storage and sent when the connection returns. Every sale carries a
// client_ref the server remembers, so a sale that is sent twice (the reply was
// lost, the page was reloaded mid-sync) is still only recorded once.
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, http } from "@/lib/api/http";
import type { PosReceipt } from "@/lib/api/types";

const QUEUE_KEY = "erp.pos.queue";
const RETRY_MS = 30_000;

export interface QueuedSale {
  client_ref: string;
  workspace_id: string;
  payload: Record<string, unknown>; // the checkout request, including client_ref and sold_at
  total: number;
  items: number;
  queued_at: string;
  error?: string; // set when the server refused it — needs a person to look
}

export function newClientRef(tillId: string): string {
  const unique = typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
  return `${tillId.slice(0, 8)}-${unique}`.slice(0, 64);
}

function read(): QueuedSale[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(QUEUE_KEY) ?? "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

/** Returns false if the browser refused to store it (storage full or disabled). */
function write(queue: QueuedSale[]): boolean {
  try {
    localStorage.setItem(QUEUE_KEY, JSON.stringify(queue));
    return true;
  } catch {
    return false;
  }
}

/** True when the request never reached the server (as opposed to being refused by it). */
export function isConnectionError(err: unknown): boolean {
  return !(err instanceof ApiError) || err.status >= 502;
}

export function usePosQueue(workspaceId: string | undefined, onSynced: () => void) {
  const [queue, setQueue] = useState<QueuedSale[]>([]);
  const [syncing, setSyncing] = useState(false);
  const busy = useRef(false);
  const synced = useRef(onSynced);
  synced.current = onSynced;

  useEffect(() => setQueue(read()), []);

  const mine = queue.filter((s) => !workspaceId || s.workspace_id === workspaceId);

  /** Keeps a sale for later. Returns false if it could not be stored. */
  const enqueue = useCallback((sale: QueuedSale): boolean => {
    const next = [...read().filter((s) => s.client_ref !== sale.client_ref), sale];
    if (!write(next)) return false;
    setQueue(next);
    return true;
  }, []);

  const discard = useCallback((clientRef: string) => {
    const next = read().filter((s) => s.client_ref !== clientRef);
    write(next);
    setQueue(next);
  }, []);

  /** Sends everything waiting, oldest first. Stops at the first connection
   * failure; a sale the server refuses is flagged and the rest carry on. */
  const sync = useCallback(async () => {
    if (busy.current || !workspaceId) return;
    busy.current = true;
    setSyncing(true);
    let sent = 0;
    try {
      for (const sale of read().filter((s) => s.workspace_id === workspaceId)) {
        try {
          await http.post<PosReceipt>("/sales/pos/checkout", sale.payload);
          write(read().filter((s) => s.client_ref !== sale.client_ref));
          sent += 1;
        } catch (err) {
          if (isConnectionError(err) || (err instanceof ApiError && (err.status === 401 || err.status === 429))) break;
          const detail = err instanceof ApiError && typeof err.detail === "string" ? err.detail : "The server did not accept this sale.";
          write(read().map((s) => (s.client_ref === sale.client_ref ? { ...s, error: detail } : s)));
        }
      }
    } finally {
      busy.current = false;
      setSyncing(false);
      setQueue(read());
      if (sent) synced.current();
    }
  }, [workspaceId]);

  // Try on load, whenever the connection comes back, and every so often in between.
  const waiting = mine.length;
  useEffect(() => {
    if (!waiting || !workspaceId) return;
    sync();
    const timer = setInterval(sync, RETRY_MS);
    window.addEventListener("online", sync);
    return () => {
      clearInterval(timer);
      window.removeEventListener("online", sync);
    };
  }, [waiting, workspaceId, sync]);

  return { queue: mine, enqueue, discard, sync, syncing };
}

// ---- last known catalogue, so the till still opens after a restart offline

const CATALOG_KEY = "erp.pos.catalog";

export function saveCatalog<T>(part: string, value: T): void {
  try {
    localStorage.setItem(`${CATALOG_KEY}.${part}`, JSON.stringify(value));
  } catch {
    // Storage full: the till still works online, it just can't restart offline.
  }
}

export function loadCatalog<T>(part: string): T | undefined {
  try {
    const raw = localStorage.getItem(`${CATALOG_KEY}.${part}`);
    return raw ? (JSON.parse(raw) as T) : undefined;
  } catch {
    return undefined;
  }
}
