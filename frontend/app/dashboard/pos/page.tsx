"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

// The till lives at /pos — a full-screen, installable app outside the back
// office. Old links and bookmarks to /dashboard/pos land there.
export default function LegacyPosRedirect() {
  const router = useRouter();
  useEffect(() => router.replace("/pos"), [router]);
  return null;
}
