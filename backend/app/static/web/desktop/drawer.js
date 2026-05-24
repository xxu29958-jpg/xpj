/* Pending expense edit drawer. */
(function (window, document) {
  "use strict";

  const app = window.TicketboxWeb = window.TicketboxWeb || {};

  app.initDrawer = function initDrawer() {
    const drawer = document.getElementById("drawer");
    const scrim = document.getElementById("drawer-scrim");
    if (!drawer || !scrim) return;

    function close() {
      drawer.classList.remove("on");
      scrim.classList.remove("on");
      drawer.innerHTML = "";
    }
    scrim.addEventListener("click", close);
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && drawer.classList.contains("on")) close();
    });

    document.querySelectorAll(".exp-row[data-fragment-url]").forEach(function (row) {
      row.addEventListener("click", function (e) {
        // 点 checkbox / 表单元素时不打开抽屉
        const tag = (e.target.tagName || "").toLowerCase();
        if (tag === "input" || tag === "button") return;
        if (e.target.closest && e.target.closest("[data-stop=true]")) return;
        e.preventDefault();
        const url = row.getAttribute("data-fragment-url");
        fetch(url, { credentials: "same-origin", headers: { "Accept": "text/html" } })
          .then(function (res) { return res.text(); })
          .then(function (html) {
            drawer.innerHTML = html;
            drawer.classList.add("on");
            scrim.classList.add("on");
            if (typeof app.initReceiptSkeletons === "function") app.initReceiptSkeletons(drawer);
            drawer.querySelectorAll("[data-drawer-close]").forEach(function (b) {
              b.addEventListener("click", close);
            });
          })
          .catch(function () {
            // fallback：fetch 失败时按链接正常跳转
            window.location.href = row.getAttribute("href");
          });
      });
    });
  };
})(window, document);
