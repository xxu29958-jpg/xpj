/* Bulk selection action bar. */
(function (window, document) {
  "use strict";

  const app = window.TicketboxWeb = window.TicketboxWeb || {};

  app.initBulkBar = function initBulkBar() {
    const form = document.querySelector("[data-bulk]");
    if (!form) return;
    const counter = form.querySelector("[data-bulk-count]");
    const all = document.getElementById("check-all");
    const checks = Array.from(document.querySelectorAll(".row-check"));

    // 被类目筛选隐藏的行不参与批选/提交,否则"全选"会误改用户没看见的别类目账单。
    function isVisible(cb) {
      const row = cb.closest(".exp-row, .timeline-row");
      return !row || row.offsetParent !== null;
    }

    function selectedEntries() {
      const entries = [];
      document.querySelectorAll(".row-check.checked").forEach(function (el) {
        if (!isVisible(el)) return;
        entries.push({
          id: el.getAttribute("data-id"),
          rowVersion: el.getAttribute("data-row-version") || ""
        });
      });
      return entries;
    }

    function refresh() {
      const entries = selectedEntries();
      counter.textContent = String(entries.length);
      form.classList.toggle("on", entries.length > 0);
      checks.forEach(function (cb) {
        const checked = cb.classList.contains("checked");
        const row = cb.closest(".exp-row, .timeline-row");
        cb.setAttribute("aria-checked", checked ? "true" : "false");
        if (row) {
          row.classList.toggle("selected", checked);
          row.setAttribute("aria-selected", checked ? "true" : "false");
        }
      });
      // 同步隐藏 input
      form.querySelectorAll('input[name="expense_ids"]').forEach(function (n) { n.remove(); });
      form.querySelectorAll('input[name="expected_row_version"]').forEach(function (n) { n.remove(); });
      entries.forEach(function (entry) {
        const h = document.createElement("input");
        h.type = "hidden";
        h.name = "expense_ids";
        h.value = entry.id;
        form.appendChild(h);

        if (entry.rowVersion) {
          const token = document.createElement("input");
          token.type = "hidden";
          token.name = "expected_row_version";
          token.value = entry.rowVersion;
          form.appendChild(token);
        }
      });
      if (all) {
        const visibleCount = checks.filter(isVisible).length;
        const allChecked = visibleCount > 0 && entries.length === visibleCount;
        all.classList.toggle("checked", allChecked);
        all.setAttribute("aria-checked", allChecked ? "true" : (entries.length > 0 ? "mixed" : "false"));
      }
    }

    // 暴露给 ledger-filter.js:筛选改变可见行后重算计数 + 重建提交字段。
    app.refreshBulkBar = refresh;

    function bindCheckbox(el, handler) {
      el.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        handler(e);
      });
      el.addEventListener("keydown", function (e) {
        if (e.key !== " " && e.key !== "Enter") return;
        e.preventDefault();
        e.stopPropagation();
        handler(e);
      });
    }

    // 批10: shift-click 范围连选。记最近点击的行 index;按住 shift 点另一行时,把
    // 区间内的可见行全部设成被点行的新状态(剔除隐藏行,与 isVisible 一致)。
    let lastIndex = -1;
    checks.forEach(function (cb, index) {
      bindCheckbox(cb, function (e) {
        const turnOn = !cb.classList.contains("checked");
        if (e && e.shiftKey && lastIndex !== -1 && lastIndex !== index) {
          const lo = Math.min(lastIndex, index);
          const hi = Math.max(lastIndex, index);
          for (let i = lo; i <= hi; i++) {
            if (!isVisible(checks[i])) continue; // 只作用可见行
            checks[i].classList.toggle("checked", turnOn);
          }
        } else {
          cb.classList.toggle("checked", turnOn);
        }
        lastIndex = index;
        refresh();
      });
    });
    if (all) {
      bindCheckbox(all, function () {
        const turnOn = !all.classList.contains("checked");
        checks.forEach(function (cb) {
          if (turnOn && !isVisible(cb)) return; // 全选只勾可见行
          cb.classList.toggle("checked", turnOn);
        });
        refresh();
      });
    }

    // issue #64 W3: progressive-enhancement fetch+partial for the two removal
    // bulk actions — 批量确认入账 (/web/review/bulk confirm_ready) and 批量忽略
    // (/web/pending/batch-reject). Both pop rows out of the pending list, so on
    // success the server answers {removed_ids, message, flash_type} and we
    // splice exactly those rows, clear the selection, nudge the filter counts,
    // and flash the summary — no full-page reload (mirrors drawer.js). The
    // in-place 设置分类/设置商家 actions stay on the native redirect. Any fetch
    // failure (offline) falls through to a native full-page submit.
    function submitterActionUrl(submitter) {
      return (submitter && submitter.getAttribute && submitter.getAttribute("formaction")) ||
        form.getAttribute("action") || "";
    }

    function removalKind(actionUrl, submitter) {
      if (/\/pending\/batch-reject$/.test(actionUrl)) return "reject";
      const value = (submitter && submitter.getAttribute && submitter.getAttribute("value")) || "";
      if (/\/review\/bulk$/.test(actionUrl) && value === "confirm_ready") return "confirm_ready";
      return null; // set_category / set_merchant → native full-page POST
    }

    function flashBanner(message, type) {
      if (!message) return;
      const content = document.querySelector("main.content");
      if (!content) return;
      let banner = document.getElementById("bulk-flash");
      if (!banner) {
        banner = document.createElement("div");
        banner.id = "bulk-flash";
        // Match the no-JS flash position: pending.html renders its .dt-alert
        // right after .page-header, so place ours there too (nextSibling null →
        // appended). Falls back to the top if the header isn't present.
        const header = content.querySelector(".page-header");
        content.insertBefore(banner, header ? header.nextSibling : content.firstElementChild);
      }
      // Reuse the server flash classes (alert.css) so the look matches the no-JS
      // redirect banner — no new CSS, no hardcoded values.
      banner.className = "dt-alert" +
        (type === "success" ? " success" : type === "error" ? " danger" : "");
      banner.textContent = message;
    }

    // Mirror drawer.js's count drift policy: decrement the active filter tab and
    // 全部 by however many rows actually left; the other tabs self-heal on the
    // next page load.
    function decrementFilterCounts(n) {
      if (n <= 0) return;
      const seen = [];
      const active = document.querySelector(".filter-tab.is-active .count");
      const total = document.querySelector(".filter-tab .count"); // 全部 is first
      [active, total].forEach(function (node) {
        if (!node || seen.indexOf(node) !== -1) return;
        seen.push(node);
        const cur = parseInt(node.textContent, 10);
        if (!isNaN(cur)) node.textContent = String(Math.max(0, cur - n));
      });
    }

    function clearSelection() {
      document.querySelectorAll(".row-check.checked").forEach(function (cb) {
        cb.classList.remove("checked");
      });
      refresh(); // 0 selected → hides the bar + rebuilds the hidden id fields
    }

    function applyBulkResult(data) {
      const ids = (data && data.removed_ids) || [];
      let removed = 0;
      ids.forEach(function (id) {
        const row = document.querySelector('.exp-row[data-expense-id="' + id + '"]');
        if (row && row.parentNode) { row.parentNode.removeChild(row); removed++; }
      });
      clearSelection();
      decrementFilterCounts(removed);
      flashBanner(data && data.message, (data && data.flash_type) || "success");
    }

    function setBulkBusy(busy) {
      form.querySelectorAll("button[type=submit]").forEach(function (b) {
        b.disabled = busy;
      });
    }

    function nativeFallback(actionUrl, submitter) {
      form.setAttribute("action", actionUrl);
      form.setAttribute("data-native-fallback", "1");
      // requestSubmit (not .submit()) fires the real submit event so csrf.js
      // injects csrf_token; passing the submitter keeps its name/value
      // (action=confirm_ready) + formaction. .submit() skips the event → 403.
      if (typeof form.requestSubmit === "function") {
        form.requestSubmit(submitter);
      } else {
        HTMLFormElement.prototype.submit.call(form);
      }
    }

    function submitBulk(actionUrl, submitter) {
      const body = new FormData(form);
      // FormData(form) omits the submit button — carry its name/value so
      // /web/review/bulk still sees action=confirm_ready. csrf.js's fetch
      // wrapper adds X-CSRF-Token; the form also carries the injected
      // csrf_token field, so the /web CSRF gate is satisfied either way.
      if (submitter && submitter.name) body.append(submitter.name, submitter.value);
      body.append("fragment", "1");
      setBulkBusy(true);
      fetch(actionUrl, { method: "POST", credentials: "same-origin", body: body })
        .then(function (res) {
          return res.json().then(function (data) { return { ok: res.ok, data: data }; });
        })
        .then(function (out) {
          setBulkBusy(false);
          if (out.ok) {
            applyBulkResult(out.data);
          } else {
            flashBanner((out.data && out.data.message) || "操作失败，请重试。", "error");
          }
        })
        .catch(function () {
          setBulkBusy(false);
          nativeFallback(actionUrl, submitter);
        });
    }

    function bindSubmit() {
      if (form.getAttribute("data-fetch-bound") === "1") return;
      form.setAttribute("data-fetch-bound", "1");
      form.addEventListener("submit", function (e) {
        // Offline-fallback re-entry guard: requestSubmit() re-fires this listener.
        if (form.getAttribute("data-native-fallback") === "1") return;
        const submitter = e.submitter || document.activeElement;
        const actionUrl = submitterActionUrl(submitter);
        const kind = removalKind(actionUrl, submitter);
        if (!kind) return; // not a removal action → leave the native submit alone
        e.preventDefault();
        // confirm-modal latches data-confirm buttons (批量忽略) with _tbConfirmed.
        // Without a reload that flag persists and skips the dialog next time —
        // clear it so the next 批量忽略 re-prompts.
        if (submitter && submitter.dataset) delete submitter.dataset._tbConfirmed;
        submitBulk(actionUrl, submitter);
      });
    }

    bindSubmit();
    refresh();
  };
})(window, document);
