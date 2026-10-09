/* Shared helpers for /web desktop scripts. */
(function (window, document) {
  "use strict";

  const app = window.TicketboxWeb = window.TicketboxWeb || {};
  const UNKNOWN_MONEY_TEXT = "金额不可用";

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

  // Native constraint validation must reveal the real field before focusing it.
  // Shared by budget options, debt details and other progressive disclosures.
  app.initFormDisclosures = function initFormDisclosures() {
    app.bindReviewFields(document);
    document.addEventListener("invalid", function (event) {
      let disclosure = event.target.closest("details");
      while (disclosure) {
        disclosure.open = true;
        disclosure = disclosure.parentElement?.closest("details");
      }
    }, true);
  };

  // The disclosure reads the real input, preserving raw long values without
  // rounding or a second draft. Used by review, correction and restored rows.
  app.bindReviewFields = function bindReviewFields(root) {
    root.querySelectorAll("[data-review-value]").forEach(function (output) {
      if (output.dataset.bound) return;
      output.dataset.bound = "true";
      const field = output.closest("details");
      const input = field.querySelector('[name="' + output.dataset.reviewValue + '"]');
      function showValue() {
        output.textContent = input.value
          ? (input.tagName === "SELECT" ? input.selectedOptions[0].textContent.trim() : input.value)
          : output.dataset.empty;
        (output.closest("[data-review-display]") || output).hidden = input.value === output.dataset.reviewHideValue;
      }
      input.addEventListener("input", showValue);
      showValue();
      if (!field.hasAttribute("data-review-line")) {
        field.open = !input.value || input.getAttribute("aria-invalid") === "true";
      }
    });
  };

  app.readReviewRows = function readReviewRows(form, columns) {
    return [...form.querySelectorAll('[name="' + columns[0] + '"]')].map(input => {
      const row = input.closest("[data-review-line]");
      return Object.fromEntries(columns.map(name => [name, row.querySelector('[name="' + name + '"]').value]));
    });
  };
  app.putReviewField = function putReviewField(input, value) {
    if (!input.tagName) {
      [...input].forEach(option => { option.checked = option.value === value; });
      return;
    }
    if (input.tagName === "SELECT" && ![...input.options].some(option => option.value === value)) {
      input.add(new Option(value || "原选择为空", value));
    }
    if (["number", "date", "datetime-local"].includes(input.type)) {
      input.value = value;
      if (input.value !== value) input.type = "text";
    }
    input.value = value;
  };
  app.restoreReviewRows = function restoreReviewRows(form, columns, encoded) {
    const original = form.querySelector('[name="' + columns[0] + '"]');
    const prototype = original.closest("[data-review-line]").cloneNode(true);
    const parent = original.closest(".expense-lines-editor");
    const additions = parent.querySelector(".expense-line-additions")?.cloneNode(true);
    additions?.querySelectorAll("[data-review-line]").forEach(row => row.remove());
    if (additions) additions.open = false;
    const rows = JSON.parse(encoded);
    const lastData = rows.findLastIndex(values => columns.some(name => name !== "item_kind" && values[name]));
    parent.replaceChildren();
    rows.forEach((values, index) => {
      const row = prototype.cloneNode(true);
      row.hidden = index > lastData && !additions; row.open = index === lastData + 1;
      row.querySelectorAll("[data-bound]").forEach(node => node.removeAttribute("data-bound"));
      row.querySelectorAll(".field-error, .meta").forEach(node => node.remove());
      row.querySelectorAll("[aria-describedby]").forEach(node => node.removeAttribute("aria-describedby"));
      columns.forEach(name => {
        const input = row.querySelector('[name="' + name + '"]');
        app.putReviewField(input, values[name]);
        if (input.hasAttribute("aria-label")) input.setAttribute("aria-label", input.getAttribute("aria-label").replace(/第 \d+ 行/, "第 " + (index + 1) + " 行"));
      });
      if (index === lastData + 1 && additions) parent.append(additions);
      (index > lastData && additions ? additions : parent).append(row);
    });
    app.bindReviewFields(parent);
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

  // Read-only repayment/refund estimate. Currency precision and balance come
  // from the displayed server snapshot; this never changes or accepts input.
  app.remainingMoneyPreview = function remainingMoneyPreview(value, before, digits) {
    if (!Number.isInteger(digits) || digits < 0 || digits > 20 || !/^[0-9]+$/.test(before)) return null;
    const match = /^(0|[1-9][0-9]*)(?:\.([0-9]+))?$/.exec(value.trim());
    if (!match) return null;
    const fraction = match[2] || "";
    if (/[^0]/.test(fraction.slice(digits))) return null;
    const scale = 10n ** BigInt(digits);
    const minor = BigInt(match[1]) * scale + BigInt(fraction.slice(0, digits).padEnd(digits, "0") || "0");
    if (minor <= 0n || minor > BigInt(before)) return null;
    const after = BigInt(before) - minor;
    const whole = (after / scale).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    return whole + (digits ? "." + (after % scale).toString().padStart(digits, "0") : "");
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

  // Canvas keeps its first text measurements; load the chart's actual glyphs
  // before drawing. A missing font must still leave the financial chart usable.
  app.withChartFonts = function withChartFonts(text, render) {
    if (!document.fonts) { render(); return; }
    const family = app.readVar("--font-numeric") || "sans-serif";
    document.fonts.load("12px " + family, text).then(render, render);
  };

  // 原生 <details> 披露的共享便利层: 点外部 / Escape 关闭并把焦点还回
  // trigger。开合状态由 <details open> 原生持有 (无 JS 可用), 本层只做增强。
  // 两个真实 consumer: 外观 popover (theme.js) 与「我」账户面板
  // (ledger-switcher.js)。
  app.bindDisclosureDismiss = function bindDisclosureDismiss(host, triggerSelector) {
    if (!host) return;
    document.addEventListener("click", (event) => {
      if (host.hasAttribute("open") && !host.contains(event.target)) {
        host.removeAttribute("open");
      }
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && host.hasAttribute("open")) {
        host.removeAttribute("open");
        const trigger = triggerSelector ? host.querySelector(triggerSelector) : null;
        if (trigger && typeof trigger.focus === "function") trigger.focus();
      }
    });
  };

  app.initInboxFilters = function initInboxFilters() {
    const filters = document.querySelector(".inbox-filters .product-segments");
    const active = filters && filters.querySelector('[aria-current="page"]');
    if (!active) return;
    const viewport = filters.getBoundingClientRect();
    const selected = active.getBoundingClientRect();
    if (selected.right > viewport.right) filters.scrollLeft += selected.right - viewport.right;
    else if (selected.left < viewport.left) filters.scrollLeft -= viewport.left - selected.left;
  };

  app.initInboxEnrichmentWatch = function initInboxEnrichmentWatch(root = document) {
    const marker = root.querySelector("[data-inbox-enrichment-watch]");
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
      if (!marker.isConnected || Date.now() >= deadline) {
        stopWaiting();
        return;
      }
      const controller = new AbortController();
      const requestTimer = window.setTimeout(function abortSlowPoll() {
        controller.abort();
      }, Math.min(fetchTimeoutMs, Math.max(1, deadline - Date.now())));
      try {
        const response = await fetch(marker.dataset.watchHref || window.location.href, {
          cache: "no-store",
          headers: {Accept: "text/html"},
          signal: controller.signal
        });
        if (response.ok) {
          const next = new DOMParser().parseFromString(await response.text(), "text/html");
          const terminal = next.querySelector("[data-inbox-enrichment-terminal]");
          if (terminal) {
            if (marker.hasAttribute("data-watch-inline")) {
              marker.setAttribute("aria-busy", "false");
              marker.querySelector("span").textContent = terminal.textContent.trim();
              marker.dispatchEvent(new CustomEvent("recognitioncomplete", {detail: {state: terminal.dataset.enrichmentState}}));
            } else window.location.replace(window.location.href);
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
