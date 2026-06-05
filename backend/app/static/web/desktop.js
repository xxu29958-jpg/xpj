/* /web 桌面账本 · v0.10 bootstrap
 *
 * Feature modules live in /static/web/desktop/*.js and attach their init
 * functions to window.TicketboxWeb. This entrypoint keeps the existing
 * non-module script loading model used by base.html.
 */
(function (window, document) {
  "use strict";

  const app = window.TicketboxWeb || {};

  function call(name) {
    const fn = app[name];
    if (typeof fn === "function") fn();
  }

  function boot() {
    // 启动时先把 cookie / localStorage 与 <html data-theme> 对齐（防止刷新闪烁）
    let saved = null;
    try { saved = localStorage.getItem("ui-theme"); } catch (_) {}
    if (saved && app.THEMES && app.THEMES.includes(saved)) {
      const current = document.documentElement.getAttribute("data-theme");
      if (current !== saved) document.documentElement.setAttribute("data-theme", saved);
    }

    call("initThemeToggle");
    call("initLedgerSwitcher");
    call("initSparks");
    call("initDrawer");
    call("initBulkBar");
    call("initReceiptSkeletons");
    call("initDashboard");
    call("initTrendChart");
    call("initCategoryDonut");
    call("initDragReorder");
    call("initSplitLayout");
  }

  app.boot = boot;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})(window, document);
