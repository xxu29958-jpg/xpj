/* confirm-modal.js · 共享于 /web 与 /owner
 *
 * 把 `onsubmit="return confirm('...')"` / `onclick="return confirm('...')"`
 * 这种浏览器原生弹窗，替换为风格化的 <dialog> 模态框：
 *
 *   <form ... data-confirm="确认要删除？">...</form>
 *   <button data-confirm="确认要应用？" ...>应用</button>
 *
 * 设计目标：
 *   - 零依赖、不污染全局命名空间
 *   - 不破坏原生 <button name=action value=...> 表单语义
 *   - 浏览器若不支持 <dialog> 自动回退到 window.confirm()
 */
(function () {
    "use strict";

    function ensureModal() {
        var dlg = document.getElementById("tb-confirm-modal");
        if (dlg) return dlg;
        dlg = document.createElement("dialog");
        dlg.id = "tb-confirm-modal";
        dlg.className = "tb-confirm-modal";
        dlg.innerHTML = ''
            + '<form method="dialog" class="tb-confirm-body">'
            + '  <p class="tb-confirm-message"></p>'
            + '  <div class="tb-confirm-actions">'
            + '    <button type="button" class="tb-confirm-cancel" value="cancel">取消</button>'
            + '    <button type="submit" class="tb-confirm-ok" value="ok">确认</button>'
            + '  </div>'
            + '</form>';
        document.body.appendChild(dlg);
        dlg.querySelector(".tb-confirm-cancel").addEventListener("click", function () {
            dlg.returnValue = "cancel";
            dlg.close();
        });
        return dlg;
    }

    function ask(message) {
        return new Promise(function (resolve) {
            var dlg = ensureModal();
            dlg.querySelector(".tb-confirm-message").textContent = message || "确认要执行此操作？";
            if (typeof dlg.showModal !== "function") {
                resolve(window.confirm(message));
                return;
            }
            var done = function () {
                dlg.removeEventListener("close", done);
                resolve(dlg.returnValue === "ok");
            };
            dlg.addEventListener("close", done);
            dlg.returnValue = "cancel";
            dlg.showModal();
            var okBtn = dlg.querySelector(".tb-confirm-ok");
            if (okBtn) okBtn.focus();
        });
    }

    document.addEventListener("submit", function (e) {
        var form = e.target && e.target.closest && e.target.closest("form[data-confirm]");
        if (!form) return;
        if (form.dataset._tbConfirmed === "1") return;
        e.preventDefault();
        ask(form.dataset.confirm).then(function (ok) {
            if (!ok) return;
            form.dataset._tbConfirmed = "1";
            // 复制原生 submit() 行为；不会重新触发 'submit' 事件
            HTMLFormElement.prototype.submit.call(form);
        });
    }, true);

    document.addEventListener("click", function (e) {
        var target = e.target;
        if (!target || !target.closest) return;
        var btn = target.closest("button[data-confirm], a[data-confirm]");
        if (!btn) return;
        if (btn.dataset._tbConfirmed === "1") return;
        e.preventDefault();
        e.stopPropagation();
        ask(btn.dataset.confirm).then(function (ok) {
            if (!ok) return;
            btn.dataset._tbConfirmed = "1";
            if (btn.tagName === "A") {
                window.location.assign(btn.href);
                return;
            }
            // 重新派发 click，复用原生 button[type=submit] 的 name/value 提交语义
            btn.click();
        });
    }, true);
})();
