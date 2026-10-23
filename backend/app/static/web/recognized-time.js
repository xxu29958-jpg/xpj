/* A deliberate copy into the existing draft; never a request or automatic update. */
(function () {
"use strict";
document.addEventListener("click", function (event) {
  const button = event.target.closest("[data-recognized-time]");
  if (!button || button.disabled) return;
  const candidate = JSON.parse(button.dataset.recognizedTime);
  if (!candidate.can_apply) return;
  if (button.hasAttribute("data-recognized-date")) {
    copyRepaymentDate(button, candidate);
  } else {
    copyExpenseTime(button, candidate);
  }
});

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
  const form = button.closest("form");
  if (candidate.evidence_public_id && candidate.parser_version && candidate.source) {
    let input = form.elements.namedItem("recognition_time_choice");
    if (!input) {
      input = document.createElement("input"); input.type = "hidden";
      input.name = "recognition_time_choice"; form.append(input);
    }
    input.value = JSON.stringify({evidence_public_id: candidate.evidence_public_id,
      candidate_id: candidate.id, parser_version: candidate.parser_version, source: candidate.source, intent: "candidate"});
    input.dispatchEvent(new Event("input", {bubbles: true}));
  }
  fieldset.querySelector("[data-recognized-time-status]").textContent = "已填入当前草稿，请核对后保存。";
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
