/* Swipe row gesture helper. */
(function (window, document) {
  "use strict";

  const app = window.TicketboxWeb = window.TicketboxWeb || {};

  app.initSwipeRow = function initSwipeRow() {
    const THRESHOLD = 0.30; // 行宽 30% 触发
    document.querySelectorAll("[data-swipe-row]").forEach(function (row) {
      if (row.getAttribute("data-swipe-bound") === "1") return;
      row.setAttribute("data-swipe-bound", "1");

      let startX = 0, currentX = 0, dragging = false;
      const fg = row.querySelector("[data-swipe-fg]") || row;

      function start(x) {
        startX = x; currentX = 0; dragging = true;
        fg.style.transition = "none";
      }
      function move(x) {
        if (!dragging) return;
        currentX = x - startX;
        const max = row.clientWidth;
        const clamped = Math.max(-max, Math.min(max, currentX));
        fg.style.transform = "translateX(" + clamped + "px)";
        row.setAttribute("data-swipe-dir", clamped > 0 ? "right" : clamped < 0 ? "left" : "");
      }
      function end() {
        if (!dragging) return;
        dragging = false;
        const max = row.clientWidth;
        const trigger = max * THRESHOLD;
        fg.style.transition = "transform var(--motion-swipe-reveal, 180ms) var(--ease-standard, ease)";
        fg.style.transform = "translateX(0)";
        row.removeAttribute("data-swipe-dir");
        if (currentX > trigger) {
          row.dispatchEvent(new CustomEvent("swipe-action", { detail: { direction: "right" }, bubbles: true }));
        } else if (currentX < -trigger) {
          row.dispatchEvent(new CustomEvent("swipe-action", { detail: { direction: "left" }, bubbles: true }));
        }
      }

      row.addEventListener("touchstart", function (e) { start(e.touches[0].clientX); }, { passive: true });
      row.addEventListener("touchmove",  function (e) { move(e.touches[0].clientX); }, { passive: true });
      row.addEventListener("touchend",   end);
      row.addEventListener("touchcancel", end);

      // 鼠标支持：必须按住才算 drag，避免误触发点击
      let mouseDown = false;
      row.addEventListener("mousedown", function (e) {
        // 跳过 input / button / a 等交互元素，避免和点击冲突
        const tag = (e.target.tagName || "").toLowerCase();
        if (tag === "input" || tag === "button" || tag === "a" || tag === "select" || tag === "textarea") return;
        mouseDown = true; start(e.clientX);
      });
      row.addEventListener("mousemove", function (e) { if (mouseDown) move(e.clientX); });
      window.addEventListener("mouseup", function () { if (mouseDown) { mouseDown = false; end(); } });
    });
  };
})(window, document);
