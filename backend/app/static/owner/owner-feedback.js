/* /owner Console · 长任务 loading + toast 反馈 (v0.10.1)
 *
 * 用法:
 *   1. 表单提交触发 loading:
 *        <form ... data-show-loading="正在备份…">
 *   2. 程序触发:
 *        window.OwnerLoading.show("处理中…");
 *        window.OwnerLoading.hide();
 *   3. Toast 提示:
 *        window.OwnerToast.success("备份完成");
 *        window.OwnerToast.warn("队列已满");
 *        window.OwnerToast.danger("操作失败");
 *
 * 自动:页面加载时如果 URL 含 ?notice=xxx 或 ?error=xxx,会自动展示对应 toast。
 */
(function () {
    "use strict";

    var overlayEl = null;
    var trayEl = null;

    function ensureOverlay() {
        if (overlayEl) return overlayEl;
        overlayEl = document.createElement("div");
        overlayEl.className = "loading-overlay";
        overlayEl.setAttribute("role", "status");
        overlayEl.setAttribute("aria-live", "polite");
        overlayEl.innerHTML =
            '<div class="loading-card">' +
            '<div class="spinner" aria-hidden="true"></div>' +
            '<div class="label"></div>' +
            "</div>";
        document.body.appendChild(overlayEl);
        return overlayEl;
    }

    function ensureTray() {
        if (trayEl) return trayEl;
        trayEl = document.createElement("div");
        trayEl.className = "toast-tray";
        document.body.appendChild(trayEl);
        return trayEl;
    }

    function pushToast(kind, message, durationMs) {
        var tray = ensureTray();
        var t = document.createElement("div");
        t.className = "toast";
        if (kind === "success") t.classList.add("is-success");
        else if (kind === "warn") t.classList.add("is-warn");
        else if (kind === "danger") t.classList.add("is-danger");
        t.textContent = message;
        tray.appendChild(t);
        var ttl = durationMs || 3200;
        setTimeout(function () {
            t.style.transition = "opacity .2s ease, transform .2s ease";
            t.style.opacity = "0";
            t.style.transform = "translateY(-6px)";
            setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, 220);
        }, ttl);
    }

    window.OwnerLoading = {
        show: function (label) {
            var o = ensureOverlay();
            o.querySelector(".label").textContent = label || "处理中…";
            o.classList.add("is-active");
        },
        hide: function () {
            if (overlayEl) overlayEl.classList.remove("is-active");
        },
    };

    window.OwnerToast = {
        info:    function (msg) { pushToast("info", msg); },
        success: function (msg) { pushToast("success", msg); },
        warn:    function (msg) { pushToast("warn", msg); },
        danger:  function (msg) { pushToast("danger", msg); },
    };

    /* 自动:绑定带 data-show-loading 的表单 */
    document.addEventListener("submit", function (ev) {
        var form = ev.target;
        if (form && form.dataset && form.dataset.showLoading) {
            window.OwnerLoading.show(form.dataset.showLoading);
        }
    });

    /* 自动:URL 含 notice / error 参数时弹 toast(适合 POST → 302 回跳场景) */
    document.addEventListener("DOMContentLoaded", function () {
        try {
            var params = new URLSearchParams(window.location.search);
            var notice = params.get("notice");
            var error  = params.get("error");
            if (notice) window.OwnerToast.success(decodeURIComponent(notice));
            if (error)  window.OwnerToast.danger(decodeURIComponent(error));
        } catch (e) { /* ignore */ }
    });
})();
