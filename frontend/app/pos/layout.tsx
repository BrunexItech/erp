import type { Metadata, Viewport } from "next";
import { RegisterServiceWorker } from "@/components/pos/RegisterServiceWorker";

// The till is its own installable app (Chrome/Edge "Install app", Android
// "Add to Home screen"): it opens full-screen at /pos with no browser chrome.
export const metadata: Metadata = {
  title: "POS",
  manifest: "/pos.webmanifest",
  appleWebApp: { capable: true, title: "POS", statusBarStyle: "black-translucent" },
  icons: { icon: "/pos-icon-192.png", apple: "/pos-icon-192.png" },
};

export const viewport: Viewport = {
  themeColor: "#0f1b2d",
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
};

export default function PosLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <RegisterServiceWorker />
      {children}
    </>
  );
}
