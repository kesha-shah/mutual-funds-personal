// Minimal service worker — exists only so browsers treat the site as an
// installable PWA. No caching: portfolio data must always be live, and every
// request still goes through the auth gateway.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {});
