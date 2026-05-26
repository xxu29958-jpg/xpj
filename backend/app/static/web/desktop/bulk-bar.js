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

    function selectedEntries() {
      const entries = [];
      document.querySelectorAll(".row-check.checked").forEach(function (el) {
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
        const allChecked = checks.length > 0 && entries.length === checks.length;
        all.classList.toggle("checked", allChecked);
        all.setAttribute("aria-checked", allChecked ? "true" : (entries.length > 0 ? "mixed" : "false"));
      }
    }

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
          cb.classList.toggle("checked", turnOn);
        });
        refresh();
      });
    }
    refresh();
  };
})(window, document);
