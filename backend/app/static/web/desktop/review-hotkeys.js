/* 批10: keyboard pipeline for the待确认 review queue.
 *
 *   J / K      move the selection down / up through the visible rows
 *   Enter      open the selected row's edit drawer
 *   Ctrl/⌘+Enter   confirm the row in the open drawer (= 确认并下一笔)
 *
 * Progressive enhancement on top of the existing mouse flow — every action is
 * still reachable by click. Typing is never hijacked: while an input / textarea
 * / select / contenteditable holds focus, only Ctrl/⌘+Enter is honoured (so you
 * can confirm straight from an edited field); plain J/K/Enter fall through to
 * the field. Pairs with drawer.js via window.TicketboxWeb.drawerApi.
 */
(function (window, document) {
  "use strict";

  const app = window.TicketboxWeb = window.TicketboxWeb || {};

  app.initReviewHotkeys = function initReviewHotkeys() {
    const table = document.getElementById("exp-table");
    if (!table) return;

    function rows() {
      // Only rows still in the table and visible (filter tabs are server-side
      // here, but a removed row is gone from the DOM, so offsetParent guards
      // the rare hidden case).
      return Array.prototype.filter.call(
        table.querySelectorAll(".exp-row[data-fragment-url]"),
        function (r) { return r.offsetParent !== null; }
      );
    }

    function selectedIndex(list) {
      for (let i = 0; i < list.length; i++) {
        if (list[i].getAttribute("aria-selected") === "true") return i;
      }
      return -1;
    }

    function select(row, list) {
      list.forEach(function (r) {
        r.setAttribute("aria-selected", r === row ? "true" : "false");
      });
      if (row && row.scrollIntoView) {
        row.scrollIntoView({ block: "nearest" });
      }
    }

    function move(delta) {
      const list = rows();
      if (!list.length) return;
      let idx = selectedIndex(list);
      if (idx === -1) {
        idx = delta > 0 ? 0 : list.length - 1;
      } else {
        idx = Math.min(list.length - 1, Math.max(0, idx + delta));
      }
      select(list[idx], list);
    }

    function openSelected() {
      const list = rows();
      const idx = selectedIndex(list);
      const row = idx === -1 ? list[0] : list[idx];
      if (row && app.drawerApi) app.drawerApi.open(row);
    }

    function isTyping(el) {
      if (!el) return false;
      const tag = (el.tagName || "").toLowerCase();
      return tag === "input" || tag === "textarea" || tag === "select" || el.isContentEditable;
    }

    document.addEventListener("keydown", function (e) {
      // Ctrl/⌘+Enter confirms from anywhere (including an edited field).
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        if (app.drawerApi && app.drawerApi.isOpen() && app.drawerApi.submitConfirm()) {
          e.preventDefault();
        }
        return;
      }
      // Never hijack typing or modified chords beyond the Ctrl+Enter above.
      if (isTyping(e.target) || e.altKey || e.ctrlKey || e.metaKey) return;
      // While the drawer is open, leave plain keys to the form (Esc closes it,
      // handled in drawer.js).
      if (app.drawerApi && app.drawerApi.isOpen()) return;

      if (e.key === "j" || e.key === "J") {
        e.preventDefault();
        move(1);
      } else if (e.key === "k" || e.key === "K") {
        e.preventDefault();
        move(-1);
      } else if (e.key === "Enter") {
        e.preventDefault();
        openSelected();
      }
    });
  };
})(window, document);
