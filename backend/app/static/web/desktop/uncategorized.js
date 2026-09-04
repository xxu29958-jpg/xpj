/* 未分类核对页: 表头「全选」联动本页所有 expense_ids 勾选框。
   原 uncategorized.html 内联 <script> 在 CSP script-src 'self' 下从不执行 ——
   全选对开启 JS 的用户也一直失效; 此外部脚本是同一行为的合规载体。
   无 JS 时逐勾提交仍完全可用 (noJS fallback); 只读角色的禁用勾选框不受联动。 */
(function (window, document) {
  "use strict";

  function init() {
    var all = document.getElementById("select-all");
    if (!all) return;
    all.addEventListener("change", function () {
      var boxes = document.querySelectorAll('input[name="expense_ids"]');
      boxes.forEach(function (box) {
        if (!box.disabled) box.checked = all.checked;
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window, document);
