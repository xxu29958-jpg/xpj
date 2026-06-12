/* /owner Console · 上传链接交接(一键复制 + 本地二维码)
 *
 * 用法(upload_links.html 的 new_secret 一次性展示卡):
 *   <div class="secret-box" data-upload-handoff-url>…完整 URL…</div>
 *   <button type="button" data-copy-upload-url>复制完整 URL</button>
 *   <div data-upload-qr-section hidden> <div data-upload-qr></div> … </div>
 *
 * 约束:
 *   - 完整 URL 在 HTML 里只允许出现一次(test_owner_upload_links_create_reveals_once
 *     钉死),所以本脚本只从 [data-upload-handoff-url] 的文本读取,绝不把 URL 复制进
 *     第二个属性/节点;二维码由 vendored qrcode.js(/static/owner/vendor/,MIT)在
 *     客户端本地编码,零网络、零后端参与。
 *   - 复制走 navigator.clipboard(loopback http://127.0.0.1 属 secure context),
 *     失败降级 document.execCommand("copy");二维码渲染失败不破坏页面,复制按钮仍可用。
 */
(function () {
    "use strict";

    function fallbackCopy(text) {
        var ta = document.createElement("textarea");
        ta.value = text;
        ta.setAttribute("readonly", "");
        ta.style.position = "fixed";
        ta.style.left = "-9999px";
        document.body.appendChild(ta);
        ta.select();
        var ok = false;
        try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
        document.body.removeChild(ta);
        return ok;
    }

    function bindCopy(url) {
        var btn = document.querySelector("[data-copy-upload-url]");
        if (!btn) return;
        var idleLabel = btn.textContent;
        btn.addEventListener("click", function () {
            function settle(ok) {
                if (ok) {
                    btn.textContent = "已复制";
                    // 复用面语境化：按钮可带 data-copy-toast 覆盖确认句
                    // （成员页邀请明文复用本脚本，默认句的 iPhone 语境不通）。
                    var okToast = btn.getAttribute("data-copy-toast")
                        || "完整 URL 已复制，去 iPhone 快捷指令里粘贴";
                    if (window.OwnerToast) window.OwnerToast.success(okToast);
                    setTimeout(function () { btn.textContent = idleLabel; }, 2000);
                } else if (window.OwnerToast) {
                    window.OwnerToast.danger(
                        btn.getAttribute("data-copy-fail-toast")
                            || "复制失败，请手动全选上面的 URL 复制"
                    );
                }
            }
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(url).then(
                    function () { settle(true); },
                    function () { settle(fallbackCopy(url)); }
                );
            } else {
                settle(fallbackCopy(url));
            }
        });
    }

    function renderQr(url) {
        var section = document.querySelector("[data-upload-qr-section]");
        var box = document.querySelector("[data-upload-qr]");
        if (!section || !box || typeof window.qrcode !== "function") return;
        try {
            var qr = window.qrcode(0, "M");
            qr.addData(url);
            qr.make();
            box.innerHTML = qr.createSvgTag({ cellSize: 4, title: "上传链接二维码" });
            section.hidden = false;
        } catch (e) {
            /* 渲染失败保持 section 隐藏即可 */
        }
    }

    document.addEventListener("DOMContentLoaded", function () {
        var source = document.querySelector("[data-upload-handoff-url]");
        if (!source) return;
        var url = (source.textContent || "").trim();
        if (!url) return;
        bindCopy(url);
        renderQr(url);
    });
})();
