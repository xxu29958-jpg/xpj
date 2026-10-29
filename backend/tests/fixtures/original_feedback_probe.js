(async function () {
  "use strict";
  if (document.readyState === "loading") await new Promise(resolve => document.addEventListener("DOMContentLoaded", resolve, {once: true}));
  const key = "original-feedback-probe", state = JSON.parse(sessionStorage.getItem(key) || "null") || {stage: "edit", requests: []};
  const save = () => sessionStorage.setItem(key, JSON.stringify(state));
  const assert = (value, message) => { if (!value) throw Error(message); };
  const wait = async predicate => { for (let n = 0; n < 250; n++) { if (predicate()) return; await new Promise(resolve => setTimeout(resolve, 25)); } throw Error("Feedback timed out at " + state.stage); };
  const originalFetch = window.fetch, mode = new URL(location.href).searchParams.get("feedback");
  const action = new URL(location.href).searchParams.get("feedback_action") || "save";
  window.fetch = async (url, options) => {
    if (!/\/42\/(save|confirm)$/.test(new URL(url, location.href).pathname)) return originalFetch(url, options);
    state.requests.push([...options.body].filter(([name]) => name !== "csrf_token")); save();
    const response = await originalFetch(url, options);
    if (!response.ok) { state.refusal = await response.clone().text(); save(); }
    assert(response.ok, "Original feedback save refused");
    if (state.stage === "sent") { state.stage = "unknown"; save(); throw Error("Committed reply lost"); }
    return response;
  };
  async function preparePanelsTogether(form, panel) {
    const sibling = form.querySelector('[data-original-feedback="merchant"]'), previousFetch = window.fetch;
    let release, requests = 0;
    const ready = new Promise(resolve => { release = resolve; });
    window.fetch = async (url, options) => {
      if (new URL(url, location.href).href === new URL(panel.dataset.sourceImageHref, location.href).href) {
        requests++; await ready;
      }
      return previousFetch(url, options);
    };
    for (const selected of [panel, sibling]) {
      for (let parent = selected; parent; parent = parent.parentElement) if (parent.tagName === "DETAILS") parent.open = true;
    }
    try {
      await wait(() => requests > 0 && [panel, sibling].every(item => item.querySelector("[data-feedback-status]").textContent.includes("正在核对")));
      release();
      await wait(() => [panel, sibling].every(item => item.querySelector("[data-feedback-status]").textContent.includes("可直接")));
      state.parallel_metadata_ready = true; save();
    } finally { release(); window.fetch = previousFetch; }
    sibling.open = false;
  }
  async function prepareFeedback(form, field) {
    assert(!form.querySelector("[data-recognized-field]"), "This case must have no OCR candidates");
    field("amount_yuan").value = "17.00"; field("amount_yuan").dispatchEvent(new Event("input", {bubbles: true}));
    const panel = form.querySelector('[data-original-feedback="amount_cents"]');
    assert(panel, "No-candidate feedback is missing");
    await preparePanelsTogether(form, panel);
    const text = panel.querySelector('[data-feedback-input="verbatim_text"]');
    text.value = "实付：78.00"; text.dispatchEvent(new Event("input", {bubbles: true}));
    panel.querySelector('[data-feedback-input="text_verified"]').click();
    const open = async () => {
      panel.querySelector("[data-feedback-locate]").click();
      const dialog = form.querySelector(".recognition-source-dialog");
      await wait(() => !dialog.querySelector("[data-feedback-use]").disabled);
      assert(dialog.querySelector('[data-feedback-mode="browse"]').getAttribute("aria-pressed") === "true", "Locator did not start in browse mode");
      dialog.querySelector('[data-feedback-mode="corners"]').click();
      return dialog;
    };
    const tap = (dialog, x, y) => {
      const image = dialog.querySelector("img"), bounds = image.getBoundingClientRect();
      const options = {bubbles: true, isPrimary: true, button: 0, pointerId: 1, clientX: bounds.left + x / image.naturalWidth * bounds.width, clientY: bounds.top + y / image.naturalHeight * bounds.height};
      image.dispatchEvent(new PointerEvent("pointerdown", options)); image.dispatchEvent(new PointerEvent("pointerup", options));
    };
    const chooseLine = dialog => {
      const group = dialog.querySelector("[data-feedback-lines]");
      assert(!group.hidden, "Original OCR text lines are missing without parsed candidates"); group.open = true;
      const choices = [...dialog.querySelectorAll("[data-feedback-line]")];
      assert(choices.length === 2 && choices.every(button => button.getBoundingClientRect().height >= 48), "Text line targets are too small");
      choices.find(button => button.textContent === "实付：7B.OO").click();
    };
    let dialog = await open();
    if (mode === "suggested_region") chooseLine(dialog); else tap(dialog, 20, 50);
    dialog.querySelector("[data-source-close]").click();
    assert(JSON.parse(field("original_text_feedback").value)[0].location_state === "unlocated", "Cancel committed an unaccepted location");
    if (mode !== "unlocated") {
      dialog = await open();
      if (mode === "suggested_region") chooseLine(dialog); else tap(dialog, 20, 50);
      if (mode === "verified_region") { dialog.querySelector('[data-source-zoom="2"]').click(); tap(dialog, 390, 75); }
      dialog.querySelector("[data-feedback-use]").click();
      if (mode === "verified_region") panel.querySelector('[data-feedback-input="region_verified"]').click();
    }
    const feedback = JSON.parse(field("original_text_feedback").value)[0];
    assert(feedback.verbatim_text === "实付：78.00" && feedback.location_state === mode, "Feedback text/location changed");
    assert(field("amount_yuan").value === "17.00" && !field("recognition_field_choices")?.value, "Annotation rewrote finance or forged a candidate");
    if (mode === "coarse_point") assert(JSON.stringify(feedback.point) === "[20,50]", "Point not in original pixels");
    if (mode === "verified_region") assert(JSON.stringify(feedback.box) === "[20,50,390,75]", "Zoom mixed coordinate spaces");
    if (mode === "suggested_region") assert(JSON.stringify(feedback.box) === "[20,50,390,75]" &&
      !panel.querySelector('[data-feedback-input="region_verified"]').checked, "Selecting an OCR line incorrectly verified it");
    panel.scrollIntoView({block: "center"}); window.__originalFeedbackPreviewReady = true;
    await wait(() => window.__originalFeedbackPreviewCaptured);
  }
  try {
    if (document.querySelector("[data-expense-confirmation]")) {
      assert(state.requests.length === 2 && document.body.textContent.includes("原文反馈已保留"), "Confirmation omitted the original feedback receipt");
      window.__expenseReviewResult = {...state, completed: true}; return;
    }
    const drawer = location.pathname === "/web/pending";
    if (drawer) { document.querySelector('.exp-row[data-expense-id="42"] .exp-row-detail').click(); await wait(() => document.querySelector("#drawer [data-drawer-form]")); }
    const form = document.querySelector(drawer ? "#drawer [data-drawer-form]" : "form.edit-form"), field = name => form.elements.namedItem(name);
    const primary = form.querySelector("[data-expensereview-submit]");
    await wait(() => form.dataset.expensereviewDraftPhase && !primary.disabled);
    if (state.stage === "replay") {
      assert(!field("original_text_feedback")?.value, "Accepted feedback was copied into the next command");
      assert(document.body.textContent.includes("原文反馈已保留"), "Accepted feedback has no truthful acknowledgement");
      window.__expenseReviewResult = {...state, completed: true}; return;
    }
    if (state.stage === "unknown") {
      assert(form.dataset.expensereviewDraftPhase === "submitted", "Lost reply replaced original command");
      assert(field("original_text_feedback").value === state.feedback, "Reload lost the independent original text");
      state.stage = "replay"; save(); form.requestSubmit(primary);
      if (drawer) {
        await wait(() => !form.isConnected);
        assert(document.body.textContent.includes("原文反馈已保留"), "Drawer did not acknowledge the committed feedback");
        window.__expenseReviewResult = {...state, completed: true};
      }
      return;
    }
    await prepareFeedback(form, field);
    state.feedback = field("original_text_feedback").value; state.stage = "sent"; save();
    form.requestSubmit(action === "confirm" ? primary : [...form.querySelectorAll("button")].find(button => button.textContent === "保存草稿"));
    await wait(() => state.stage === "unknown" && form.querySelector("[data-expensereview-draft-status]").textContent.includes("暂未收到"));
    location.reload();
  } catch (error) { window.__expenseReviewResult = {...state, error: String(error)}; }
})();
