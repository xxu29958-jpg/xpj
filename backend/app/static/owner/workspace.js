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

    function localSelection(picker) {
        var form = picker.closest("form");
        var model = form.elements[picker.dataset.modelField].value;
        var base = form.elements[picker.dataset.baseField].value;
        picker.querySelector("[data-model-selection]").textContent = model ? "当前选择：" + model + " · " + base : "尚未选择模型。";
        if (form.elements.clear_key && form.elements.clear_key.checked) {
            picker.querySelector("[data-model-selection]").textContent += " 原 Key 不会用于所选服务，保存后清除。";
        }
    }
    async function scanLocalModels(picker) {
        var form = picker.closest("form");
        var button = picker.querySelector("[data-scan-models]");
        var status = picker.querySelector("[data-scan-status]");
        var select = picker.querySelector("[data-discovered-model]");
        if (button.disabled) return;
        picker.dataset.scanned = "true";
        button.disabled = true;
        select.disabled = true;
        status.textContent = "正在查找本机模型服务…";
        try {
            var response = await fetch("/owner/local-models?" + new URLSearchParams({current_url: form.elements[picker.dataset.baseField].value}));
            if (!response.ok) throw new Error("discovery failed");
            var payload = await response.json();
            select.replaceChildren(new Option("请选择模型", ""));
            payload.services.forEach(function (service) {
                var group = document.createElement("optgroup");
                group.label = service.base_url;
                service.models.forEach(function (model) {
                    var option = new Option(model, model);
                    option.dataset.baseUrl = service.base_url;
                    option.selected = model === form.elements[picker.dataset.modelField].value && service.base_url === form.elements[picker.dataset.baseField].value;
                    group.appendChild(option);
                });
                select.appendChild(group);
            });
            select.disabled = !payload.services.length;
            status.textContent = payload.services.length ? "已找到 " + (select.options.length - 1) + " 个模型，请选择要使用的模型。" : "未发现可用模型。请在 LM Studio 或 Ollama 中启动模型服务后重新扫描；使用其他端口时，可在下方填写地址再扫描。";
        } catch (_) {
            status.textContent = "扫描未完成，请重试。已填写的内容仍保留。";
        } finally {
            button.disabled = false;
            button.textContent = "重新扫描";
        }
    }
    document.querySelectorAll("[data-local-models]").forEach(function (picker) {
        var form = picker.closest("form");
        picker.querySelector("[data-scan-models]").addEventListener("click", function () { scanLocalModels(picker); });
        picker.querySelector("[data-discovered-model]").addEventListener("change", function (event) {
            var option = event.target.selectedOptions[0];
            if (!option.value) return;
            var base = form.elements[picker.dataset.baseField];
            if (base.value !== option.dataset.baseUrl && form.elements.api_key) {
                form.elements.api_key.value = "";
                if (form.elements.clear_key) form.elements.clear_key.checked = true;
            }
            base.value = option.dataset.baseUrl;
            form.elements[picker.dataset.modelField].value = option.value;
            base.dispatchEvent(new Event("input", {bubbles: true}));
        });
        form.addEventListener("input", function () { localSelection(picker); });
        localSelection(picker);
    });
    function discoverOnce(picker) {
        if (!picker.dataset.scanned) scanLocalModels(picker);
    }

    var recognition = document.querySelector("[data-recognition-setup]");
    if (recognition) {
        function showRecognitionFields() {
            var usesModel = ["ocr_provider", "ocr_fallback_provider", "debt_bill_provider"].some(function (name) {
                return recognition.elements[name].value === "local_llm";
            });
            document.getElementById("recognition-model").hidden = !usesModel;
            if (usesModel) discoverOnce(recognition.querySelector("[data-local-models]"));
            var automatic = document.getElementById("ocr_auto_run");
            automatic.disabled = recognition.elements.ocr_provider.value === "empty";
            automatic.closest("label").hidden = automatic.disabled;
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
            var mode = advisor.elements.connection_mode.value;
            var off = mode === "empty";
            var connection = document.getElementById("advisor-connection");
            connection.hidden = off;
            connection.querySelectorAll("input, button, select").forEach(function (field) { field.disabled = off; });
            var picker = connection.querySelector("[data-local-models]");
            picker.hidden = mode !== "local";
            connection.querySelector("[data-cloud-only]").hidden = mode !== "cloud";
            var manual = document.getElementById("advisor-manual-connection");
            manual.querySelector("summary").hidden = mode === "cloud";
            if (mode === "cloud") manual.open = true;
            if (mode === "local") discoverOnce(picker);
            document.getElementById("advisor-save-label").textContent = off ? "保存关闭设置" : "保存连接，下一步";
        }
        advisor.elements.connection_mode.addEventListener("change", function () {
            document.getElementById("advisor-manual-connection").open = advisor.elements.connection_mode.value === "cloud";
            showAdvisorFields();
        });
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
                if (["connection_mode", "base_url", "api_key", "clear_key"].some(function (name) {
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
                    if (!advisor.elements.model.value && payload.models.length === 1) {
                        advisor.elements.model.value = payload.models[0];
                        advisor.elements.model.dispatchEvent(new Event("input", {bubbles: true}));
                    }
                    advisor.elements.model.focus();
                }
            } catch (_) {
                result.textContent = "未能读取模型。输入仍保留，请重试或直接填写模型名称。";
            } finally {
                button.disabled = advisor.elements.connection_mode.value === "empty";
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
