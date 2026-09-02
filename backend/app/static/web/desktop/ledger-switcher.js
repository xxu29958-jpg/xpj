/* Ledger switcher disclosure for /web product shell.
   W1 repair: 根是 <details> 原生披露 (无 JS 可开合/键盘/读屏诚实);
   点外部 / Escape 关闭由 core.js 的 bindDisclosureDismiss 共享便利层承担,
   本文件不再持有开合状态。 */
(function (window, document) {
  "use strict";

  const app = window.TicketboxWeb = window.TicketboxWeb || {};

  app.initLedgerSwitcher = function initLedgerSwitcher() {
    const root = document.getElementById("ledger-switcher");
    if (!root) return;
    app.bindDisclosureDismiss(root, "summary");
  };
})(window, document);
