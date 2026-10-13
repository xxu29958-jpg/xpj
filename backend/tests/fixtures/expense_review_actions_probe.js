/* Real related actions return to the original fields; explicit review rebases before confirm. */
(async function () {
  "use strict";
  const stateKey = "expense-actions-probe", prefix = "ticketbox:expensereview-edit-draft:v1:";
  const params = new URL(location.href).searchParams;
  const state = JSON.parse(sessionStorage.getItem(stateKey) || "null") || {stage:"edit", action:params.get("probe"), entry:params.get("entry") || "drawer"};
  const save = () => sessionStorage.setItem(stateKey, JSON.stringify(state));
  const assert = (ok, message) => { if (!ok) throw Error(message); };
  const wait = async predicate => {
    for (let n=0; n<200; n+=1) { if (predicate()) return; await new Promise(resolve => setTimeout(resolve,25)); }
    throw Error("related action did not reach " + state.stage);
  };
  const form = () => document.querySelector("form[data-expensereview-plan-id]");
  const primary = () => form()?.querySelector("[data-expensereview-submit]");
  let commandPosts=0;
  const originalFetch=window.fetch;
  window.fetch=(url, options)=>{
    if (options?.method === "POST" && /\/(save|confirm)$/.test(new URL(url,location.href).pathname)) commandPosts+=1;
    if (options?.method === "POST" && /\/keep$/.test(new URL(url,location.href).pathname) && state.entry==="drawer" && !state.keep_reply_lost) {
      return originalFetch(url,options).then(async response=>{
        assert(response.ok, "non-duplicate decision was not accepted before reply loss");
        await response.text(); state.keep_reply_lost=true; save();
        throw new TypeError("probe drops the accepted non-duplicate reply");
      });
    }
    return originalFetch(url,options);
  };
  async function reviewOriginal() {
    await wait(() => form()?.dataset.expensereviewDraftPhase === "editing" && !form().elements.merchant.readOnly);
    state.input_retained = form().elements.merchant.value === "相关操作前的填写" && form().elements.idempotency_key.value === state.key;
    assert(state.input_retained, "related action discarded the original input: " + JSON.stringify({merchant:form().elements.merchant.value,key:form().elements.idempotency_key.value,notice:form().querySelector("[data-expensereview-draft-status]").textContent,hash:location.hash}));
    assert(primary().disabled && !form().querySelector("[data-expensereview-review]").disabled, "stale original could be confirmed without reviewing the updated bill");
    assert([...form().querySelectorAll('button[type="submit"]')].find(button=>button.textContent==="保存草稿").disabled, "stale original still offers save before review");
    const before=commandPosts;
    form().dispatchEvent(new SubmitEvent("submit", {bubbles:true,cancelable:true}));
    assert(commandPosts===before, "implicit submit sent the stale original before explicit review");
    state.stage="reviewed"; save(); form().requestSubmit(form().querySelector("[data-expensereview-review]"));
  }
  async function beginRelatedAction() {
    await wait(() => !primary().disabled);
    if (state.legacy_edit_seeded) {
      state.legacy_edit_restored=form().elements.merchant.value==="相关操作前的填写" &&
        form().elements.idempotency_key.value===state.key && !!form().elements.keep_idempotency_key.value;
      assert(state.legacy_edit_restored, "older editable draft cannot use the newly connected related decision");
    }
    form().elements.merchant.value="相关操作前的填写";
    form().elements.merchant.dispatchEvent(new Event("input",{bubbles:true}));
    state.ref=form().elements.draft_ref.value; state.key=form().elements.idempotency_key.value;
    if (state.action==="keep" && state.entry==="full" && !state.legacy_edit_seeded) {
      const record=JSON.parse(localStorage.getItem(prefix+state.ref));
      const laterFields=["command_action", "keep_idempotency_key", "reject_idempotency_key"];
      laterFields.forEach(name=>delete record.values[name]);
      record.values.present_fields=JSON.stringify(JSON.parse(record.values.present_fields).filter(name=>!laterFields.includes(name)));
      localStorage.setItem(prefix+state.ref,JSON.stringify(record));
      state.legacy_edit_seeded=true; save(); location.reload(); return;
    }
    const button=form().querySelector('button[formaction$="/'+(state.action==="keep"?"keep":"reject")+'"]');
    assert(button, "related action missing");
    form().querySelector('.review-more-actions summary')?.click();
    assert(button.checkVisibility(), "related action cannot be reached from the actual menu");
    if (state.action==="reject") {
      state.stage="rejected"; save(); button.click();
      await wait(() => document.querySelector("#tb-confirm-modal[open]"));
      document.querySelector("#tb-confirm-modal .tb-confirm-ok").click(); return;
    }
    state.stage="kept"; save(); const before=form(); button.click();
    if (state.entry==="full") return;
    await wait(() => form().dataset.expensereviewDraftPhase==="submitted" && !primary().disabled);
    assert(form().querySelector('[data-expensereview-recovery] h1').textContent==="正在核实这次非重复决定",
      "lost reply did not retain the related operation");
    assert(form()===before && form().elements.merchant.value==="相关操作前的填写" && form().elements.idempotency_key.value===state.key,
      "lost related-action reply discarded the original input");
    state.unknown_retained=true; save(); primary().click();
    await wait(() => form() !== before && form()?.dataset.expensereviewDraftPhase);
    await wait(() => !document.querySelector('.exp-row[data-expense-id="42"]'));
    assert(document.querySelector('.filter-tab.is-active .count').textContent==="0", "duplicate count stayed stale");
    assert(!document.querySelector('nav a[href^="/web/duplicates"] > .nav-badge'), "navigation still reports the cleared duplicate");
    assert(!document.querySelector('.filter-tab .nav-badge'), "queue filters acquired a second navigation count");
    assert(document.querySelector('nav a[href^="/web/pending"] > .nav-badge').textContent==="1", "clearing duplicate incorrectly removed the pending bill");
    await reviewOriginal();
  }
  try {
    if (state.stage === "confirm") {
      await wait(() => document.querySelector("[data-expense-confirmation]"));
      state.confirmed = document.querySelector("[data-expense-confirmation]").textContent.includes("相关操作前的填写");
      window.__expenseReviewResult=state; return;
    }
    if (state.stage === "rejected") {
      const url=new URL(location.href);
      assert(url.searchParams.get("filter")==="ready", "ignore lost the original filter");
      assert(JSON.parse(localStorage.getItem(prefix+state.ref)).values.merchant==="相关操作前的填写", "ignore dropped unsaved input");
      const undo=document.querySelector('.undo-banner-action[action$="/undo"]');
      assert(undo, "accepted ignore has no undo entry");
      state.stage="undone"; save(); undo.querySelector('button[type="submit"]').click(); return;
    }
    if (state.stage === "undone") assert(new URL(location.href).searchParams.get("filter")==="ready", "undo lost the original filter");
    if (location.pathname === "/web/pending") {
      await wait(() => window.TicketboxWeb?.drawerApi);
      document.querySelector('.exp-row[data-expense-id="42"] .exp-row-detail').click();
    }
    await wait(() => form()?.dataset.expensereviewDraftPhase);
    if (state.stage === "edit") {
      await beginRelatedAction();
    } else if (state.stage==="undone" || (state.stage==="kept" && state.entry==="full")) await reviewOriginal();
    else if (state.stage==="reviewed") {
      await wait(() => !primary().disabled);
      assert(form().elements.merchant.value==="相关操作前的填写", "review overwrote input");
      assert(form().elements.expected_row_version.value===(state.action==="keep"?"5":"6"), "review used stale basis");
      state.reviewed=true; state.stage="confirm"; save(); form().requestSubmit(primary());
    }
  } catch (error) { window.__expenseReviewResult={...state,error:String(error)}; }
})();
