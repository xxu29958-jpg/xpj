/* Reveal invalid fields before native form validation tries to focus them. */
(function () {
    "use strict";
    document.addEventListener("invalid", function (event) {
        if (!event.target.closest(".workspace-form")) return;
        var details = event.target.closest("details");
        while (details) {
            details.open = true;
            details = details.parentElement.closest("details");
        }
    }, true);
})();
