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
          updatedAt: el.getAttribute("data-updated-at") || ""
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
      form.querySelectorAll('input[name="expected_updated_at"]').forEach(function (n) { n.remove(); });
      entries.forEach(function (entry) {
        const h = document.createElement("input");
        h.type = "hidden";
        h.name = "expense_ids";
        h.value = entry.id;
        form.appendChild(h);

        if (entry.updatedAt) {
          const token = document.createElement("input");
          token.type = "hidden";
          token.name = "expected_updated_at";
          token.value = entry.updatedAt;
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
        handler();
      });
      el.addEventListener("keydown", function (e) {
        if (e.key !== " " && e.key !== "Enter") return;
        e.preventDefault();
        e.stopPropagation();
        handler();
      });
    }

    checks.forEach(function (cb) {
      bindCheckbox(cb, function () {
        cb.classList.toggle("checked");
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
    refresh();
  };
})(window, document);
