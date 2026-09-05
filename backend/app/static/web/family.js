(function () {
    "use strict";

    function fallbackCopy(source) {
        source.focus();
        source.select();
        source.setSelectionRange(0, source.value.length);
        try {
            return document.execCommand("copy");
        } catch (_) {
            return false;
        }
    }

    function bindInvitationCopy() {
        var source = document.querySelector("[data-family-invite-value]");
        var button = document.querySelector("[data-family-copy-button]");
        var status = document.querySelector("[data-family-copy-status]");
        if (!source || !button || !status) return;

        button.addEventListener("click", function () {
            function settle(copied) {
                button.textContent = copied ? "已复制" : "请手动复制";
                status.textContent = copied
                    ? "邀请已复制，可以私下发给家人。"
                    : "复制失败，已选中邀请，请手动复制。";
                if (!copied) fallbackCopy(source);
            }

            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(source.value).then(
                    function () { settle(true); },
                    function () { settle(fallbackCopy(source)); }
                );
            } else {
                settle(fallbackCopy(source));
            }
        });
    }

    document.addEventListener("DOMContentLoaded", bindInvitationCopy);
})();
