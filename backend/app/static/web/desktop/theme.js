/* Theme toggle for /web desktop shell. */
(function (window, document) {
  "use strict";

  const app = window.TicketboxWeb = window.TicketboxWeb || {};

  app.applyTheme = function applyTheme(theme) {
    if (!app.THEMES.includes(theme)) theme = "paper";
    document.documentElement.setAttribute("data-theme", theme);
    try { localStorage.setItem("ui-theme", theme); } catch (_) {}
    // SSR 用 cookie 读取主题以避免下次刷新闪烁
    document.cookie = "ui_theme=" + theme + ";path=/;max-age=31536000;samesite=lax";
    // v0.10: 跨端同步。Loopback web 暂无 auth 会 401, V0.11 加 web account binding 后自然生效。
    if (typeof fetch === "function") {
      fetch("/api/me/ui-preferences", {
        method: "PUT",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ theme: theme }),
      }).catch(function () { /* silent, 服务端无 auth 时 401 是预期 */ });
    }
  };

  app.initThemeToggle = function initThemeToggle() {
    const btn = document.getElementById("theme-toggle");
    if (!btn) return;
    btn.addEventListener("click", function () {
      const current = document.documentElement.getAttribute("data-theme") || "paper";
      const next = app.THEMES[(app.THEMES.indexOf(current) + 1) % app.THEMES.length];
      app.applyTheme(next);
    });
  };
})(window, document);
