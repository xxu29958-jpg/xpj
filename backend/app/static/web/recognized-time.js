/* A deliberate copy into the existing draft; never a request or automatic update. */
(function () {
"use strict";
document.addEventListener("click", function (event) {
  const button = event.target.closest("[data-recognized-time]");
  if (!button || button.disabled) return;
  let candidate = JSON.parse(button.dataset.recognizedTime);
  if (candidate.requires_year) candidate = completeYear(button, candidate);
  if (!candidate) return;
  if (!candidate.can_apply) return;
  if (button.hasAttribute("data-recognized-date")) {
    copyRepaymentDate(button, candidate);
  } else {
    copyExpenseTime(button, candidate);
  }
});

function completeYear(button, candidate) {
  const yearText = button.closest(".product-field").querySelector("[data-recognized-year]").value;
  const year = Number(yearText), parts = candidate.components;
  const valid = /^[1-9]\d{3}$/.test(yearText) && parts.month >= 1 && parts.month <= 12 &&
    parts.day >= 1 && parts.day <= new Date(year, parts.month, 0).getDate();
  if (!valid) {
    button.closest("[data-recognized-times]").querySelector("[data-recognized-time-status]").textContent = "请补充有效的四位年份，并核对原件中的月日。";
    return null;
  }
  const pad = value => String(value).padStart(2, "0");
  let value = `${yearText}-${pad(parts.month)}-${pad(parts.day)}`;
  if (candidate.precision !== "date_only") value += `T${pad(parts.hour)}:${pad(parts.minute)}`;
  if (candidate.precision === "second") value += `:${pad(parts.second)}`;
  return {...candidate, local_value: value, can_apply: true};
}

function copyRepaymentDate(button, candidate) {
    const date = button.closest("form")?.querySelector('[name="payment_date"]');
    if (!date || date.disabled) return;
    date.value = candidate.local_value.slice(0, 10);
    date.dispatchEvent(new Event("input", { bubbles: true }));
    date.dispatchEvent(new Event("change", { bubbles: true }));
    button.closest("[data-recognized-times]").querySelector("[data-recognized-time-status]").textContent = "已填入还款草稿，请核对后保存。";
}

function copyExpenseTime(button, candidate) {
  const fieldset = button.closest("fieldset");
  if (!fieldset || fieldset.disabled) return;
  const dateOnly = candidate.precision === "date_only";
  const values = {
    time_precision: dateOnly ? "date_only" : "instant",
    user_local_date: candidate.local_value.slice(0, 10),
    expense_time: dateOnly ? "" : candidate.local_value,
    source_timezone: candidate.source_timezone || "",
    source_utc_offset_seconds: dateOnly ? "" : String(candidate.source_utc_offset_seconds ?? ""),
  };
  for (const [name, value] of Object.entries(values)) {
    const input = fieldset.querySelector(`[name="${name}"]`);
    if (!input) continue;
    copyTimeField(input, value);
  }
  recordSourceChoice(button.closest("form"), candidate, Boolean(button.dataset.eventDraftApply));
  fieldset.querySelector("[data-recognized-time-status]").textContent = "已填入当前草稿，请核对后保存。";
}

function recordSourceChoice(form, candidate, eventDraft) {
  if (candidate.evidence_public_id && candidate.parser_version && candidate.source) {
    let input = form.elements.namedItem("recognition_time_choice");
    if (!input) {
      input = document.createElement("input"); input.type = "hidden";
      input.name = "recognition_time_choice"; form.append(input);
    }
    input.value = JSON.stringify({evidence_public_id: candidate.evidence_public_id,
      candidate_id: candidate.id, parser_version: candidate.parser_version, source: candidate.source,
      ...(candidate.presentation ? {presentation: candidate.presentation} : {}),
      intent: eventDraft ? "bookkeeping" : candidate.requires_year ? "original_correction" : "candidate"});
    input.dispatchEvent(new Event("input", {bubbles: true}));
  }
}

function copyTimeField(input, value) {
    if (input.tagName === "SELECT" && value && !Array.from(input.options).some(option => option.value === value)) {
      const seconds = Number(value);
      const hours = String(Math.floor(Math.abs(seconds) / 3600)).padStart(2, "0");
      const minutes = String(Math.floor(Math.abs(seconds) % 3600 / 60)).padStart(2, "0");
      input.add(new Option(`原件 UTC ${seconds < 0 ? "−" : "+"}${hours}:${minutes}`, value));
    }
    input.value = value;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
}
})();
