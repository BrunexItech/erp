const ACCESS_KEY = "erp.access_token";
const REFRESH_KEY = "erp.refresh_token";
const WORKSPACE_KEY = "erp.workspace_id";

const ADMIN_BACKUP_KEY = "erp.admin_backup";

export const session = {
  /** Support access: remember the admin's own session, then become the
   * customer's owner. `stopImpersonating` puts the admin's session back. */
  startImpersonating: (accessToken: string, workspaceId: string, label: string) => {
    safeSet(
      ADMIN_BACKUP_KEY,
      JSON.stringify({ access: safeGet(ACCESS_KEY), refresh: safeGet(REFRESH_KEY), workspace: safeGet(WORKSPACE_KEY), label })
    );
    safeSet(ACCESS_KEY, accessToken);
    safeRemove(REFRESH_KEY); // support sessions can't be extended
    safeSet(WORKSPACE_KEY, workspaceId);
  },
  impersonating: (): string | null => {
    try {
      return JSON.parse(safeGet(ADMIN_BACKUP_KEY) ?? "null")?.label ?? null;
    } catch {
      return null;
    }
  },
  stopImpersonating: () => {
    try {
      const backup = JSON.parse(safeGet(ADMIN_BACKUP_KEY) ?? "null");
      if (backup?.access) safeSet(ACCESS_KEY, backup.access);
      if (backup?.refresh) safeSet(REFRESH_KEY, backup.refresh);
      if (backup?.workspace) safeSet(WORKSPACE_KEY, backup.workspace);
    } catch {
      // fall through to clearing the marker
    }
    safeRemove(ADMIN_BACKUP_KEY);
  },

  getAccessToken: () => safeGet(ACCESS_KEY),
  getRefreshToken: () => safeGet(REFRESH_KEY),
  getWorkspaceId: () => safeGet(WORKSPACE_KEY),

  setTokens: (accessToken: string, refreshToken: string) => {
    safeSet(ACCESS_KEY, accessToken);
    safeSet(REFRESH_KEY, refreshToken);
  },
  setWorkspaceId: (workspaceId: string) => safeSet(WORKSPACE_KEY, workspaceId),

  clear: () => {
    safeRemove(ACCESS_KEY);
    safeRemove(REFRESH_KEY);
    safeRemove(WORKSPACE_KEY);
    safeRemove(ADMIN_BACKUP_KEY);
  },

  isAuthenticated: () => !!safeGet(ACCESS_KEY),
};

function safeGet(key: string): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeSet(key: string, value: string) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // ignore (private browsing, storage blocked, etc.)
  }
}

function safeRemove(key: string) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(key);
  } catch {
    // ignore
  }
}
