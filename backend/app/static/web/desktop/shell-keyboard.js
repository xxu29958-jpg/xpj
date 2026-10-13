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
    const menuSelector = ".topbar-create, .inbox-more-filters, .review-more-actions";
    const shortcuts = new Map([
      ["/", "search"], ["n", "manual-expense"], ["u", "capture"]
    ]);
    document.addEventListener("click", function (event) {
      document.querySelectorAll(menuSelector).forEach(function (menu) {
        if (!menu.contains(event.target) || event.target.closest("a")) menu.open = false;
      });
    });
    document.addEventListener("keydown", function (event) {
      if (event.defaultPrevented || event.isComposing) return;
      if (event.key === "Escape") {
        const menu = event.target.closest(menuSelector);
        if (menu && menu.open) {
          event.preventDefault();
          menu.open = false;
          menu.querySelector("summary").focus();
          return;
        }
      }
      if (event.altKey || event.ctrlKey || event.metaKey) return;
      if (isTypingTarget(event.target)) return;
      if (app.drawerApi && app.drawerApi.isOpen()) return;

      const shortcut = shortcuts.get(event.key.toLowerCase());
      if (!shortcut) return;

      const link = document.querySelector('[data-shell-shortcut="' + shortcut + '"]');
      if (!link) return;
      event.preventDefault();
      link.click();
    });
  };
})(window, document);
