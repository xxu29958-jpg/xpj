/* 月度预算「再加一行」渐进增强 (C1).
 *
 * 边界: 只做纯 DOM 克隆 —— 不校验、不 normalize、不预测保存结果; 分类名
 * 规范化/存在性/重复判定永远归服务端 Budget Owner。无 JS 时模板自带的两个
 * 真实添加行完整可提交, 「再加一行」按钮保持 hidden, 不做可见但无用的控件。
 */
(function (window, document) {
  "use strict";

  function initBudgetAddRow() {
    const zone = document.querySelector("[data-budget-add-zone]");
    if (!zone) return;
    const rows = zone.querySelector(".budget-add-rows");
    const more = zone.querySelector("[data-budget-add-more]");
    const prototype = rows && rows.querySelector("[data-budget-add-row]");
    if (!rows || !more || !prototype) return;

    more.addEventListener("click", function () {
      const clone = prototype.cloneNode(true);
      clone.querySelectorAll("input").forEach(function (input) {
        input.value = "";
      });
      rows.appendChild(clone);
      const first = clone.querySelector("input");
      if (first) first.focus();
    });

    // 监听器挂接完成后才让按钮现身; 任何更早的失败都保持隐藏 (与 check-all
    // 同一 settlement 模式)。
    more.hidden = false;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initBudgetAddRow);
  } else {
    initBudgetAddRow();
  }
})(window, document);
