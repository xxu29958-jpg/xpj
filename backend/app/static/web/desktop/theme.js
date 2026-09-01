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
