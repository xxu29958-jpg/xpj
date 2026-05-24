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

    function selectedIds() {
      const ids = [];
      document.querySelectorAll(".row-check.checked").forEach(function (el) {
        ids.push(el.getAttribute("data-id"));
      });
      return ids;
    }

    function refresh() {
      const ids = selectedIds();
      counter.textContent = String(ids.length);
      form.classList.toggle("on", ids.length > 0);
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
      ids.forEach(function (id) {
        const h = document.createElement("input");
        h.type = "hidden";
        h.name = "expense_ids";
        h.value = id;
        form.appendChild(h);
      });
      if (all) {
        const allChecked = checks.length > 0 && ids.length === checks.length;
        all.classList.toggle("checked", allChecked);
        all.setAttribute("aria-checked", allChecked ? "true" : (ids.length > 0 ? "mixed" : "false"));
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
