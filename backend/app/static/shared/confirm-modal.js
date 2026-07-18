/* confirm-modal.js · 共享于 /web 与 /owner
 *
 * 把 `onsubmit="return confirm('...')"` / `onclick="return confirm('...')"`
 * 这种浏览器原生弹窗，替换为风格化的 <dialog> 模态框：
 *
 *   <form ... data-confirm="确认要删除？">...</form>
 *   <button data-confirm="确认要应用？" ...>应用</button>
 *   <form ... data-confirm="永久删除？" data-confirm-variant="danger">...</form>
 *
 * 设计目标：
 *   - 零依赖、不污染全局命名空间
 *   - 不破坏原生 <button name=action value=...> 表单语义
 *   - 仅危险动作使用 alertdialog + 安全焦点；普通确认仍是 dialog
 *   - 浏览器若不支持 <dialog> 自动回退到 window.confirm()
 */
(function () {
    "use strict";

    function normalizedText(value) {
        return String(value || "").replace(/\s+/g, " ").trim();
    }

    function dataValue(node, key) {
        if (!node || !node.dataset) return "";
        return normalizedText(node.dataset[key]);
    }

    function actionLabel(source, trigger) {
        var override = dataValue(trigger, "confirmAction") || dataValue(source, "confirmAction");
        if (override) return override;
        if (trigger && trigger.getAttribute) {
            var accessible = normalizedText(trigger.getAttribute("aria-label"));
            if (accessible) return accessible;
            var visible = normalizedText(trigger.textContent);
            if (visible) return visible;
            var value = normalizedText(trigger.getAttribute("value"));
            if (value) return value;
        }
        return "继续此操作";
    }

    function confirmationVariant(source, trigger) {
        var explicit = (
            dataValue(trigger, "confirmVariant")
            || dataValue(source, "confirmVariant")
        ).toLowerCase();
        if (explicit) {
            return explicit === "danger" || explicit === "critical" ? "danger" : "default";
        }
        if (!trigger || !trigger.classList) return "default";
        if (
            trigger.classList.contains("btn-danger")
            || trigger.classList.contains("product-button--danger")
            || (
                trigger.classList.contains("dt-btn")
                && trigger.classList.contains("danger")
            )
        ) {
            return "danger";
        }
        return "default";
    }

    function confirmationCopy(message, source, trigger) {
        var action = actionLabel(source, trigger);
        return {
            action: action,
            message: normalizedText(message) || "此操作需要再次确认。",
            variant: confirmationVariant(source, trigger),
            title: dataValue(trigger, "confirmTitle")
                || dataValue(source, "confirmTitle")
                || ("确认" + action)
        };
    }

    function ensureModal() {
        var dlg = document.getElementById("tb-confirm-modal");
        if (dlg) return dlg;
        dlg = document.createElement("dialog");
        dlg.id = "tb-confirm-modal";
        dlg.className = "tb-confirm-modal";
        dlg.setAttribute("aria-labelledby", "tb-confirm-title");
        dlg.setAttribute("aria-describedby", "tb-confirm-message");
        dlg.setAttribute("aria-modal", "true");
        dlg.innerHTML = ''
            + '<form method="dialog" class="tb-confirm-body">'
            + '  <h2 class="tb-confirm-title" id="tb-confirm-title"></h2>'
            + '  <p class="tb-confirm-message" id="tb-confirm-message"></p>'
            + '  <div class="tb-confirm-actions">'
            + '    <button type="button" class="tb-confirm-cancel" value="cancel">取消</button>'
            + '    <button type="submit" class="tb-confirm-ok" value="ok"></button>'
            + '  </div>'
            + '</form>';
        document.body.appendChild(dlg);
        dlg.querySelector(".tb-confirm-cancel").addEventListener("click", function () {
            dlg.returnValue = "cancel";
            dlg.close();
        });
        return dlg;
    }

    function restoreFocus(target) {
        if (!target || typeof target.focus !== "function") return;
        if (target.isConnected === false) return;
        target.focus();
    }

    function ask(message, source, trigger) {
        return new Promise(function (resolve) {
            var dlg = ensureModal();
            var copy = confirmationCopy(message, source, trigger);
            var restoreTarget = trigger && typeof trigger.focus === "function"
                ? trigger
                : document.activeElement;
            dlg.querySelector(".tb-confirm-title").textContent = copy.title;
            dlg.querySelector(".tb-confirm-message").textContent = copy.message;
            var okBtn = dlg.querySelector(".tb-confirm-ok");
            okBtn.textContent = copy.action;
            var isDanger = copy.variant === "danger";
            dlg.classList.toggle("is-danger", isDanger);
            if (isDanger) dlg.setAttribute("role", "alertdialog");
            else dlg.removeAttribute("role");
            if (typeof dlg.showModal !== "function") {
                var accepted = window.confirm(copy.message);
                restoreFocus(restoreTarget);
                resolve(accepted);
                return;
            }
            var done = function () {
                dlg.removeEventListener("close", done);
                restoreFocus(restoreTarget);
                resolve(dlg.returnValue === "ok");
            };
            dlg.addEventListener("close", done);
            dlg.returnValue = "cancel";
            dlg.showModal();
            var cancelBtn = dlg.querySelector(".tb-confirm-cancel");
            var initialFocus = isDanger ? cancelBtn : okBtn;
            if (initialFocus) initialFocus.focus();
        });
    }

    function isSubmitControl(control, form) {
        if (!control || control.form !== form || control.disabled) return false;
        var tag = normalizedText(control.tagName).toUpperCase();
        var type = normalizedText(control.type).toLowerCase();
        return (tag === "BUTTON" && (!type || type === "submit"))
            || (tag === "INPUT" && (type === "submit" || type === "image"));
    }

    function legacySubmitEvent(form, submitter) {
        var event;
        if (typeof SubmitEvent === "function") {
            event = new SubmitEvent("submit", {
                bubbles: true,
                cancelable: true,
                submitter: submitter || null
            });
        } else {
            event = new Event("submit", {bubbles: true, cancelable: true});
            try {
                Object.defineProperty(event, "submitter", {value: submitter || null});
            } catch (_err) {
                // Very old engines may not expose SubmitEvent.submitter.
            }
        }
        return form.dispatchEvent(event);
    }

    function applySubmitterOverrides(form, submitter) {
        var mappings = [
            ["formaction", "action"],
            ["formmethod", "method"],
            ["formenctype", "enctype"],
            ["formtarget", "target"]
        ];
        var originals = [];
        if (!submitter || !submitter.hasAttribute) return function () {};
        mappings.forEach(function (mapping) {
            if (!submitter.hasAttribute(mapping[0])) return;
            originals.push({
                name: mapping[1],
                present: form.hasAttribute(mapping[1]),
                value: form.getAttribute(mapping[1])
            });
            form.setAttribute(mapping[1], submitter.getAttribute(mapping[0]));
        });
        return function () {
            originals.forEach(function (original) {
                if (original.present) form.setAttribute(original.name, original.value);
                else form.removeAttribute(original.name);
            });
        };
    }

    function nativeSubmitWithSubmitter(form, submitter) {
        var skipsValidation = form.noValidate || (submitter && submitter.formNoValidate);
        if (
            !skipsValidation
            && typeof form.reportValidity === "function"
            && !form.reportValidity()
        ) {
            return;
        }
        var hiddenFields = [];
        if (submitter && submitter.name) {
            var names = [submitter.name];
            var values = [submitter.value];
            if (normalizedText(submitter.type).toLowerCase() === "image") {
                names = [submitter.name + ".x", submitter.name + ".y"];
                values = ["0", "0"];
            }
            names.forEach(function (name, index) {
                var hidden = document.createElement("input");
                hidden.type = "hidden";
                hidden.name = name;
                hidden.value = values[index];
                form.appendChild(hidden);
                hiddenFields.push(hidden);
            });
        }
        var restoreOverrides = function () {};
        try {
            // requestSubmit dispatches a cancelable submit event. Replaying that
            // event keeps CSRF and AJAX consumers alive in older engines too.
            if (!legacySubmitEvent(form, submitter)) return;
            restoreOverrides = applySubmitterOverrides(form, submitter);
            HTMLFormElement.prototype.submit.call(form);
        } finally {
            restoreOverrides();
            hiddenFields.forEach(function (field) {
                field.remove();
            });
        }
    }

    function resumeForm(form, submitter) {
        form.dataset._tbConfirmed = "1";
        try {
            if (typeof form.requestSubmit === "function") {
                if (submitter) form.requestSubmit(submitter);
                else form.requestSubmit();
                return;
            }
            nativeSubmitWithSubmitter(form, submitter);
        } finally {
            delete form.dataset._tbConfirmed;
        }
    }

    document.addEventListener("submit", function (e) {
        var form = e.target && e.target.closest && e.target.closest("form[data-confirm]");
        if (!form) return;
        if (form.dataset._tbConfirmed === "1") return;
        var submitter = isSubmitControl(e.submitter, form) ? e.submitter : null;
        var displayTrigger = submitter || form.querySelector(
            'button:not([type]), button[type="submit"], input[type="submit"], input[type="image"]'
        );
        e.preventDefault();
        ask(form.dataset.confirm, form, displayTrigger).then(function (ok) {
            if (!ok) return;
            // requestSubmit preserves the originating button's name/value and
            // replays the native submit event (including CSRF listeners).
            resumeForm(form, submitter);
        });
    }, true);

    document.addEventListener("click", function (e) {
        var target = e.target;
        if (!target || !target.closest) return;
        var btn = target.closest("button[data-confirm], a[data-confirm]");
        if (!btn) return;
        if (btn.dataset._tbConfirmed === "1") return;
        e.preventDefault();
        e.stopPropagation();
        ask(btn.dataset.confirm, btn, btn).then(function (ok) {
            if (!ok) return;
            btn.dataset._tbConfirmed = "1";
            var form = btn.form;
            if (form && form.dataset.confirm) form.dataset._tbConfirmed = "1";
            try {
                if (btn.tagName === "A") {
                    window.location.assign(btn.href);
                    return;
                }
                // Re-dispatch click so native button submitter/name/value
                // semantics and any existing click consumers remain intact.
                btn.click();
            } finally {
                delete btn.dataset._tbConfirmed;
                if (form && form.dataset.confirm) delete form.dataset._tbConfirmed;
            }
        });
    }, true);
})();
