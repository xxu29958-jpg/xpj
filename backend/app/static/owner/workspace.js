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

    var keyAction = document.getElementById("advisor_key_action");
    var keyField = document.getElementById("advisor-new-key");
    if (keyAction && keyField) {
        function updateKeyField() {
            keyField.hidden = keyAction.value !== "replace";
            keyField.querySelector("input").disabled = keyField.hidden;
        }
        keyAction.addEventListener("change", updateKeyField);
        updateKeyField();
    }
})();
