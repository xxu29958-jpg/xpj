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
})();
