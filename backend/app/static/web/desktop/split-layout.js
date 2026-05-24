/* Drawer/body split-layout state sync. */
(function (window, document) {
  "use strict";

  const app = window.TicketboxWeb = window.TicketboxWeb || {};

  app.initSplitLayout = function initSplitLayout() {
    const drawer = document.getElementById("drawer");
    if (!drawer) return;
    const sync = function () {
      if (drawer.classList.contains("on")) {
        document.body.setAttribute("data-drawer-open", "true");
      } else {
        document.body.removeAttribute("data-drawer-open");
      }
    };
    const mo = new MutationObserver(sync);
    mo.observe(drawer, { attributes: true, attributeFilter: ["class"] });
    sync();
  };
})(window, document);
