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
  function applyCandidate(form, candidate, correction) {
    if (correction) {
      const input = form.elements.namedItem(candidate.field === "amount_cents" ? "amount_yuan" : "merchant");
      return Boolean(input && !input.disabled && input.value.trim());
    }
    if (candidate.field === "amount_cents") return copyMoney(form, candidate);
    const merchant = form.elements.namedItem("merchant");
    if (!merchant || merchant.disabled) return false;
    merchant.value = candidate.value; merchant.dispatchEvent(new Event("input", {bubbles: true}));
    return true;
  }
  document.addEventListener("click", event => {
    const button = event.target.closest("[data-recognized-field], [data-recognized-field-correction]");
    if (!button || button.disabled || button.closest("fieldset")?.disabled) return;
    const correction = button.hasAttribute("data-recognized-field-correction");
    const form = button.closest("form"), candidate = JSON.parse(button.dataset.recognizedField || button.dataset.recognizedFieldCorrection);
    if (!form || !candidate.can_apply || !applyCandidate(form, candidate, correction)) return;
    saveChoices(form, [...choices(form).filter(item => item.field !== candidate.field), {
      field: candidate.field, candidate_id: candidate.id, evidence_public_id: candidate.evidence_public_id,
      parser_version: candidate.parser_version, source: candidate.source,
      intent: correction ? "original_correction" : (candidate.selection_intent || "candidate"),
    }]);
    button.closest("[data-recognized-fields]").querySelector("[data-recognized-field-status]").textContent = correction
      ? "已注明你对照这一处原件作了纠正，请保存当前修改。" : "已填入当前草稿，请核对后保存。";
  });
  document.addEventListener("input", event => {
    if (!event.isTrusted || !event.target.form) return;
    const field = {amount_yuan: "amount_cents", original_currency: "amount_cents", merchant: "merchant"}[event.target.name];
    if (field) saveChoices(event.target.form, choices(event.target.form).filter(item => item.field !== field));
  });
})();
