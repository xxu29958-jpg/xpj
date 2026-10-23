/* The real editor must replay the displayed advice identity after a lost acknowledgement. */
(async function () {
  "use strict";
  if (document.readyState === "loading") {
    await new Promise(resolve => document.addEventListener("DOMContentLoaded", resolve, {once: true}));
  }
  const key = "learning-choice-probe";
  const state = JSON.parse(sessionStorage.getItem(key) || "null") || {stage: "choose", requests: []};
  const save = () => sessionStorage.setItem(key, JSON.stringify(state));
  const assert = (value, message) => { if (!value) throw Error(message); };
  const wait = async predicate => {
    for (let attempt = 0; attempt < 200; attempt++) {
      if (predicate()) return;
      await new Promise(resolve => setTimeout(resolve, 25));
    }
    throw Error("Learning choice did not reach " + state.stage);
  };
  const fetchOriginal = window.fetch;
  window.fetch = async (url, options) => {
    if (!new URL(url, location.href).pathname.endsWith("/42/save")) return fetchOriginal(url, options);
    state.requests.push([...options.body].filter(([name]) => name !== "csrf_token")); save();
    const response = await fetchOriginal(url, options);
    if (state.stage === "sent") {
      assert(response.ok, "Original save was refused");
      state.stage = "unknown"; save();
      throw Error("Committed acknowledgement lost");
    }
    return response;
  };
  try {
    const form = document.querySelector("form.edit-form"), field = name => form.elements.namedItem(name);
    const primary = form.querySelector("[data-expensereview-submit]");
    await wait(() => form.dataset.expensereviewDraftPhase && !primary.disabled);
    if (state.stage === "choose") {
      assert(!field("category_choice")?.value, "Untouched category became feedback");
      const suggestion = form.querySelector("[data-category-suggestion]");
      assert(suggestion && !suggestion.disabled, "Original category advice is not actionable");
      state.decision = suggestion.dataset.categoryDecision;
      state.category = field("category").value;
      suggestion.click();
      assert(field("category").value === state.category, "This case must exercise a same-value choice");
      assert(field("category_choice").value === "suggestion", "Choice was not preserved");
      assert(!field("recognition_time_choice")?.value, "Untouched time became feedback");
      const time = form.querySelector("[data-recognized-time]");
      assert(time, "Original time candidate is missing");
      assert(!time.disabled, "Original time candidate is not actionable");
      time.click();
      state.timeChoice = field("recognition_time_choice").value;
      assert(state.timeChoice, "Explicit time choice is missing");
      assert(JSON.parse(state.timeChoice).candidate_id === JSON.parse(time.dataset.recognizedTime).id,
        "Explicit time choice lost its original evidence identity");
      state.stage = "sent"; save();
      form.requestSubmit([...form.querySelectorAll("button")].find(button => button.textContent === "保存草稿"));
      await wait(() => state.stage === "unknown" && form.querySelector("[data-expensereview-draft-status]").textContent.includes("暂未收到"));
      location.reload();
    } else if (state.stage === "unknown") {
      assert(form.dataset.expensereviewDraftPhase === "submitted", "Unknown save became a new editable command");
      assert(field("category_decision_public_id").value === state.decision, "Reload borrowed a newer advice identity");
      assert(field("category_choice").value === "suggestion", "Reload lost explicit choice");
      assert(field("recognition_time_choice").value === state.timeChoice, "Reload borrowed a newer time candidate");
      state.stage = "replay"; save(); form.requestSubmit(primary);
    } else if (state.stage === "replay") {
      assert(!field("category_choice")?.value && !field("category_decision_public_id")?.value,
        "The next command inherited the already accepted vote");
      assert(!field("recognition_time_choice")?.value, "The next command inherited a previous time choice");
      window.__expenseReviewResult = {...state, completed: true};
    }
  } catch (error) {
    window.__expenseReviewResult = {...state, error: String(error)};
  }
})();
