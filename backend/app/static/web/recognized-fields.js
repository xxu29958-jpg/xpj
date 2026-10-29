/* Explicit source choices travel with the existing immutable draft command. */
(function () {
  "use strict";
  function choices(form) {
    const value = form.elements.namedItem("recognition_field_choices")?.value;
    return value ? JSON.parse(value) : [];
  }
  function saveChoices(form, value) {
    let input = form.elements.namedItem("recognition_field_choices");
    if (!value.length) { input?.remove(); return; }
    if (!input) {
      input = document.createElement("input"); input.type = "hidden";
      input.name = "recognition_field_choices"; form.append(input);
    }
    input.value = JSON.stringify(value);
    input.dispatchEvent(new Event("input", {bubbles: true}));
  }
  function copyMoney(form, candidate) {
    const amount = form.elements.namedItem("amount_yuan"), currency = form.elements.namedItem("original_currency");
    const exponent = candidate.minor_unit_exponent;
    if (!amount || amount.disabled || !currency || currency.disabled || !Number.isSafeInteger(candidate.value) ||
        !Number.isInteger(exponent) || exponent < 0 || exponent > 6) return false;
    if (currency.options && ![...currency.options].some(option => option.value === candidate.currency_code)) return false;
    const digits = String(candidate.value).padStart(exponent + 1, "0");
    currency.value = candidate.currency_code;
    amount.value = exponent ? digits.slice(0, -exponent) + "." + digits.slice(-exponent) : digits;
    for (const input of [currency, amount]) {
      input.dispatchEvent(new Event("input", {bubbles: true}));
      input.dispatchEvent(new Event("change", {bubbles: true}));
    }
    return true;
  }
  function fieldInput(form, field) {
    return form.elements.namedItem(field === "amount_cents" ? "amount_yuan" : "merchant");
  }
  function noun(field) {
    return field === "amount_cents" ? "金额" : "商户";
  }
  function minorUnits(text, exponent) {
    const match = /^(\d*)(?:\.(\d*))?$/.exec(text);
    if (!match || (match[2] || "").length > exponent) return null;
    return Number((match[1] || "0") + (match[2] || "").padEnd(exponent, "0"));
  }
  // Same rule as Android and the backend's learning qualification: a correction only counts when the
  // field holds a value that differs from this reading, in the reading's currency.
  function correctionProblem(form, candidate) {
    const input = fieldInput(form, candidate.field), name = noun(candidate.field), value = input?.value.trim();
    if (!input || input.disabled) return `这笔账单的${name}不能在这里修改。`;
    if (!value) return `${name}还是空的：请先在上方填入你核对后的${name}，再点“注明已对照此处纠正${name}”。`;
    const unchanged = `${name}与这处原文相同，没有需要注明的纠正；若原文读错，请先改正${name}。`;
    if (candidate.field !== "amount_cents") return value === String(candidate.value).trim() ? unchanged : "";
    if (form.elements.namedItem("original_currency")?.value !== candidate.currency_code) {
      return "这处原文的币种与当前填写不同；只有在同一币种下改正了金额，才能注明对照纠正。";
    }
    return minorUnits(value, candidate.minor_unit_exponent) === candidate.value ? unchanged : "";
  }
  function applyCandidate(form, candidate) {
    if (candidate.field === "amount_cents") return copyMoney(form, candidate);
    const merchant = form.elements.namedItem("merchant");
    if (!merchant || merchant.disabled) return false;
    merchant.value = candidate.value; merchant.dispatchEvent(new Event("input", {bubbles: true}));
    return true;
  }
  function unavailableMessage(form, candidate) {
    const input = fieldInput(form, candidate.field), name = noun(candidate.field);
    if (!input || input.disabled) return `这笔账单的${name}不能在这里修改。`;
    return `无法自动填入这条${name}，请直接修改${name}。`;
  }
  document.addEventListener("focusin", event => {
    const field = {amount_yuan: "amount_cents", merchant: "merchant"}[event.target.name];
    const candidates = field && event.target.form?.querySelector(`[data-recognized-fields="${field}"]`);
    if (candidates) candidates.open = true;
  });
  document.addEventListener("click", event => {
    const button = event.target.closest("[data-recognized-field], [data-recognized-field-correction]");
    if (!button || button.disabled || button.closest("fieldset")?.disabled) return;
    const correction = button.hasAttribute("data-recognized-field-correction");
    const form = button.closest("form"), candidate = JSON.parse(button.dataset.recognizedField || button.dataset.recognizedFieldCorrection);
    if (!form || !candidate.can_apply) return;
    const status = button.closest("[data-recognized-fields]").querySelector("[data-recognized-field-status]");
    // An enabled control never fails silently: say why nothing was recorded.
    const problem = correction ? correctionProblem(form, candidate)
      : !applyCandidate(form, candidate) && unavailableMessage(form, candidate);
    if (problem) {
      status.textContent = problem;
      return;
    }
    saveChoices(form, [...choices(form).filter(item => item.field !== candidate.field), {
      field: candidate.field, candidate_id: candidate.id, evidence_public_id: candidate.evidence_public_id,
      parser_version: candidate.parser_version, source: candidate.source,
      intent: button.dataset.eventDraftApply ? "bookkeeping" : correction ? "original_correction" : (candidate.selection_intent || "candidate"),
    }]);
    status.textContent = correction
      ? "已注明你对照这一处原件作了纠正，请保存当前修改。" : "已填入当前草稿，请核对后保存。";
  });
  document.addEventListener("input", event => {
    if (!event.isTrusted || !event.target.form) return;
    const field = {amount_yuan: "amount_cents", original_currency: "amount_cents", merchant: "merchant"}[event.target.name];
    if (!field) return;
    // Typing drops this field's choice; a dropped correction says so instead of leaving "已注明" on screen.
    const form = event.target.form, current = choices(form);
    const corrected = current.some(item => item.field === field && item.intent === "original_correction");
    saveChoices(form, current.filter(item => item.field !== field));
    const status = form.querySelector(`[data-recognized-fields="${field}"] [data-recognized-field-status]`);
    if (status && corrected) status.textContent = `你改动了${noun(field)}，之前的注明已取消；改好后可再点一次注明。`;
  });
})();
