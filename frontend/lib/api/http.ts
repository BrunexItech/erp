import { session } from "@/lib/session";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

/** A dead session: normally back to sign-in. But if a platform admin was
 * signed in as a customer (support sessions last 30 minutes and can't be
 * extended), put the admin's own session back instead of logging them out. */
function endSession() {
  if (typeof window === "undefined") return;
  if (session.impersonating()) {
    session.stopImpersonating();
    window.location.href = "/admin";
    return;
  }
  session.clear();
  window.location.href = "/login";
}

let refreshInFlight: Promise<boolean> | null = null;

async function refreshAccessToken(): Promise<boolean> {
  const refreshToken = session.getRefreshToken();
  if (!refreshToken) return false;

  if (!refreshInFlight) {
    refreshInFlight = fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
      .then(async (res) => {
        if (!res.ok) return false;
        const data = await res.json();
        session.setTokens(data.access_token, data.refresh_token);
        return true;
      })
      .catch(() => false)
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
}

interface RequestOptions {
  body?: unknown;
  workspaceScoped?: boolean;
  skipRetry?: boolean;
}

async function request<T>(method: string, path: string, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };

  const accessToken = session.getAccessToken();
  if (accessToken) headers["Authorization"] = `Bearer ${accessToken}`;

  const workspaceScoped = opts.workspaceScoped ?? true;
  if (workspaceScoped) {
    const workspaceId = session.getWorkspaceId();
    if (workspaceId) headers["X-Workspace-Id"] = workspaceId;
  }

  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });

  if (res.status === 401 && !opts.skipRetry) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      return request<T>(method, path, { ...opts, skipRetry: true });
    }
    endSession();
    throw new ApiError(401, "session expired");
  }

  if (!res.ok) {
    let detail: unknown;
    try {
      detail = (await res.json()).detail;
    } catch {
      detail = res.statusText;
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) return undefined as T;
  return res.json();
}

async function requestBlob(path: string, opts: RequestOptions = {}): Promise<Blob> {
  const headers: Record<string, string> = {};
  const accessToken = session.getAccessToken();
  if (accessToken) headers["Authorization"] = `Bearer ${accessToken}`;
  const workspaceId = session.getWorkspaceId();
  if (workspaceId) headers["X-Workspace-Id"] = workspaceId;

  const res = await fetch(`${API_BASE}${path}`, { headers });

  if (res.status === 401 && !opts.skipRetry) {
    const refreshed = await refreshAccessToken();
    if (refreshed) return requestBlob(path, { ...opts, skipRetry: true });
    endSession();
    throw new ApiError(401, "session expired");
  }
  if (!res.ok) throw new ApiError(res.status, res.statusText);
  return res.blob();
}

/** Multipart upload (the browser sets the boundary, so no Content-Type here). */
async function upload<T>(path: string, file: File, field = "file"): Promise<T> {
  const headers: Record<string, string> = {};
  const accessToken = session.getAccessToken();
  if (accessToken) headers["Authorization"] = `Bearer ${accessToken}`;
  const workspaceId = session.getWorkspaceId();
  if (workspaceId) headers["X-Workspace-Id"] = workspaceId;
  const body = new FormData();
  body.append(field, file);
  const res = await fetch(`${API_BASE}${path}`, { method: "POST", headers, body });
  if (!res.ok) {
    let detail: unknown;
    try {
      detail = (await res.json()).detail;
    } catch {
      detail = res.statusText;
    }
    throw new ApiError(res.status, detail);
  }
  return res.json();
}

/** Logos we host are stored as API paths ("/api/v1/media/…"); turn them into
 * a URL the browser can load. External logo URLs pass through unchanged. */
export function mediaUrl(path: string | null | undefined): string | null {
  if (!path) return null;
  if (!path.startsWith("/api/")) return path;
  return API_BASE.replace(/\/api\/v1\/?$/, "") + path;
}

export const http = {
  upload,
  get: <T>(path: string, opts?: RequestOptions) => request<T>("GET", path, opts),
  post: <T>(path: string, body?: unknown, opts?: RequestOptions) =>
    request<T>("POST", path, { ...opts, body }),
  put: <T>(path: string, body?: unknown, opts?: RequestOptions) =>
    request<T>("PUT", path, { ...opts, body }),
  patch: <T>(path: string, body?: unknown, opts?: RequestOptions) =>
    request<T>("PATCH", path, { ...opts, body }),
  del: <T>(path: string, opts?: RequestOptions) => request<T>("DELETE", path, opts),
  getBlob: (path: string) => requestBlob(path),
};
