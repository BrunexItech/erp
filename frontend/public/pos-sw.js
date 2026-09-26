// Service worker for the installable POS. Keeps the till's code and assets
// cached so it opens instantly (and shows a clear "offline" state instead of a
// browser error page if the shop's internet drops). Sales themselves always go
// to the server — stock and the ledger must never diverge between tills.
const CACHE = "pos-shell-v1";

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(["/pos"])).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin) return; // API calls: straight to network

  if (url.pathname.startsWith("/_next/static/") || /\.(png|svg|woff2?|webmanifest)$/.test(url.pathname)) {
    // Fingerprinted build assets never change — cache first.
    event.respondWith(
      caches.match(request).then(
        (hit) => hit || fetch(request).then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((cache) => cache.put(request, copy));
          return res;
        })
      )
    );
    return;
  }

  if (request.mode === "navigate") {
    // Pages: fresh when online, last good copy when not.
    event.respondWith(
      fetch(request)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((cache) => cache.put(request, copy));
          return res;
        })
        .catch(() => caches.match(request).then((hit) => hit || caches.match("/pos")))
    );
  }
});
