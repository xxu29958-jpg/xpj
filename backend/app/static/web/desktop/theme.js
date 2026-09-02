/* Appearance control for /web product shell — 主题 × 质感 × 强调色 三条本地偏好轴。
 *
 * 用户偏好是本地 mode：paper / midnight 直接渲染，system 解析到平台明暗。
 * 渲染主题（<html data-theme> 与 ui_theme cookie）永远只有 paper / midnight ——
 * cookie 供 SSR 首屏避免闪烁，因此只保存已解析值，绝不保存 "system"。
 *
 * 质感 (data-texture: flat|fiber) 与强调色 (data-accent: evergreen|ink|ochre|plum)
 * 是同一级的浏览器本地偏好：只写 localStorage + <html> 属性，没有 cookie
 * (SSR 不需要它们: 共享的 appearance-bootstrap.js 在首屏前直接还原本地值,
 * base.html 与 auth/login.html 都挂它——inline script 会被 CSP 阻断)。
 * 三条轴都不登录、不上传、不跨端同步，不产生任何服务端事实。
 */
(function (window, document) {
  "use strict";

  const app = window.TicketboxWeb = window.TicketboxWeb || {};

  const MODES = ["paper", "midnight", "system"];
  const DARK_QUERY = "(prefers-color-scheme: dark)";
  const MODE_STORAGE_KEY = "ui-theme-mode";
  const BRAND_MARK_SOURCES = {
    paper: "/static/web/product/brand/brand-mark.png",
    midnight: "/static/web/product/brand/brand-mark-midnight.png",
  };

  // 质感/强调色的 storage key、合法值、默认值由 appearance-bootstrap.js 暴露的
  // TicketboxAppearance 合同唯一持有 (它在 head 无 defer 先行加载, 首帧前就要读);
  // 本文件只经合同读/写/应用, 不再持有第二份常量。
  const prefs = window.TicketboxAppearance;

  function readStored(key, allowed, fallback) {
    let saved = null;
    try { saved = localStorage.getItem(key); } catch (_) {}
    return allowed.includes(saved) ? saved : fallback;
  }

  function store(key, value) {
    try { localStorage.setItem(key, value); } catch (_) {}
  }

  function systemDark() {
    return typeof window.matchMedia === "function" && window.matchMedia(DARK_QUERY).matches;
  }

  // mode → 渲染主题；非法 mode 一律回落 paper（与 SSR 端 _read_ui_theme 的回落一致）。
  app.resolveThemeMode = function resolveThemeMode(mode) {
    if (mode === "system") return systemDark() ? "midnight" : "paper";
    return mode === "midnight" ? "midnight" : "paper";
  };

  app.currentThemeMode = function currentThemeMode() {
    return readStored(MODE_STORAGE_KEY, MODES, "paper");
  };

  app.currentTextureMode = function currentTextureMode() {
    // W1: 无显式偏好的新会话默认 fiber (纸纹上背景层); 显式 flat 永远尊重。
    return prefs.read("texture");
  };

  app.currentAccentMode = function currentAccentMode() {
    return prefs.read("accent");
  };

  function syncPressed(selector, current) {
    document.querySelectorAll(selector).forEach((btn) => {
      const value = btn.getAttribute(selector.slice(1, -1));
      btn.setAttribute("aria-pressed", value === current ? "true" : "false");
    });
  }

  function syncAppearanceControl() {
    syncPressed("[data-theme-mode]", app.currentThemeMode());
    syncPressed("[data-texture-mode]", app.currentTextureMode());
    syncPressed("[data-accent-mode]", app.currentAccentMode());
  }

  app.applyThemeMode = function applyThemeMode(mode) {
    if (!MODES.includes(mode)) mode = "paper";
    const resolved = app.resolveThemeMode(mode);
    document.documentElement.setAttribute("data-theme", resolved);
    store(MODE_STORAGE_KEY, mode);
    document.cookie = "ui_theme=" + resolved + ";path=/;max-age=31536000;samesite=lax";
    syncPressed("[data-theme-mode]", mode);
    // 品牌 mark 单 img 换色款: 运行时只采用受信任的产品资产映射，DOM
    // data-* 不参与 URL 决策；另一色款在切换发生前不会下载。
    document.querySelectorAll(".brand-mark-img").forEach((img) => {
      const next = BRAND_MARK_SOURCES[resolved];
      if (next && img.getAttribute("src") !== next) img.setAttribute("src", next);
    });
  };

  app.applyTextureMode = function applyTextureMode(mode) {
    const value = prefs.write("texture", mode);
    prefs.apply(document.documentElement, "texture", value);
    syncPressed("[data-texture-mode]", value);
  };

  app.applyAccentMode = function applyAccentMode(mode) {
    const value = prefs.write("accent", mode);
    prefs.apply(document.documentElement, "accent", value);
    syncPressed("[data-accent-mode]", value);
  };

  function bindAxis(root, attr, apply) {
    root.querySelectorAll("[" + attr + "]").forEach((btn) => {
      btn.addEventListener("click", () => apply(btn.getAttribute(attr)));
    });
  }

  app.initThemeControl = function initThemeControl() {
    // W1: 外观控件可多实例 (topbar 一枚, ≤40rem「我」popover 内一枚) —
    // 每个实例独立绑定, aria-pressed 由 syncPressed 跨文档同步。
    const roots = document.querySelectorAll("[data-appearance-popover]");
    // bootstrap 未加载 (静态资产失败) 时外观层整体不可用, 诚实静默退出。
    if (!roots.length || !prefs) return;

    // 对齐本地值（anti-FOUC bootstrap 之外的兜底：脚本被裁切/禁用后重进时
    // 也保证 <html> 属性、存储与按钮态三者一致）。
    app.applyTextureMode(app.currentTextureMode());
    app.applyAccentMode(app.currentAccentMode());

    roots.forEach((root) => {
      bindAxis(root, "data-theme-mode", app.applyThemeMode);
      bindAxis(root, "data-texture-mode", app.applyTextureMode);
      bindAxis(root, "data-accent-mode", app.applyAccentMode);

      // popover 行为：点外部 / Esc 关闭（<details> 原生开合之外的便利层,
      // 共享 helper 在 core.js）。nested 实例 (≤40rem「我」popover 内静态铺开)
      // 不绑关闭——它不是浮层。
      const host = root.closest(".appearance");
      if (host && !host.classList.contains("appearance--nested")) {
        app.bindDisclosureDismiss(host, "[data-appearance-trigger]");
      }
    });
    syncAppearanceControl();

    if (typeof window.matchMedia === "function") {
      window.matchMedia(DARK_QUERY).addEventListener("change", () => {
        // 仅 system mode 跟随平台配色变化；显式 paper/midnight 不被系统覆盖。
        if (app.currentThemeMode() === "system") app.applyThemeMode("system");
      });
    }
  };
})(window, document);
