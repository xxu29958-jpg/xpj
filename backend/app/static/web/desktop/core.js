/* Shared helpers for /web desktop scripts. */
(function (window, document) {
  "use strict";

  const app = window.TicketboxWeb = window.TicketboxWeb || {};

  app.THEMES = ["paper", "mono", "midnight"];

  app.escapeHtml = function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  };

  app.homeCurrencySymbol = function homeCurrencySymbol() {
    return document.documentElement.getAttribute("data-home-currency-symbol") ||
      document.documentElement.getAttribute("data-home-currency") ||
      "";
  };

  app.homeMoney = function homeMoney(value) {
    return app.homeCurrencySymbol() + app.escapeHtml(value);
  };

  app.dashboardUrl = function dashboardUrl(path, ledgerId, extra) {
    const params = new URLSearchParams(extra || {});
    if (ledgerId) params.set("ledger_id", ledgerId);
    const query = params.toString();
    return path + (query ? "?" + query : "");
  };

  app.moneyParts = function moneyParts(value) {
    const raw = String(value || "0.00");
    const parts = raw.split(".");
    return [parts[0] || "0", parts[1] || "00"];
  };

  app.readVar = function readVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  };
})(window, document);
