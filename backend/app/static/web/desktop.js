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
    // 启动时把本地 mode 解析成渲染主题并对齐 <html data-theme> / ui_theme cookie。
    if (typeof app.currentThemeMode === "function" && typeof app.applyThemeMode === "function") {
      app.applyThemeMode(app.currentThemeMode());
    }

    call("initThemeControl");
    call("initBackgroundControl");
    call("initLedgerSwitcher");
    call("initShellKeyboard");
    call("initDrawer");
    call("initReviewKeyboard");
    call("initBulkBar");
    call("initReceiptSkeletons");
    call("initTrendChart");
    call("initCategoryDonut");
    call("initDragReorder");
    call("initSplitLayout");
    call("initInboxCapture");
    call("initInboxEnrichmentWatch");
  }

  app.boot = boot;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})(window, document);
