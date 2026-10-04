/* 月度预算的可选设置与「再加一行」渐进增强。
 *
 * 边界: 只展开可选设置与克隆添加行, 不校验、不 normalize、不预测保存结果。
 * 分类名规范化/存在性/重复判定永远归服务端 Budget Owner。无 JS 时全部字段
 * 与两个真实添加行仍能通过原生 details 访问；「再加一行」仅在增强完成后显示。
 */
(function (window, document) {
  "use strict";

  function initBudgetForm() {
    const editor = document.querySelector("#budget-editor");
    const form = document.querySelector(".budget-form");
    if (form) {
      const options = [...form.querySelectorAll("[data-budget-options]")];
      // invalid 不冒泡；同步显露后由浏览器继续聚焦原生非法字段。
      // 不读取金额、不复制约束，也不把折叠状态变成第二份表单数据。
      form.addEventListener("invalid", function (event) {
        const zone = event.target.closest("[data-budget-add-zone]");
        if (zone) zone.hidden = false;
      }, true);
      options.forEach(function (item) {
        const summary = item.querySelector("summary");
        if (!summary) return;
        item.open = item.getAttribute("data-start-expanded") !== "false";
        summary.hidden = false;
      });
    }

    if (editor) {
      editor.addEventListener("toggle", function () {
        if (editor.open) editor.scrollIntoView({block: "start"});
      });
      const requested = new URL(window.location.href);
      if (requested.hash === "#budget-editor" || requested.searchParams.has("new_budget")) editor.open = true;
    }

    const zone = document.querySelector("[data-budget-add-zone]");
    if (!zone) return;
    const rows = zone.querySelector(".budget-add-rows");
    const more = zone.querySelector("[data-budget-add-more]");
    const prototype = rows && rows.querySelector("[data-budget-add-row]");
    if (!rows || !more || !prototype) return;

    const start = document.querySelector("[data-budget-add-start]");
    if (start) {
      start.addEventListener("click", function () {
        zone.hidden = false;
        const first = [...rows.querySelectorAll("input")].find(input => !input.value);
        if (first) first.focus();
      });
      zone.hidden = ![...rows.querySelectorAll("input")].some(input => input.value);
      start.hidden = false;
    }

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
