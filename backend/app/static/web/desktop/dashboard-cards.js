/* 仪表盘卡片设置: 拖排后把可见顺序写回每行的 position 数字输入框,
   让 /web/dashboard/cards/save 的现有 native form POST (card_key × card_position
   按索引配对) 语义不变。原 dashboard_cards.html 内联脚本在 CSP script-src 'self'
   下不执行 —— 拖排后保存不落库; 此外部脚本是同一监听的合规载体。
   无 JS 时数字输入仍是可用的排序路径 (noJS fallback)。 */
(function (window, document) {
  "use strict";

  function init() {
    var list = document.getElementById("dashboard-cards-list");
    if (!list) return;
    list.addEventListener("drag-reorder-change", function () {
      var rows = list.querySelectorAll("[data-reorder-key]");
      rows.forEach(function (row, idx) {
        var posInput = row.querySelector("[data-card-position]");
        if (posInput) posInput.value = idx;
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window, document);
