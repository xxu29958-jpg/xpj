/* Encode only the one-time value already visible in this page; no network or storage. */
(function () {
    "use strict";
    document.addEventListener("DOMContentLoaded", function () {
        document.querySelectorAll("[data-qr-output]").forEach(function (output) {
            var source = document.querySelector(output.dataset.qrSource);
            if (!source) return;
            var value = (source.value || source.textContent || "").trim();
            if (!value) return;
            try {
                if (output.dataset.qrOrigin) {
                    if (!/^[0-9]{8}$/.test(value)) throw new Error("invalid_pairing_code");
                    var url = new URL("/web/auth/login", output.dataset.qrOrigin);
                    if (url.protocol !== "https:") throw new Error("invalid_origin");
                    url.hash = "pairing=" + value;
                    value = url.href;
                }
                var qr = window.qrcode(0, "M");
                qr.addData(value);
                qr.make();
                output.innerHTML = qr.createSvgTag({ cellSize: 4, margin: 16, title: output.dataset.qrLabel });
            } catch (_) {
                output.textContent = "二维码暂时无法显示，请使用上方的链接或连接码。";
            }
            output.hidden = false;
        });
    });
})();
