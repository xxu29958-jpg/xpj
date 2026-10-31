(async function () {
  "use strict";
  if (document.readyState === "loading") await new Promise(resolve => document.addEventListener("DOMContentLoaded", resolve, {once: true}));
  const key = "recognition-correction-note-probe", state = JSON.parse(sessionStorage.getItem(key) || "null") || {stage: "note"};
  const save = () => sessionStorage.setItem(key, JSON.stringify(state));
  const assert = (value, message) => { if (!value) throw Error(message); };
  const wait = async predicate => {
    for (let attempt = 0; attempt < 200; attempt++) {
      if (predicate()) return;
      await new Promise(resolve => setTimeout(resolve, 25));
    }
    throw Error("Correction note did not reach " + state.stage);
  };
  try {
    const form = document.querySelector("form.edit-form"), field = name => form.elements.namedItem(name);
    await wait(() => form.dataset.expensereviewDraftPhase && !form.querySelector("[data-expensereview-submit]").disabled);
    if (state.stage === "saved") {
      window.__expenseReviewResult = {completed: true, notes: state.notes};
      return;
    }
    const choices = () => JSON.parse(field("recognition_field_choices")?.value || "[]");
    for (const [name, input, original, recalled] of [
      ["amount_cents", "amount_yuan", "18.00", "1.80"], ["merchant", "merchant", "海棠咖吽", "海棠咖啡"]]) {
      const group = form.querySelector(`[data-recognized-fields="${name}"]`);
      const readings = [...group.querySelectorAll("[data-recognized-field]")]
        .map(item => JSON.parse(item.dataset.recognizedField));
      assert(readings[0].value === readings[0].source_reading_value,
        `Historical ${name} correction displaced this original's first reading`);
      assert(field(input).value === original, `Historical ${name} correction changed the draft on display`);
      const button = [...group.querySelectorAll("[data-recognized-field-correction]")]
        .find(item => JSON.parse(item.dataset.recognizedFieldCorrection).selection_intent === "bookkeeping");
      assert(button, `The earlier ${name} correction is not recalled here`);
      const candidate = JSON.parse(button.dataset.recognizedFieldCorrection);
      assert(String(candidate.value) !== String(candidate.source_reading_value), `Recall did not change the shown ${name}`);
      assert(!candidate.event_selected && candidate.label.includes("曾读错"), `Historical ${name} correction became an event default`);
      group.open = true;
      // Typing back the parser's own reading is not a correction of it.
      field(input).value = original; button.click();
      assert(group.querySelector("[data-recognized-field-status]").textContent.includes("与这处原文相同") &&
        !choices().some(item => item.field === name), `Typing back the original ${name} reading was noted`);
      // Confirming the recalled value against the original is the explicit correction the backend qualifies.
      field(input).value = recalled; button.click();
      assert(choices().some(item => item.field === name && item.intent === "original_correction"),
        `Confirming the recalled ${name} against the original was refused`);
    }
    state.notes = choices(); state.stage = "saved"; save();
    form.requestSubmit([...form.querySelectorAll("button")].find(button => button.textContent === "保存草稿"));
  } catch (error) {
    window.__expenseReviewResult = {error: String(error && error.stack || error), stage: state.stage};
  }
})();
