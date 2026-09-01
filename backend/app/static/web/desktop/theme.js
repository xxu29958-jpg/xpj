/* Theme control for /web desktop shell.
 *
 * 用户偏好是本地 mode：paper / midnight 直接渲染，system 解析到平台明暗。
 * 渲染主题（<html data-theme> 与 ui_theme cookie）永远只有 paper / midnight ——
 * cookie 供 SSR 首屏避免闪烁，因此只保存已解析值，绝不保存 "system"。
 * 主题是浏览器本地偏好：不登录、不上传、不跨端同步。
 */
(function (window, document) {
  "use strict";

  const app = window.TicketboxWeb = window.TicketboxWeb || {};

  const MODES = ["paper", "midnight", "system"];
  const DARK_QUERY = "(prefers-color-scheme: dark)";
  const MODE_STORAGE_KEY = "ui-theme-mode";

  function systemDark() {
    return typeof window.matchMedia === "function" && window.matchMedia(DARK_QUERY).matches;
  }

  // mode → 渲染主题；非法 mode 一律回落 paper（与 SSR 端 _read_ui_theme 的回落一致）。
  app.resolveThemeMode = function resolveThemeMode(mode) {
    if (mode === "system") return systemDark() ? "midnight" : "paper";
    return mode === "midnight" ? "midnight" : "paper";
  };

  app.currentThemeMode = function currentThemeMode() {
    let saved = null;
    try { saved = localStorage.getItem(MODE_STORAGE_KEY); } catch (_) {}
    return MODES.includes(saved) ? saved : "paper";
  };

  function syncThemeControl(mode) {
    const control = document.getElementById("theme-control");
    if (!control) return;
    control.querySelectorAll("[data-theme-mode]").forEach((btn) => {
      btn.setAttribute("aria-pressed", btn.getAttribute("data-theme-mode") === mode ? "true" : "false");
    });
  }

  app.applyThemeMode = function applyThemeMode(mode) {
    if (!MODES.includes(mode)) mode = "paper";
    const resolved = app.resolveThemeMode(mode);
    document.documentElement.setAttribute("data-theme", resolved);
    try { localStorage.setItem(MODE_STORAGE_KEY, mode); } catch (_) {}
    document.cookie = "ui_theme=" + resolved + ";path=/;max-age=31536000;samesite=lax";
    syncThemeControl(mode);
  };

  app.initThemeControl = function initThemeControl() {
    const control = document.getElementById("theme-control");
    if (!control) return;
    control.querySelectorAll("[data-theme-mode]").forEach((btn) => {
      btn.addEventListener("click", () => app.applyThemeMode(btn.getAttribute("data-theme-mode")));
    });
    syncThemeControl(app.currentThemeMode());
    if (typeof window.matchMedia === "function") {
      window.matchMedia(DARK_QUERY).addEventListener("change", () => {
        // 仅 system mode 跟随平台配色变化；显式 paper/midnight 不被系统覆盖。
        if (app.currentThemeMode() === "system") app.applyThemeMode("system");
      });
    }
  };
})(window, document);
