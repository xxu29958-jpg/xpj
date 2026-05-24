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
  };
})(window, document);
