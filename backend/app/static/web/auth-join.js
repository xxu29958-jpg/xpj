(function () {
    "use strict";

    var form = document.querySelector("[data-invitation-preview-form]");
    var input = document.querySelector("[data-invitation-input]");
    if (!form || !input || !window.location.hash) return;

    var token = new URLSearchParams(window.location.hash.slice(1)).get("invite");
    window.history.replaceState(null, "", "/web/auth/join");
    if (!token) return;

    input.value = token;
    form.requestSubmit();
})();
