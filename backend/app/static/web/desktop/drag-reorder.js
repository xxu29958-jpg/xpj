/* HTML5 drag reorder helper. */
(function (window, document) {
  "use strict";

  const app = window.TicketboxWeb = window.TicketboxWeb || {};

  app.initDragReorder = function initDragReorder() {
    document.querySelectorAll("[data-drag-reorder]").forEach(function (container) {
      if (container.getAttribute("data-drag-reorder-bound") === "1") return;
      container.setAttribute("data-drag-reorder-bound", "1");

      function rowsArr() {
        return Array.from(container.querySelectorAll('[draggable="true"][data-reorder-key]'));
      }
      function emit() {
        const order = rowsArr().map(function (el) { return el.getAttribute("data-reorder-key"); });
        container.dispatchEvent(new CustomEvent("drag-reorder-change", { detail: { order: order } }));
      }

      let dragged = null;
      container.addEventListener("dragstart", function (e) {
        const t = e.target.closest('[draggable="true"][data-reorder-key]');
        if (!t || !container.contains(t)) return;
        dragged = t;
        t.classList.add("dragging");
        try { e.dataTransfer.effectAllowed = "move"; } catch (_) {}
        try { e.dataTransfer.setData("text/plain", t.getAttribute("data-reorder-key")); } catch (_) {}
      });
      container.addEventListener("dragend", function () {
        if (dragged) dragged.classList.remove("dragging");
        dragged = null;
      });
      container.addEventListener("dragover", function (e) {
        if (!dragged) return;
        e.preventDefault();
        const after = afterElement(container, e.clientY);
        if (after == null) {
          container.appendChild(dragged);
        } else if (after !== dragged) {
          container.insertBefore(dragged, after);
        }
      });
      container.addEventListener("drop", function (e) {
        if (!dragged) return;
        e.preventDefault();
        emit();
      });
    });
    function afterElement(container, y) {
      const els = Array.from(container.querySelectorAll('[draggable="true"][data-reorder-key]:not(.dragging)'));
      let closest = { offset: Number.NEGATIVE_INFINITY, el: null };
      for (let i = 0; i < els.length; i++) {
        const rect = els[i].getBoundingClientRect();
        const offset = y - rect.top - rect.height / 2;
        if (offset < 0 && offset > closest.offset) closest = { offset: offset, el: els[i] };
      }
      return closest.el;
    }
  };
})(window, document);
