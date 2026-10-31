(async function () {
  const key = "recognition-source-order-probe";
  const assert = (ok, message) => { if (!ok) throw Error(message); };
  try {
    if (document.readyState === "loading") await new Promise(resolve => document.addEventListener("DOMContentLoaded", resolve, {once: true}));
    const form = document.querySelector("form.edit-form");
    for (let i = 0; i < 200 && (!form.dataset.expensereviewDraftPhase || form.querySelector("[data-expensereview-submit]").disabled); i++) {
      await new Promise(resolve => setTimeout(resolve, 25));
    }
    const saved = sessionStorage.getItem(key);
    if (saved) { window.__expenseReviewResult = {completed: true, chosen: JSON.parse(saved)}; return; }
    const buttons = [...form.querySelectorAll('[data-recognized-fields="amount_cents"] [data-recognized-field]')];
    const readings = buttons.map(button => JSON.parse(button.dataset.recognizedField));
    assert(readings[0].value === 2500 && readings.at(-1).value === 1800, "Abstained readings lost source text order");
    assert(readings.every(item => item.presentation === "source-order-v1:text"), "Text-only evidence claimed image or score order");
    assert(form.elements.namedItem("amount_yuan").value === "18.00", "Displaying source order changed the accounting draft");
    buttons[0].click();
    const chosen = JSON.parse(form.elements.namedItem("recognition_field_choices").value)[0];
    assert(chosen.presentation === readings[0].presentation, "Choice lost its displayed order");
    sessionStorage.setItem(key, JSON.stringify(chosen));
    form.requestSubmit([...form.querySelectorAll("button")].find(button => button.textContent === "保存草稿"));
  } catch (error) { window.__expenseReviewResult = {error: String(error.stack || error)}; }
})();
