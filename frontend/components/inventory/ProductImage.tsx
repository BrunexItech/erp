"use client";

import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Camera, Package } from "lucide-react";
import { http, mediaUrl } from "@/lib/api/http";
import { errorMessage } from "@/lib/api/query";
import type { Product } from "@/lib/api/types";

/** Square product picture, or a neutral placeholder when there isn't one. */
export function ProductThumb({ url, name, className = "h-10 w-10" }: { url: string | null | undefined; name: string; className?: string }) {
  const src = mediaUrl(url);
  return (
    <span className={`flex shrink-0 items-center justify-center overflow-hidden rounded-lg bg-slate-100 text-slate-300 dark:bg-navy-700 dark:text-navy-500 ${className}`}>
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={src} alt={name} loading="lazy" className="h-full w-full object-cover" />
      ) : (
        <Package className="h-1/2 w-1/2" />
      )}
    </span>
  );
}

/** The picture in the product window, with a button to add or change it. */
export function ProductImageUploader({ productId, url, name, canWrite }: { productId: string; url: string | null | undefined; name: string; canWrite: boolean }) {
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function send(file: File | undefined) {
    if (!file) return;
    setError(null);
    if (!/^image\/(png|jpeg|webp)$/.test(file.type)) return setError("Choose a PNG, JPG or WebP image.");
    if (file.size > 3 * 1024 * 1024) return setError("That picture is over 3 MB.");
    setBusy(true);
    try {
      await http.upload<Product>(`/inventory/products/${productId}/image`, file);
      qc.invalidateQueries({ queryKey: ["inventory"] });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="shrink-0">
      <div className="relative">
        <ProductThumb url={url} name={name} className="h-20 w-20 rounded-xl" />
        {canWrite && (
          <button
            type="button"
            disabled={busy}
            onClick={() => input.current?.click()}
            aria-label={url ? "Change picture" : "Add picture"}
            title={url ? "Change picture" : "Add picture"}
            className="absolute -bottom-1.5 -right-1.5 flex h-7 w-7 items-center justify-center rounded-full bg-brand text-white shadow ring-2 ring-white hover:bg-brand-600 disabled:opacity-50 dark:ring-navy-800"
          >
            <Camera className="h-3.5 w-3.5" />
          </button>
        )}
        <input ref={input} type="file" accept="image/png,image/jpeg,image/webp" className="hidden" onChange={(e) => { send(e.target.files?.[0]); e.target.value = ""; }} />
      </div>
      {error && <p className="mt-2 max-w-40 text-xs text-red-600">{error}</p>}
    </div>
  );
}
