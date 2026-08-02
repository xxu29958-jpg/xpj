/* Receipt image skeleton state. */
(function (window, document) {
  "use strict";

  const app = window.TicketboxWeb = window.TicketboxWeb || {};

  app.initReceiptSkeletons = function initReceiptSkeletons(root) {
    (root || document).querySelectorAll("[data-image-skeleton]").forEach(function (box) {
      if (box.getAttribute("data-skeleton-bound") === "1") return;
      box.setAttribute("data-skeleton-bound", "1");
      const img = box.querySelector("img");
      if (!img) {
        box.classList.add("is-loaded");
        return;
      }
      const done = function () { box.classList.add("is-loaded"); };
      if (img.complete) {
        done();
        return;
      }
      img.addEventListener("load", done, { once: true });
      img.addEventListener("error", done, { once: true });
    });

    // 218-D S4 (移植自产品矿): 收件行缩略图加载态 — 成功后隐去占位 label,
    // 失败时藏 img 并明示「加载失败」(无图/已清理态由模板直接渲染, 不走这里)。
    (root || document).querySelectorAll("[data-receipt-thumb]").forEach(function (box) {
      if (box.getAttribute("data-thumb-bound") === "1") return;
      box.setAttribute("data-thumb-bound", "1");
      const img = box.querySelector("img");
      const label = box.querySelector("[data-receipt-thumb-label]");
      if (!img) return;
      const loaded = function () {
        box.classList.add("is-loaded");
        if (label) label.textContent = "小票预览";
      };
      const failed = function () {
        box.classList.add("is-failed");
        img.hidden = true;
        if (label) label.textContent = "加载失败";
      };
      if (img.complete) {
        if (img.naturalWidth > 0) loaded();
        else failed();
        return;
      }
      img.addEventListener("load", loaded, { once: true });
      img.addEventListener("error", failed, { once: true });
    });
  };
})(window, document);
