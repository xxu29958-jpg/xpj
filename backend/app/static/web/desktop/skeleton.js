/* Generic skeleton marker binding. */
(function (window, document) {
  "use strict";

  const app = window.TicketboxWeb = window.TicketboxWeb || {};

  app.initSkeleton = function initSkeleton() {
    document.querySelectorAll("[data-skeleton]:not(.skeleton)").forEach(function (el) {
      el.classList.add("skeleton");
    });
  };
})(window, document);
