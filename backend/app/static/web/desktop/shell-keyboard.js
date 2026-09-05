/* Global shell keyboard shortcuts. Links remain the only navigation owners; this
 * module only clicks their real, permission-gated DOM consumers.
 *
 *   /   search
 *   N   manual expense
 *   U   upload a receipt
 */
(function (window, document) {
  "use strict";

  const app = window.TicketboxWeb = window.TicketboxWeb || {};

  function isTypingTarget(target) {
    return Boolean(
      target && target.closest &&
      target.closest('input, textarea, select, [contenteditable="true"]')
    );
  }

  app.initShellKeyboard = function initShellKeyboard() {
    document.addEventListener("keydown", function (event) {
      if (event.defaultPrevented || event.isComposing) return;
      if (event.altKey || event.ctrlKey || event.metaKey) return;
      if (isTypingTarget(event.target)) return;
      if (app.drawerApi && app.drawerApi.isOpen()) return;

      const key = event.key.toLowerCase();
      const shortcut = event.key === "/"
        ? "search"
        : key === "n"
          ? "manual-expense"
          : key === "u" ? "capture" : "";
      if (!shortcut) return;

      const link = document.querySelector('[data-shell-shortcut="' + shortcut + '"]');
      if (!link) return;
      event.preventDefault();
      link.click();
    });
  };
})(window, document);
