(async function () {
  "use strict";
  const wait = async (read, description) => {
    const until = Date.now() + 8000;
    while (Date.now() < until) {
      const result = read();
      if (result) return result;
      await new Promise(resolve => setTimeout(resolve, 25));
    }
    throw Error("Timed out: " + description);
  };
  try {
    const form = await wait(() => document.querySelector("form[data-expensereview-draft-scope]"), "financial form");
    await wait(() => form.expenseReviewContinuity && !form.elements.merchant.readOnly, "draft owner");
    const marker = await wait(() => document.querySelector("[data-expense-ocr-watch]"), "queued task");
    const before = Object.fromEntries(new FormData(form));
    form.elements.merchant.value = "识别途中未保存的商家";
    form.elements.merchant.dispatchEvent(new Event("input", {bubbles: true}));
    const response = await fetch("/ocr-watch-finish", {method: "POST"});
    if (!response.ok) throw Error("Worker completion failed");
    await wait(() => marker.getAttribute("aria-busy") === "false", "task completion observer");
    const after = Object.fromEntries(new FormData(form));
    window.__expenseReviewResult = {
      merchant: after.merchant,
      identity_retained: ["expected_row_version", "idempotency_key", "draft_ref", "draft_scope"]
        .every(name => before[name] === after[name]),
      message: marker.querySelector("[data-ocr-task-message]").textContent,
      result_link_visible: !marker.querySelector("[data-ocr-result-link]").hidden,
      cancel_hidden: marker.querySelector("[data-ocr-cancel]").hidden,
      horizontal_overflow: document.documentElement.scrollWidth > window.innerWidth,
    };
  } catch (error) { window.__expenseReviewResult = {error: String(error)}; }
})();
