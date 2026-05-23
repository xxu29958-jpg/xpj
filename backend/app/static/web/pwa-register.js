// Register the /web service worker once on each page load. Idempotent: if
// the worker is already controlling this page, the browser short-circuits
// the registration. Scope defaults to the directory the SW is served from
// (/static/web/), which is enough for iOS installability — full /web
// offline is intentionally not a v1.0 goal.
(function () {
  if (!("serviceWorker" in navigator)) return;
  window.addEventListener("load", () => {
    navigator.serviceWorker
      .register("/static/web/sw.js")
      .catch(() => {
        // Stay silent. SW registration failure (e.g. private mode on iOS
        // Safari) just means the page falls back to plain web behavior;
        // it is not user-facing.
      });
  });
})();
