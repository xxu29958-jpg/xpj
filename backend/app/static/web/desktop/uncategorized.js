/* Native category snapshots remain the command; enhance only selection feedback. */
(function (window, document) {
  "use strict";

  function init() {
    var all = document.getElementById("select-all");
    if (!all) return;
    var form = all.closest("form");
    var boxes = Array.from(form.querySelectorAll('input[name="expense_snapshot"]'));
    var button = form.querySelector("[data-category-apply]");
    all.closest("label").hidden = false;
    function refresh() {
      var count = boxes.filter(function (box) { return box.checked; }).length;
      all.checked = count === boxes.length;
      all.indeterminate = count > 0 && count < boxes.length;
      button.textContent = count ? "应用到 " + count + " 笔" : "先选择账单";
      button.disabled = count === 0;
    }
    all.addEventListener("change", function () {
      boxes.forEach(function (box) {
        if (!box.disabled) box.checked = all.checked;
      });
      refresh();
    });
    boxes.forEach(function (box) { box.addEventListener("change", refresh); });
    window.addEventListener("pageshow", refresh);
    refresh();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window, document);
