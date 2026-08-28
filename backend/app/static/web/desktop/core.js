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

  // 收件页原生上传表单的渐进增强：权限所需 ledger 已在 action query，
  // 这里只补浏览器时区；不触碰 multipart body，也绝不自动提交。
  app.initInboxCapture = function initInboxCapture() {
    const form = document.querySelector("[data-inbox-capture]");
    if (!form) return;
    try {
      const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      if (typeof tz !== "string" || !tz) return;
      const action = new URL(form.action, window.location.href);
      action.searchParams.set("timezone", tz);
      form.action = action.pathname + action.search;
    } catch (_) {}
  };

  app.initInboxEnrichmentWatch = function initInboxEnrichmentWatch() {
    const marker = document.querySelector("[data-inbox-enrichment-watch]");
    if (!marker) return;
    const delayMs = 1500;
    const fetchTimeoutMs = 5000;
    const configuredTimeoutMs = Number(marker.dataset.watchTimeoutMs);
    const watchTimeoutMs = Number.isFinite(configuredTimeoutMs) && configuredTimeoutMs > 0
      ? configuredTimeoutMs
      : 30000;
    const deadline = Date.now() + watchTimeoutMs;

    const stopWaiting = function stopWaiting() {
      marker.setAttribute("aria-busy", "false");
      const message = marker.querySelector("span");
      if (message) {
        message.textContent = "识别仍在处理中或未返回可用字段；可以稍后刷新，也可直接手动补全。";
      }
    };

    const poll = async function poll() {
      if (Date.now() >= deadline) {
        stopWaiting();
        return;
      }
      const controller = new AbortController();
      const requestTimer = window.setTimeout(function abortSlowPoll() {
        controller.abort();
      }, Math.min(fetchTimeoutMs, Math.max(1, deadline - Date.now())));
      try {
        const response = await fetch(window.location.href, {
          cache: "no-store",
          headers: {Accept: "text/html"},
          signal: controller.signal
        });
        if (response.ok) {
          const next = new DOMParser().parseFromString(await response.text(), "text/html");
          if (next.querySelector("[data-inbox-enrichment-terminal]")) {
            window.location.replace(window.location.href);
            return;
          }
          if (!next.querySelector("[data-inbox-enrichment-watch]")) {
            stopWaiting();
            return;
          }
        }
      } catch (_) {
        // A transient network failure is retried within the server-provided
        // OCR deadline. Each individual fetch is independently bounded.
      } finally {
        window.clearTimeout(requestTimer);
      }
      const remainingMs = deadline - Date.now();
      if (remainingMs <= 0) {
        stopWaiting();
        return;
      }
      window.setTimeout(poll, Math.min(delayMs, remainingMs));
    };

    window.setTimeout(poll, delayMs);
  };
})(window, document);
