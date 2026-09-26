const ACCESS_KEY = "erp.access_token";
const REFRESH_KEY = "erp.refresh_token";
const WORKSPACE_KEY = "erp.workspace_id";

export const session = {
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
