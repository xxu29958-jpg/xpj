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

  // PR #253 R5: 币种 exponent 经 base.html 的 data-home-currency-minor-digits
  // 下发 (源: currency_common.minor_unit_digits), 图表中心值/大数字按此格式化。
  app.homeCurrencyMinorDigits = function homeCurrencyMinorDigits() {
    const raw = document.documentElement.getAttribute("data-home-currency-minor-digits");
    const parsed = Number.parseInt(raw == null ? "" : raw, 10);
    return Number.isInteger(parsed) && parsed >= 0 ? parsed : 2;
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

  app.homeMoneyMajor = function homeMoneyMajor(value) {
    return app.homeCurrencySymbol() + app.homeMajorNumber(value);
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
