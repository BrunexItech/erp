"use client";

import { useEffect } from "react";

export function RegisterServiceWorker() {
  useEffect(() => {
    if ("serviceWorker" in navigator && process.env.NODE_ENV === "production") {
      navigator.serviceWorker.register("/pos-sw.js").catch(() => {
        // Installability is a convenience — the till works without it.
      });
    }
  }, []);
  return null;
}
