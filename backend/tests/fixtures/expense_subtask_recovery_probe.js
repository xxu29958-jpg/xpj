/* One real browser journey: independent originals, first receipts, explicit review and return. */
(async () => {
  const key = "subtask-runtime-probe";
  const state = JSON.parse(sessionStorage.getItem(key) || "null") || {
    stage: "start", scenario: new URL(location.href).searchParams.get("probe"), requests: [], receipts: []};
  const save = () => sessionStorage.setItem(key, JSON.stringify(state));
  const check = (value, message) => { if (!value) throw Error(message); };
  const wait = async (read, message) => {
    for (let attempt = 0; attempt < 100; attempt++) { if (read()) return; await new Promise(resolve => setTimeout(resolve, 40)); }
    throw Error(message);
  };
  const form = kind => document.querySelector('form[action$="/' + (kind === "ack" ? "items/acknowledge-mismatch" : kind + "/save") + '"]');
  const field = (current, name) => current.elements.namedItem(name);
  const button = current => current.querySelector("[data-subtask-submit]");
  const put = (current, name, value) => {
    const input = field(current, name); (input.length ? input[0] : input).value = value;
    (input.length ? input[0] : input).dispatchEvent(new Event("input", {bubbles: true}));
  };
  const value = (current, name) => { const input = field(current, name); return (input.length ? input[0] : input).value; };
  const basis = current => Object.fromEntries(["expected_row_version", "idempotency_key", "draft_ref"].map(name => [name, value(current, name)]));
  const main = () => document.querySelector("form.edit-form");
  const go = (stage, href) => { state.stage = stage; save(); if (href) location.assign(href); else location.reload(); };
  const originalFetch = window.fetch.bind(window);
  window.fetch = async (url, options) => {
    const path = new URL(url, location.href).pathname;
    const command = options?.method === "POST" && /^\/web\/expenses\/42\/(items|splits)\//.test(path);
    if (command) { state.requests.push({path, body: [...options.body.entries()].filter(([name]) => name !== "csrf_token")}); save(); }
    const response = await originalFetch(url, options);
    if (command && response.ok) {
      state.receipts.push((await response.clone().json()).receipt); save();
      if (!state.lost) { state.lost = true; save(); throw Error("Accepted response lost in delivery"); }
    }
    return response;
  };
  const post = path => originalFetch("/web/subtask-probe/" + path, {method: "POST"});
  const ready = current => wait(() => current?.expenseReviewContinuity && !button(current).disabled, "command did not become available");
  const pending = current => wait(() => current.dataset["expense" + (current === form("ack") ? "ack" : current === form("items") ? "items" : "splits") + "DraftPhase"] !== "editing" && !button(current).disabled, "original result was not retained");
  const submit = current => current.requestSubmit(button(current));
  const stage = state.stage;
  if (state.scenario !== "rows") {
    if (stage === "start") {
      const ack = form("ack"); await ready(ack); state.original = basis(ack); submit(ack); await pending(ack);
      await post("peer/ack"); go("ack-return"); return;
    }
    if (stage === "ack-return") {
      const ack = form("ack"); await ready(ack);
      check(!ack.hidden && JSON.stringify(basis(ack)) === JSON.stringify(state.original), "accepted acknowledgement lost its original after confirmation");
      state.ack_recovered_after_confirmation = true; state.stage = "ack-saved"; save(); submit(ack); return;
    }
    check(stage === "ack-saved" && !document.querySelector("form.edit-form"), "acknowledgement did not return to current fact");
    window.__expenseReviewResult = state; return;
  }
  if (stage === "start") {
    await ready(form("items")); await ready(form("splits"));
    await wait(() => main().expenseReviewContinuity && !field(main(), "merchant").readOnly, "main draft unavailable");
    put(main(), "merchant", "原核对商家");
    field(main(), "merchant").addEventListener("blur", event => event.target.dispatchEvent(new Event("change", {bubbles: true})), {once: true});
    field(main(), "merchant").focus();
    document.querySelector('.review-subtask-link[href$="#expense-items"]').click();
    await wait(() => !document.querySelector("[data-review-subtasks]").hidden && location.hash === "#expense-items", "retaining a blurred field displaced subtask navigation");
    put(form("items"), "item_name", "原商品填写"); put(form("items"), "item_amount_yuan", "0005.00");
    put(form("splits"), "split_member_id", "1"); put(form("splits"), "split_amount_yuan", "5.50"); put(form("splits"), "split_note", "原拆账填写");
    state.main = basis(main()); state.items = basis(form("items")); state.splits = basis(form("splits"));
    go("restored"); return;
  }
  if (stage === "restored") {
    await ready(form("items")); await ready(form("splits"));
    check(value(main(), "merchant") === "原核对商家" && value(form("items"), "item_amount_yuan") === "0005.00" &&
      value(form("splits"), "split_note") === "原拆账填写", "raw independent drafts were lost on refresh");
    state.raw_restored = true; put(form("items"), "item_amount_yuan", "5.00");
    submit(form("items")); await pending(form("items")); await post("peer/items"); go("unknown"); return;
  }
  if (stage === "unknown") {
    const items = form("items"); await ready(items);
    check(JSON.stringify(basis(items)) === JSON.stringify(state.items), "unknown original borrowed a later version or key");
    check(JSON.stringify(basis(main())) === JSON.stringify(state.main) && JSON.stringify(basis(form("splits"))) === JSON.stringify(state.splits), "another task changed original basis");
    state.stage = "inspect"; save(); items.querySelector("[data-subtask-current]").click(); return;
  }
  if (stage === "inspect") {
    check(document.querySelector("[data-review-current-record]") && !document.querySelector("[data-expenseitems-draft-scope]"), "current record restored a local task");
    check(value(form("items"), "item_name") === "后来明细", "inspection did not show current server rows");
    state.current_separate = true; state.stage = "return-original"; save();
    document.querySelector('a[href*="#expenseitems-edit-"]').click(); return;
  }
  if (stage === "return-original") {
    const items = form("items"); await ready(items);
    check(value(items, "item_name") === "原商品填写" && value(items, "expected_row_version") === "4", "inspection replaced original fields");
    state.stage = "replayed"; save(); submit(items); return;
  }
  if (stage === "replayed") {
    const splits = form("splits"); await ready(splits);
    check(value(form("items"), "item_name") === "后来明细" && value(main(), "merchant") === "原核对商家", "replay replaced peer facts or another draft");
    submit(splits); await pending(splits);
    check(splits.dataset.expensesplitsDraftPhase === "blocked", "stale split was not rejected");
    await post("role/viewer"); go("viewer"); return;
  }
  if (stage === "viewer") {
    const splits = form("splits"); await wait(() => splits.expenseReviewContinuity && value(splits, "split_note") === "原拆账填写", "readonly draft was not restored");
    check(button(splits).hidden && field(splits, "split_member_id")[0].disabled && JSON.stringify(basis(splits)) === JSON.stringify(state.splits), "revocation changed or enabled original");
    state.readonly_retained = true; await post("role/owner"); go("owner"); return;
  }
  if (stage === "owner") {
    const splits = form("splits"); await ready(splits);
    const review = splits.querySelector("[data-expensesplits-review]"); check(!review.hidden && !review.disabled, "known refusal cannot be explicitly reviewed");
    state.stage = "prepared"; save(); splits.requestSubmit(review); return;
  }
  if (stage === "prepared") {
    const splits = form("splits"); await ready(splits);
    check(value(splits, "expected_row_version") === "6" && value(splits, "idempotency_key") !== state.splits.idempotency_key &&
      value(splits, "draft_ref") === state.splits.draft_ref && value(splits, "split_note") === "原拆账填写", "explicit review lost input or failed to prepare a new command");
    state.reviewed_new_key = true;
    check(JSON.stringify(basis(main())) === JSON.stringify(state.main) && value(main(), "merchant") === "原核对商家", "review refreshed another original");
    state.other_original_preserved = true; state.stage = "saved"; save(); submit(splits); return;
  }
  if (stage === "saved") {
    await wait(() => main().expenseReviewContinuity && !field(main(), "merchant").readOnly, "main draft did not resume after subtask save");
    check(value(main(), "merchant") === "原核对商家", "successful subtask removed main input");
    go("shelf", "/web/pending?ledger_id=owner&filter=ready"); return;
  }
  check(stage === "shelf", "unexpected stage " + stage);
  await wait(() => window.TicketboxExpenseReview, "task shelf did not initialize");
  const links = [...document.querySelectorAll("[data-expensereview-scope] li a")];
  check(links.some(link => link.hash === "#expensereview-edit-" + state.main.draft_ref) &&
    !links.some(link => /#expense(items|splits)-edit-/.test(link.hash)), "shelf lost main original or retained consumed commands");
  state.shelf = true; window.__expenseReviewResult = state;
})().catch(error => { window.__expenseReviewResult = {error: String(error), stack: error.stack,
  state: JSON.parse(sessionStorage.getItem("subtask-runtime-probe") || "null")}; });
