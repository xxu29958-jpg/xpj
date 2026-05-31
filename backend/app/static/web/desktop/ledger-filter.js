/* 账本流水 · 客户端类目即时过滤
 *
 * 由 confirmed.html 的 `.lfilter[data-ledger-filter]` 驱动:点类目 tab 即时显隐
 * `.timeline-row[data-cat]`,并把整天没有可见行的 `.lday` 日头一起收起。
 * 纯前端、不重载页面——升级自概念图里的静态 tab。
 */
(function () {
  "use strict";

  function applyFilter(stream, cat) {
    stream.querySelectorAll(".timeline-row[data-cat]").forEach(function (row) {
      row.style.display = !cat || row.dataset.cat === cat ? "" : "none";
    });
    // 整天行全隐 → 连日头一起收起（行排在各自 .lday 之后,直到下一个 .lday）
    stream.querySelectorAll(".lday").forEach(function (day) {
      var el = day.nextElementSibling;
      var anyVisible = false;
      while (el && !el.classList.contains("lday")) {
        if (el.classList.contains("timeline-row") && el.style.display !== "none") {
          anyVisible = true;
        }
        el = el.nextElementSibling;
      }
      day.style.display = anyVisible ? "" : "none";
    });
  }

  function init() {
    var bar = document.querySelector("[data-ledger-filter]");
    var stream = document.querySelector(".ledger-stream");
    if (!bar || !stream) {
      return;
    }
    bar.addEventListener("click", function (event) {
      var btn = event.target.closest(".lf");
      if (!btn) {
        return;
      }
      bar.querySelectorAll(".lf").forEach(function (b) {
        b.classList.toggle("on", b === btn);
      });
      applyFilter(stream, btn.dataset.cat || "");
      // 可见行集合变了:通知 bulk-bar 重算计数 + 重建提交字段(剔除隐藏行)。
      if (window.TicketboxWeb && typeof window.TicketboxWeb.refreshBulkBar === "function") {
        window.TicketboxWeb.refreshBulkBar();
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
