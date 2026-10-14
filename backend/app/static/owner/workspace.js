/* Reveal invalid fields before native form validation tries to focus them. */
(function () {
    "use strict";
    function revealSection() {
        var section = document.getElementById(window.location.hash.slice(1));
        if (!section) return;
        if (section.matches(".workspace-disclosure")) section.open = true;
        var target = section.querySelector("summary") || section;
        target.focus({ preventScroll: true });
        section.scrollIntoView({ block: "start" });
    }
    revealSection();
    window.addEventListener("hashchange", revealSection);
    document.addEventListener("invalid", function (event) {
        if (!event.target.closest(".workspace-form")) return;
        var details = event.target.closest("details");
        while (details) {
            details.open = true;
            details = details.parentElement.closest("details");
        }
    }, true);

    var recognition = document.querySelector("[data-recognition-setup]");
    if (recognition) {
        function showRecognitionFields() {
            var usesModel = ["ocr_provider", "ocr_fallback_provider", "debt_bill_provider"].some(function (name) {
                return recognition.elements[name].value === "local_llm";
            });
            document.getElementById("recognition-model").hidden = !usesModel;
            document.getElementById("ocr_auto_run").closest("label").hidden = recognition.elements.ocr_provider.value === "empty";
            var save = document.getElementById("recognition-save");
            save.value = usesModel ? "test_save" : "save";
            save.querySelector("span").textContent = usesModel ? "测试并保存识别设置" : "保存识别设置";
        }
        recognition.addEventListener("change", showRecognitionFields);
        showRecognitionFields();
    }

    var advisor = document.querySelector("[data-advisor-setup]");
    if (advisor) {
        function showAdvisorFields() {
            var off = advisor.elements.provider.value === "empty";
            var connection = document.getElementById("advisor-connection");
            connection.hidden = off;
            connection.querySelectorAll("input, button").forEach(function (field) { field.disabled = off; });
            document.getElementById("advisor-save-label").textContent = off ? "保存关闭设置" : "保存连接，下一步";
        }
        advisor.elements.provider.addEventListener("change", showAdvisorFields);
        showAdvisorFields();
        advisor.addEventListener("input", function () {
            var savedStep = document.querySelector("[data-advisor-saved-step]");
            if (!savedStep) return;
            savedStep.querySelector("[data-connection-dirty]").hidden = false;
            savedStep.querySelectorAll("button").forEach(function (button) { button.disabled = true; });
        });
        advisor.addEventListener("submit", async function (event) {
            var button = event.submitter;
            if (!button || !button.matches("[data-read-advisor-models]")) return;
            event.preventDefault();
            var draft = new FormData(advisor);
            draft.set("advisor_action", "models");
            var result = document.getElementById("advisor-model-result");
            result.textContent = "正在读取模型…";
            button.disabled = true;
            try {
                var response = await fetch(advisor.action, {method: "POST", body: draft, headers: {Accept: "application/json"}});
                var payload = await response.json();
                if (["base_url", "api_key", "clear_key"].some(function (name) {
                    return draft.get(name) !== new FormData(advisor).get(name);
                })) {
                    result.textContent = "连接内容已修改，请重新读取模型。";
                    return;
                }
                result.textContent = response.ok ? payload.message : payload.error;
                if (response.ok) {
                    var options = document.getElementById("advisor-model-options");
                    options.replaceChildren();
                    payload.models.forEach(function (name) {
                        var option = document.createElement("option");
                        option.value = name;
                        options.appendChild(option);
                    });
                    if (!advisor.elements.model.value && payload.models.length === 1) advisor.elements.model.value = payload.models[0];
                    advisor.elements.model.focus();
                }
            } catch (_) {
                result.textContent = "未能读取模型。输入仍保留，请重试或直接填写模型名称。";
            } finally {
                button.disabled = advisor.elements.provider.value === "empty";
            }
        });
        var step = document.querySelector("[data-advisor-step]").dataset.advisorStep;
        var next = step && (document.querySelector("[role='alert']") || document.getElementById("advisor-" + step));
        if (next) {
            next.tabIndex = -1;
            next.focus({preventScroll: true});
            next.scrollIntoView({block: "start"});
        }
    }

    var maintenance = document.querySelector("[data-maintenance-setup]");
    if (maintenance) {
        function showCleanupConfirmation() {
            var changed = Array.from(maintenance.querySelectorAll("[data-saved-enabled]")).some(function (field) {
                return field.checked && field.dataset.savedEnabled !== "true";
            }) || Array.from(maintenance.querySelectorAll("[data-saved-retention]")).some(function (field) {
                return field.value !== "" && Number(field.value) < Number(field.dataset.savedRetention);
            });
            maintenance.querySelector(".workspace-maintenance-confirm").hidden = !changed;
        }
        maintenance.addEventListener("input", showCleanupConfirmation);
        showCleanupConfirmation();
    }
})();
