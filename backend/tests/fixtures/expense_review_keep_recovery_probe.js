/* A non-duplicate decision survives a lost reply/reload without consuming the financial draft. */
(async function () {
  "use strict";
  const key="expense-keep-recovery-probe", prefix="ticketbox:expensereview-edit-draft:v1:";
  const query=new URL(location.href).searchParams;
  const state=JSON.parse(sessionStorage.getItem(key)||"null") || {stage:"edit",entry:query.get("entry"),fault:query.get("fault"),requests:[]};
  const save=()=>sessionStorage.setItem(key,JSON.stringify(state));
  const assert=(value,message)=>{if(!value)throw Error(message);};
  const wait=async predicate=>{for(let n=0;n<200;n++){if(predicate())return;await new Promise(resolve=>setTimeout(resolve,25));}throw Error("keep recovery stalled at "+state.stage);};
  const form=()=>document.querySelector("form[data-expensereview-plan-id]");
  const primary=()=>form()?.querySelector("[data-expensereview-submit]");
  const originalFetch=window.fetch;
  const originalSet=Storage.prototype.setItem;
  Storage.prototype.setItem=function(name,value){
    if(this===localStorage && name===prefix+state.ref && state.fault==="ack-store" && !state.storeFailed && state.stage==="started" && JSON.parse(value).phase==="editing"){
      state.storeFailed=true;save();throw new DOMException("cannot retain accepted continuation","QuotaExceededError");
    }
    return originalSet.call(this,name,value);
  };
  window.fetch=async(url,options)=>{
    if(!new URL(url,location.href).pathname.endsWith("/keep"))return originalFetch(url,options);
    state.requests.push([...options.body].filter(([name])=>name!=="csrf_token"));save();
    const response=await originalFetch(url,options);
    if(state.fault==="rejected"){
      assert(response.status===409 && (await response.clone().json()).draft_result==="rejected", "known conflict was not identified as rejected");
      state.rejected=true;save();return response;
    }
    if(state.fault!=="ack-store" && !state.lost){assert(response.ok,"first decision was not accepted");await response.text();state.lost=true;save();throw new TypeError("accepted keep reply lost");}
    return response;
  };
  async function afterReplay(){
    await wait(()=>form()?.dataset.expensereviewDraftPhase==="editing" && !form().elements.merchant.readOnly);
    const record=JSON.parse(localStorage.getItem(prefix+state.ref));
    assert(record?.phase==="editing" && record.values.merchant==="非重复前的原填写" && record.values.idempotency_key===state.confirmKey,
      "accepted related decision consumed the financial draft");
    const current=await (await originalFetch("/keep-current")).json();
    const laterDuplicate=state.entry==="drawer" && state.fault==="reply" ? "none" : "suspected";
    assert(current.version===9 && current.duplicate===laterDuplicate && current.merchant==="后来填写", "original replay overwrote later state");
    assert(primary().disabled,"original draft was silently rebased");
    state.original_preserved=true;state.stage="reviewed";save();
    form().requestSubmit(form().querySelector("[data-expensereview-review]"));
  }
  async function startOriginalDecision(){
    await wait(()=>!primary().disabled && !form().elements.merchant.readOnly);
    form().elements.merchant.value="非重复前的原填写";form().elements.merchant.dispatchEvent(new Event("input",{bubbles:true}));
    state.ref=form().elements.draft_ref.value;state.confirmKey=form().elements.idempotency_key.value;state.keepKey=form().elements.keep_idempotency_key.value;
    if(state.fault==="rejected")await originalFetch("/keep-later",{method:"POST"});
    state.stage="started";save();form().querySelector('.review-more-actions summary')?.click();
    form().querySelector('button[formaction$="/keep"]').click();
    await wait(()=>state.storeFailed || ((state.lost || state.rejected) && !primary().disabled));
    const original=JSON.parse(localStorage.getItem(prefix+state.ref));
    assert(original.phase===(state.rejected?"blocked":"submitted") && original.values.command_action==="keep", "keep decision has no durable original");
    if(state.rejected)assert(original.serverResult==="rejected", "known rejection was not retained for explicit review");
    assert(primary().textContent==="核实这次非重复决定", "unknown keep decision has no recovery action");
    if(!state.rejected)await originalFetch("/keep-later",{method:"POST"});
    state.stage="reloaded";save();location.reload();return;
  }
  async function replayOriginalDecision(){
    await wait(()=>!primary().disabled && primary().textContent==="核实这次非重复决定");
    assert(form().elements.merchant.value==="非重复前的原填写" && form().elements.expected_row_version.value==="4" &&
      form().elements.keep_idempotency_key.value===state.keepKey && form().elements.idempotency_key.value===state.confirmKey, "reload replaced the original intent");
    assert(form().elements.merchant.readOnly && primary().textContent==="核实这次非重复决定", "reload lost the frozen original decision");
    if(state.rejected){
      const review=form().querySelector("[data-expensereview-review]");
      assert(!review.hidden && !review.disabled, "known rejection cannot rejoin explicit review");
      state.original_preserved=true;state.stage="reviewed";save();form().requestSubmit(review);return;
    }
    state.stage="replayed";save();primary().click();
    if(state.entry==="full")return;
    await afterReplay();
  }
  try{
    if(document.querySelector("[data-expense-confirmation]")){
      state.confirmed=document.body.textContent.includes("非重复前的原填写");window.__expenseReviewResult=state;return;
    }
    if(location.pathname==="/web/pending"){
      await wait(()=>window.TicketboxWeb?.drawerApi);
      if(state.stage==="edit")document.querySelector('.exp-row[data-expense-id="42"] .exp-row-detail').click();
    }
    await wait(()=>form()?.dataset.expensereviewDraftPhase);
    if(state.stage==="edit"){
      await startOriginalDecision(); return;
    }
    if(state.stage==="started")throw Error("full keep navigated away without retaining its pending decision");
    if(state.stage==="reloaded"){
      await replayOriginalDecision();
    }else if(state.stage==="replayed")await afterReplay();
    else if(state.stage==="reviewed"){
      await wait(()=>!primary().disabled && !form().elements.merchant.readOnly);
      assert(form().elements.expected_row_version.value==="9" && form().elements.merchant.value==="非重复前的原填写", "explicit review failed to preserve the draft");
      assert(form().elements.idempotency_key.value!==state.confirmKey && form().elements.keep_idempotency_key.value!==state.keepKey &&
        form().elements.command_action.value==="confirm", "explicit review did not prepare a new financial command");
      state.stage="confirmed";save();primary().click();
    }
  }catch(error){window.__expenseReviewResult={...state,error:String(error)};}
})();
