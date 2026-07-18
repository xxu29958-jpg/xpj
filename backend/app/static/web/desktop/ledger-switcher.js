/* Ledger switcher dropdown for /web desktop shell. */
(function (window, document) {
  "use strict";

  const app = window.TicketboxWeb = window.TicketboxWeb || {};

  app.initLedgerSwitcher = function initLedgerSwitcher() {
    const root = document.getElementById("ledger-switcher");
    const trigger = document.getElementById("ledger-switcher-trigger");
    const popover = document.getElementById("ledger-popover");
    if (!root || !trigger || !popover) return;

    function setOpen(open) {
      popover.classList.toggle("open", open);
      root.setAttribute("data-open", open ? "true" : "false");
      trigger.setAttribute("aria-expanded", open ? "true" : "false");
    }

    trigger.addEventListener("click", function () {
      setOpen(!popover.classList.contains("open"));
    });

    document.addEventListener("click", function (e) {
      if (root.contains(e.target)) return;
      setOpen(false);
    });

    document.addEventListener("keydown", function (e) {
      if (e.key !== "Escape" || !popover.classList.contains("open")) return;
      setOpen(false);
      trigger.focus();
    });
  };
})(window, document);
