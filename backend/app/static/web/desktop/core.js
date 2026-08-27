/* Shared helpers for /web desktop scripts. */
(function (window, document) {
  "use strict";

  const app = window.TicketboxWeb = window.TicketboxWeb || {};
  const UNKNOWN_MONEY_TEXT = "金额不可用";

  app.THEMES = ["paper", "mono", "midnight"];

  app.escapeHtml = function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  };

  app.homeCurrencyCode = function homeCurrencyCode() {
    const raw = document.documentElement.getAttribute("data-home-currency");
    return typeof raw === "string" && /^[A-Z]{3}$/.test(raw) ? raw : "";
  };

  app.homeCurrencySymbol = function homeCurrencySymbol() {
    const raw = document.documentElement.getAttribute("data-home-currency-symbol");
    const symbol = typeof raw === "string" ? raw.trim() : "";
    if (symbol) return symbol;
    const code = app.homeCurrencyCode();
    return code ? code + " " : "币种未知 ";
  };

  // PR #253 R5: 币种 exponent 经 base.html 的 data-home-currency-minor-digits
  // 下发 (源: currency_common.minor_unit_digits), 图表中心值/大数字按此格式化。
  app.homeCurrencyMinorDigits = function homeCurrencyMinorDigits() {
    const raw = document.documentElement.getAttribute("data-home-currency-minor-digits");
    if (typeof raw !== "string" || !/^(?:0|[1-9][0-9]*)$/.test(raw)) return null;
    const parsed = Number(raw);
    return Number.isSafeInteger(parsed) && parsed <= 20 ? parsed : null;
  };

  app.homeMajorNumber = function homeMajorNumber(value) {
    const digits = app.homeCurrencyMinorDigits();
    if (digits === null) return UNKNOWN_MONEY_TEXT;
    const raw = value == null || value === "" ? "0" : String(value);
    if (!/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/.test(raw)) {
      return UNKNOWN_MONEY_TEXT;
    }
    return new Intl.NumberFormat("zh-CN", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
      useGrouping: true,
    }).format(raw);
  };

  app.homeMinorToMajorText = function homeMinorToMajorText(value) {
    let raw;
    if (typeof value === "bigint") {
      raw = value.toString();
    } else if (typeof value === "number" && Number.isSafeInteger(value)) {
      raw = String(value);
    } else {
      raw = String(value == null || value === "" ? "0" : value);
    }
    if (!/^-?(?:0|[1-9][0-9]*)$/.test(raw)) return null;
    const digits = app.homeCurrencyMinorDigits();
    if (digits === null) return null;
    const amount = BigInt(raw);
    if (digits === 0) return amount.toString();
    const negative = amount < 0n;
    const absolute = negative ? -amount : amount;
    const scale = 10n ** BigInt(digits);
    const whole = absolute / scale;
    const fraction = String(absolute % scale).padStart(digits, "0");
    return (negative ? "-" : "") + whole.toString() + "." + fraction;
  };

  app.homeMinorToMajor = function homeMinorToMajor(value) {
    const amount = Number(value || 0);
    const digits = app.homeCurrencyMinorDigits();
    if (!Number.isSafeInteger(amount) || digits === null) return null;
    return amount / Math.pow(10, digits);
  };

  app.homeMoneyMinor = function homeMoneyMinor(value) {
    const major = app.homeMinorToMajorText(value);
    return app.homeCurrencySymbol() +
      (major === null ? UNKNOWN_MONEY_TEXT : app.homeMajorNumber(major));
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
    const digits = app.homeCurrencyMinorDigits();
    if (digits === null) return [UNKNOWN_MONEY_TEXT, ""];
    const raw = String(value == null || value === "" ? "0" : value);
    if (!/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/.test(raw)) {
      return [UNKNOWN_MONEY_TEXT, ""];
    }
    const parts = raw.split(".");
    if (digits === 0) {
      return parts.length === 1 ? [parts[0], ""] : [UNKNOWN_MONEY_TEXT, ""];
    }
    if (parts.length !== 2 || parts[1].length !== digits) {
      return [UNKNOWN_MONEY_TEXT, ""];
    }
    return [parts[0], parts[1]];
  };

  app.readVar = function readVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  };

  // K3: 收件页原生上传表单的渐进增强 — 仅填充 hidden timezone
  // (无 JS 时留空, 服务端回落默认时区), 绝不自动提交。
  app.initInboxCapture = function initInboxCapture() {
    const field = document.querySelector("[data-inbox-timezone]");
    if (!field) return;
    try {
      const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      if (typeof tz === "string" && tz) field.value = tz;
    } catch (_) {}
  };
})(window, document);
