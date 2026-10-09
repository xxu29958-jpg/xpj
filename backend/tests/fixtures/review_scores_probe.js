/* Real full-page/drawer score input, refresh, accepted-reply loss and original replay. */
(async () => {
  const key = "review-scores-probe", state = JSON.parse(sessionStorage.getItem(key) || "null") || {stage: "start"};
  const save = () => sessionStorage.setItem(key, JSON.stringify(state));
  const check = (value, message) => { if (!value) throw Error(message); };
  const wait = async (read, message) => {
    for (let i = 0; i < 100; i++) { if (read()) return; await new Promise(resolve => setTimeout(resolve, 40)); }
    throw Error(message);
  };
  if (state.stage === "saved") { window.__expenseReviewResult = state; return; }
  if (location.pathname === "/web/pending") {
    await wait(() => window.TicketboxWeb?.drawerApi, "drawer scripts unavailable");
    if (!window.TicketboxWeb.drawerApi.isOpen()) document.querySelector('.exp-row[data-expense-id="42"] .exp-row-detail').click();
  }
  const current = () => document.querySelector("form[data-expensereview-draft-scope]");
  await wait(() => current()?.expenseReviewContinuity && !current().querySelector('[data-expensereview-submit]').disabled, "review did not become available");
  const form = current();
  check(form.elements.value_score?.length === 6 && form.elements.regret_score?.length === 6, "pending review has no complete score controls");
  const get = name => form.elements.namedItem(name).value;
  const put = (name, value) => {
    const input = form.elements.namedItem(name);
    if (typeof input.dispatchEvent !== "function") { [...input].find(radio => radio.value === value).click(); return; }
    input.value = value; input.dispatchEvent(new Event("input", {bubbles: true}));
  };
  const submit = () => form.requestSubmit([...form.querySelectorAll('button[type="submit"]')].find(button => button.textContent.trim() === "保存草稿"));
  const fetch = window.fetch.bind(window);
  window.fetch = async (url, options) => {
    const response = await fetch(url, options);
    if (new URL(url, location.href).pathname.endsWith("/42/save") && options?.method === "POST") {
      check(response.ok, "score save was rejected");
      const fields = [...options.body].filter(([name]) => name !== "csrf_token");
      if (!state.first) { state.first = fields; state.stage = "unknown"; save(); throw Error("accepted response lost"); }
      state.replay = fields; state.stage = "saved"; save();
    }
    return response;
  };
  if (state.stage === "start") {
    put("merchant", "原评分填写"); put("value_score", ""); put("regret_score", "5");
    check(get("value_score") === "" && get("regret_score") === "5", "native score choice did not take effect");
    state.key = get("idempotency_key"); state.stage = "restored"; save(); location.reload(); return;
  }
  if (state.stage === "restored") {
    check(get("value_score") === "" && get("regret_score") === "5" && get("merchant") === "原评分填写",
      "score draft was not restored: " + JSON.stringify({value: get("value_score"), regret: get("regret_score"), merchant: get("merchant")}));
    check(get("idempotency_key") === state.key && get("expected_row_version") === "4", "score draft borrowed a new command");
    state.resumed = true;
    submit();
    await wait(() => form.dataset.expensereviewDraftPhase === "submitted" && !form.querySelector('[data-expensereview-submit]').disabled, "accepted score result not retained");
    location.reload(); return;
  }
  check(state.stage === "unknown", "unexpected score recovery stage");
  form.requestSubmit(form.querySelector('[data-expensereview-submit]'));
  await wait(() => state.replay, "original score submission was not replayed");
  window.__expenseReviewResult = state;
})().catch(error => { window.__expenseReviewResult = {error: String(error), stack: error.stack}; });
