/* 月度预算的可选设置与「再加一行」渐进增强。
 *
 * 边界: 只展开可选设置与克隆添加行, 不校验、不 normalize、不预测保存结果。
 * 分类名规范化/存在性/重复判定永远归服务端 Budget Owner。无 JS 时全部字段
 * 和两个真实添加行保持可见, 折叠入口及「再加一行」按钮保持 hidden。
 */
(function (window, document) {
  "use strict";

  function initBudgetForm() {
    const options = document.querySelector("#budget-options");
    const summary = options && options.querySelector("summary");
    const form = options && options.closest("form");
    if (options && summary && form) {
      // invalid 不冒泡；同步显露后由浏览器继续聚焦原生非法字段。
      // 不读取金额、不复制约束，也不把折叠状态变成第二份表单数据。
      form.addEventListener("invalid", function (event) {
        if (options.contains(event.target)) options.open = true;
      }, true);
      options.open = options.getAttribute("data-start-expanded") !== "false";
      summary.hidden = false;
    }

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
    document.addEventListener("DOMContentLoaded", initBudgetForm);
  } else {
    initBudgetForm();
  }
})(window, document);
