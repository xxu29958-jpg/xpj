/* 待确认 review queue 的键盘行为（progressive enhancement，批10 后继）。
 *
 *   ↑ / ↓ / Home / End   焦点位于行链接时，在可见行间移动真实焦点
 *                        （不循环；边界 no-op）
 *   Ctrl/⌘+Enter         drawer 打开时确认当前行（= 确认并下一笔）
 *
 * 焦点合同（K3 裁决，取代旧 J/K + 伪选择模型）：
 *   - 只有 document.activeElement 是可用的 .exp-row-detail 行链接时才接管
 *     方向键 —— 此时方向键的意图无歧义，preventDefault 抑滚动是行导航；
 *     列表外、checkbox、按钮、输入框上的按键全部走浏览器原生
 *     （页面滚动 / 控件激活 / Space 勾选）。
 *   - 移动的是真实焦点：Enter 打开行走链接原生语义，读屏随焦点播报，
 *     高亮交给 CSS :focus-within，不再有第二套“选中”状态。
 *   - 所有自定义键先过 isComposing（中文输入法组合中一律不接管）。
 *   - aria-disabled 的行不参与方向导航（防御守卫）。
 *   - 无任何裸字母键：本文件不认识 J/K。
 */
(function (window, document) {
  "use strict";

  const app = window.TicketboxWeb = window.TicketboxWeb || {};

  app.initReviewKeyboard = function initReviewKeyboard() {
    const table = document.getElementById("exp-table");
    if (!table) return;

    const ROW_SELECTOR = ".exp-row-detail[data-fragment-url]";
    const NAV_KEYS = ["ArrowDown", "ArrowUp", "Home", "End"];

    function rows() {
      // Only rows still in the table, visible, and available.
      return Array.prototype.filter.call(
        table.querySelectorAll(ROW_SELECTOR),
        function (r) { return r.offsetParent !== null && r.getAttribute("aria-disabled") !== "true"; }
      );
    }

    function moveFrom(current, key) {
      const list = rows();
      const idx = list.indexOf(current);
      if (idx === -1) return;
      let target = null;
      if (key === "ArrowDown" && idx < list.length - 1) target = list[idx + 1];
      else if (key === "ArrowUp" && idx > 0) target = list[idx - 1];
      else if (key === "Home") target = list[0];
      else if (key === "End") target = list[list.length - 1];
      // 边界 no-op：不循环；focus() 自带 scrollIntoView 语义。
      if (!target || target === current) return;
      target.focus();
    }

    document.addEventListener("keydown", function (e) {
      // 中文输入法组合中不接管任何自定义键。
      if (e.isComposing) return;
      // Ctrl/⌘+Enter confirms from anywhere in the open drawer (including an
      // edited field — the only deliberately global chord).
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        if (app.drawerApi && app.drawerApi.isOpen() && app.drawerApi.submitConfirm()) {
          e.preventDefault();
        }
        return;
      }
      if (e.altKey || e.ctrlKey || e.metaKey) return;
      // While the drawer is open, leave plain keys to the form (Esc closes it,
      // handled in drawer.js).
      if (app.drawerApi && app.drawerApi.isOpen()) return;
      if (NAV_KEYS.indexOf(e.key) === -1) return;
      // 精确作用域：真实焦点必须在可用的行链接上。
      const active = document.activeElement;
      if (!active || !active.matches || !active.matches(ROW_SELECTOR)) return;
      if (active.getAttribute("aria-disabled") === "true") return;
      e.preventDefault();
      moveFrom(active, e.key);
    });
  };
})(window, document);
