(function () {
    "use strict";
    function readPairing() {
        var code = new URLSearchParams(window.location.hash.slice(1)).get("pairing");
        if (code === null) return;
        window.history.replaceState(null, "", window.location.pathname + window.location.search);
        var input = document.querySelector("[name=pairing_code]");
        var hint = document.querySelector("[data-pairing-scan-hint]");
        if (input && /^[0-9]{8}$/.test(code)) {
            input.value = code;
            if (hint) hint.textContent = "连接码已从二维码填好。确认这是你自己的设备后，点击连接。";
        } else if (hint) {
            hint.textContent = "二维码中的连接码不完整，请重新扫码或手动输入。";
        }
    }
    window.addEventListener("hashchange", readPairing);
    readPairing();

    var form = document.querySelector("form[action='/web/auth/login']");
    var errorBox = document.querySelector("[data-pairing-error]");
    if (!form || !errorBox) return;
    var submitting = false;
    form.addEventListener("submit", async function (event) {
        event.preventDefault();
        if (submitting) return;
        submitting = true;
        var body = new FormData(form);
        var controls = Array.from(form.elements).map(function (control) {
            return [control, control.disabled];
        });
        controls.forEach(function (item) { item[0].disabled = true; });
        errorBox.hidden = true;
        var navigating = false;
        try {
            // Keep the existing POST, cookie attempt and server redirect contract.
            // Failed input stays only in this document; credentials are not persisted.
            var response = await fetch(form.action, {method: "POST", body: body, credentials: "same-origin"});
            var target = new URL(response.url);
            if (response.ok && target.origin === location.origin && target.pathname !== "/web/auth/login") {
                navigating = true;
                location.assign(target.href);
                return;
            }
            var rejected = new DOMParser().parseFromString(await response.text(), "text/html");
            var message = rejected.querySelector("[data-pairing-error]");
            errorBox.textContent = message && message.textContent.trim() || "连接未完成。输入已保留，请重试。";
        } catch (_) {
            errorBox.textContent = "暂时无法确认连接结果。输入已保留，请恢复连接后重试。";
        } finally {
            if (!navigating) {
                controls.forEach(function (item) { item[0].disabled = item[1]; });
                submitting = false;
                errorBox.hidden = false;
                errorBox.scrollIntoView({block: "nearest"});
            }
        }
    });
})();
