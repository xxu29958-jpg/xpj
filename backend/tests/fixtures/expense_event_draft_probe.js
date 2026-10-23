(async function () {
  "use strict";
  if (document.readyState === "loading") await new Promise(resolve => document.addEventListener("DOMContentLoaded", resolve, {once: true}));
  const key = "event-draft-probe", state = JSON.parse(sessionStorage.getItem(key) || "null") || {stage: "choose", requests: []};
  const save = () => sessionStorage.setItem(key, JSON.stringify(state));
  const assert = (value, message) => { if (!value) throw Error(message); };
  const wait = async predicate => {
    for (let attempt = 0; attempt < 200; attempt++) {
      if (predicate()) return;
      await new Promise(resolve => setTimeout(resolve, 25));
    }
    throw Error("Event choice did not reach " + state.stage);
  };
  const fetchOriginal = window.fetch;
  window.fetch = async (url, options) => {
    if (!new URL(url, location.href).pathname.endsWith("/42/save")) return fetchOriginal(url, options);
    state.requests.push([...options.body].filter(([name]) => name !== "csrf_token")); save();
    const response = await fetchOriginal(url, options);
    if (state.stage === "sent") {
      assert(response.ok, "Event draft save was refused");
      state.stage = "unknown"; save(); throw Error("Committed acknowledgement lost");
    }
    if (state.stage === "replay") { assert(response.ok, "Original event command replay was refused"); state.replayAccepted = true; save(); }
    return response;
  };
  async function chooseAndSave(form, field) {
    const button = [...form.querySelectorAll("[data-recognized-event]")].find(item => item.textContent.includes("第2笔"));
    assert(button && button.textContent.includes("金额、商户、时间"), "No coherent second transaction action");
    assert(!field("recognition_time_choice")?.value && !field("recognition_field_choices")?.value, "Default display supplied labels");
    for (let parent = button.parentElement; parent; parent = parent.parentElement) {
      if (parent.tagName === "DETAILS" && !parent.open) parent.querySelector(":scope > summary").click();
    }
    button.scrollIntoView({block: "center"});
    await new Promise(resolve => requestAnimationFrame(resolve));
    const bounds = button.getBoundingClientRect();
    assert(!button.disabled && button.contains(document.elementFromPoint(bounds.x + bounds.width / 2,
      bounds.y + bounds.height / 2)), "Transaction action cannot be clicked on the page");
    button.click();
    assert(field("amount_yuan").value === "28.00" && field("merchant").value === "青禾超市", "Fields were borrowed from another transaction");
    assert(field("expense_time").value.startsWith("2026-10-21T09:20"), "The selected transaction lost its time");
    const choices = JSON.parse(field("recognition_field_choices").value), time = JSON.parse(field("recognition_time_choice").value);
    assert(choices.length === 2 && [...choices, time].every(item => item.intent === "bookkeeping"), "Bundle acceptance became a role-training label");
    window.__eventDraftPreviewReady = true;
    await wait(() => window.__eventDraftPreviewCaptured === true);
    state.fieldChoices = field("recognition_field_choices").value; state.timeChoice = field("recognition_time_choice").value;
    state.stage = "sent"; save();
    form.requestSubmit([...form.querySelectorAll("button")].find(item => item.textContent === "保存草稿"));
    await wait(() => state.stage === "unknown" && form.querySelector("[data-expensereview-draft-status]").textContent.includes("暂未收到"));
    location.reload();
  }
  try {
    const drawer = location.pathname === "/web/pending";
    if (drawer) {
      if (!window.TicketboxWeb.drawerApi.isOpen()) document.querySelector('.exp-row[data-expense-id="42"] .exp-row-detail').click();
      await wait(() => document.querySelector("#drawer [data-drawer-form]"));
    }
    const form = document.querySelector(drawer ? "#drawer [data-drawer-form]" : "form.edit-form"), field = name => form.elements.namedItem(name);
    const primary = form.querySelector("[data-expensereview-submit]");
    await wait(() => form.dataset.expensereviewDraftPhase && !primary.disabled);
    if (state.stage === "choose") {
      await chooseAndSave(form, field);
    } else if (state.stage === "unknown") {
      assert(form.dataset.expensereviewDraftPhase === "submitted", "Lost reply created a new intent");
      assert(field("recognition_field_choices").value === state.fieldChoices && field("recognition_time_choice").value === state.timeChoice, "Reload replaced original event identities");
      state.stage = "replay"; save(); form.requestSubmit(primary);
      if (drawer) {
        await wait(() => state.replayAccepted && !form.isConnected && document.querySelector("#drawer [data-drawer-form]"));
        window.__expenseReviewResult = {...state, completed: true};
      }
    } else if (state.stage === "replay") {
      window.__expenseReviewResult = {...state, completed: true};
    }
  } catch (error) { window.__expenseReviewResult = {...state, error: String(error)}; }
})();
