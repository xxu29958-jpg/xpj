/* Ledger switcher dropdown for /web desktop shell. */
(function (window, document) {
  "use strict";

  const app = window.TicketboxWeb = window.TicketboxWeb || {};

  app.initLedgerSwitcher = function initLedgerSwitcher() {
    const root = document.getElementById("ledger-switcher");
    const popover = document.getElementById("ledger-popover");
    if (!root || !popover) return;
    root.addEventListener("click", function (e) {
      // 仅当点击 chip 自身（非 popover 行）时翻转
      if (popover.contains(e.target)) return;
      const open = popover.classList.toggle("open");
      root.setAttribute("data-open", open ? "true" : "false");
    });
    document.addEventListener("click", function (e) {
      if (root.contains(e.target)) return;
      popover.classList.remove("open");
      root.setAttribute("data-open", "false");
    });
  };
})(window, document);
