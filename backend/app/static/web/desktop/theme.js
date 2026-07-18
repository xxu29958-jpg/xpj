/* Theme toggle for /web desktop shell. */
(function (window, document) {
  "use strict";

  const app = window.TicketboxWeb = window.TicketboxWeb || {};
  const syncFailureMessage = "主题已在此设备生效，但未能同步到其他设备。请稍后重试。";
  let syncRevision = 0;

  function setThemeStatus(message) {
    const status = document.querySelector("[data-theme-sync-status]");
    if (!status) return;
    status.textContent = message;
    status.hidden = !message;
  }

  app.applyTheme = function applyTheme(theme) {
    if (!app.THEMES.includes(theme)) theme = "paper";
    document.documentElement.setAttribute("data-theme", theme);
    document.querySelectorAll("[data-theme-choice]").forEach(function (choice) {
      choice.setAttribute(
        "aria-pressed",
        choice.getAttribute("data-theme-choice") === theme ? "true" : "false"
      );
    });
    try { localStorage.setItem("ui-theme", theme); } catch (_) {}
    // SSR 用 cookie 读取主题以避免下次刷新闪烁
    document.cookie = "ui_theme=" + theme + ";path=/;max-age=31536000;samesite=lax";
    if (document.documentElement.getAttribute("data-theme-sync") !== "server") {
      setThemeStatus("");
      return Promise.resolve(true);
    }
    const revision = ++syncRevision;
    if (typeof fetch !== "function") {
      setThemeStatus(syncFailureMessage);
      return Promise.resolve(false);
    }
    return fetch("/api/me/ui-preferences", {
      method: "PUT",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ theme: theme }),
    }).then(function (response) {
      if (!response.ok) {
        throw new Error("theme sync failed with status " + response.status);
      }
      if (revision === syncRevision) setThemeStatus("");
      return true;
    }).catch(function () {
      if (revision === syncRevision) setThemeStatus(syncFailureMessage);
      return false;
    });
  };

  app.initThemeToggle = function initThemeToggle() {
    const choices = Array.from(document.querySelectorAll("[data-theme-choice]"));
    if (!choices.length) return;
    const current = document.documentElement.getAttribute("data-theme") || "paper";
    choices.forEach(function (choice) {
      const theme = choice.getAttribute("data-theme-choice");
      choice.setAttribute("aria-pressed", theme === current ? "true" : "false");
      choice.addEventListener("click", function () {
        app.applyTheme(theme);
      });
    });
  };
})(window, document);
