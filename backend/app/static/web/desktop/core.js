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

  app.homeCurrencyCode = function homeCurrencyCode() {
    return document.documentElement.getAttribute("data-home-currency") || "";
  };

  app.homeCurrencyMinorDigits = function homeCurrencyMinorDigits() {
    const raw = document.documentElement.getAttribute("data-home-currency-minor-digits");
    const parsed = Number.parseInt(raw == null ? "" : raw, 10);
    return Number.isInteger(parsed) && parsed >= 0 ? parsed : 2;
  };

  app.homeMoney = function homeMoney(value) {
    return app.homeCurrencySymbol() + app.escapeHtml(value);
  };

  app.homeMajorNumber = function homeMajorNumber(value) {
    const amount = Number(value || 0);
    const digits = app.homeCurrencyMinorDigits();
    return new Intl.NumberFormat("zh-CN", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
      useGrouping: true,
    }).format(Number.isFinite(amount) ? amount : 0);
  };

  app.homeMinorToMajor = function homeMinorToMajor(value) {
    const amount = Number(value || 0);
    const scale = 10 ** app.homeCurrencyMinorDigits();
    return (Number.isFinite(amount) ? amount : 0) / scale;
  };

  app.homeMoneyMinor = function homeMoneyMinor(value) {
    return app.homeCurrencySymbol() + app.homeMajorNumber(app.homeMinorToMajor(value));
  };

  app.homeMoneyMajor = function homeMoneyMajor(value) {
    return app.homeCurrencySymbol() + app.homeMajorNumber(value);
  };

  app.homeCompactMoneyMajor = function homeCompactMoneyMajor(value) {
    const amount = Number(value || 0);
    const formatted = new Intl.NumberFormat("zh-CN", {
      notation: "compact",
      maximumFractionDigits: 1,
    }).format(Number.isFinite(amount) ? amount : 0);
    return app.homeCurrencySymbol() + formatted;
  };

  app.dashboardUrl = function dashboardUrl(path, ledgerId, extra) {
    const params = new URLSearchParams(extra || {});
    if (ledgerId) params.set("ledger_id", ledgerId);
    const query = params.toString();
    return path + (query ? "?" + query : "");
  };

  app.moneyParts = function moneyParts(value) {
    const digits = app.homeCurrencyMinorDigits();
    const raw = String(value == null || value === "" ? app.homeMajorNumber(0) : value);
    const parts = raw.split(".");
    return [parts[0] || "0", digits > 0 ? (parts[1] || "0".repeat(digits)) : ""];
  };

  app.readVar = function readVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  };
})(window, document);
