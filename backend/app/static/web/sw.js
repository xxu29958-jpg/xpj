/* 小票夹 /web service worker.
 *
 * Goal is "iOS / Android can install /web to home screen", not full offline.
 * Default scope is /static/web/ (where this file is served), which is enough
 * for iOS 16.4+ installability — the SW just needs to exist and respond.
 *
 * Cache strategy:
 * - Static assets under /static/web/, /static/shared/ → cache-first (versioned
 *   by ``backend_version`` query string in <link> tags, so the bumping of
 *   that value naturally invalidates entries).
 * - Anything else (/web HTML pages, /api/...) → network-only. Account data
 *   must never be served from a stale cache, and authentication state
 *   changes (logout, ledger switch) would be silently broken by HTML
 *   caching.
 */

const CACHE_NAME = "ticketbox-web-v1";
const STATIC_PREFIXES = ["/static/web/", "/static/shared/"];

self.addEventListener("install", (event) => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key !== CACHE_NAME && key.startsWith("ticketbox-web-"))
            .map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (!STATIC_PREFIXES.some((prefix) => url.pathname.startsWith(prefix))) return;

  event.respondWith(
    caches.open(CACHE_NAME).then(async (cache) => {
      const cached = await cache.match(request);
      if (cached) return cached;
      const response = await fetch(request);
      if (response.ok && response.type === "basic") {
        cache.put(request, response.clone());
      }
      return response;
    }),
  );
});
