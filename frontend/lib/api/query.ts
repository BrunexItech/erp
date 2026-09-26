// Generic React Query wrappers for the newer modules — one hook per endpoint
// in hooks.ts doesn't scale to the ~80 endpoints HR, payroll, assets,
// manufacturing and the accounting reports add. Query keys are the URL path
// split on "/", so invalidating ["hr"] refreshes every /hr/* query.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, http } from "@/lib/api/http";

export function keyFor(path: string): string[] {
  return path.replace(/^\//, "").split(/[/?]/);
}

export function useApi<T>(path: string | null, opts: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: path ? [...keyFor(path), path] : ["disabled"],
    queryFn: () => http.get<T>(path as string),
    enabled: !!path && (opts.enabled ?? true),
  });
}

type Method = "post" | "put" | "patch" | "del";

export function useApiMutation<TBody = unknown, TResult = unknown>(
  method: Method,
  path: string | ((body: TBody) => string),
  invalidate: string[][] = []
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: TBody) => {
      const url = typeof path === "function" ? path(body) : path;
      if (method === "del") return http.del<TResult>(url);
      return http[method]<TResult>(url, body);
    },
    onSuccess: () => {
      for (const key of invalidate) qc.invalidateQueries({ queryKey: key });
    },
  });
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    const detail = err.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).slice(1).join(".")}: ${d.msg ?? ""}`)
        .join("; ");
    }
    return JSON.stringify(detail);
  }
  return err instanceof Error ? err.message : "Something went wrong";
}

/** Opens an authenticated PDF (or downloads a CSV) in a new tab. */
export async function openFile(path: string, download?: string) {
  const blob = await http.getBlob(path);
  const url = URL.createObjectURL(blob);
  if (download) {
    const a = document.createElement("a");
    a.href = url;
    a.download = download;
    a.click();
  } else {
    window.open(url, "_blank");
  }
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
