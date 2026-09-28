(async () => {
  const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  async function until(check,label) {
    for(let n=0;n<160;n++){if(check())return;await pause(25);}throw Error(label);
  }
  const frame=document.createElement("iframe");document.body.append(frame);
  const getForm=()=>frame.contentDocument?.querySelector('form[method="post"][action="/web/budget-advise"]');
  const save=()=>getForm()?.querySelector("[data-arrangement-submit]");
  const ready=()=>getForm()?.dataset.arrangementDraftPhase && save() && !save().disabled;
  frame.src="/fixture?kind=arrangement";
  await until(ready,"editor unavailable");
  for(const [name,value] of Object.entries({savings_target_yuan:"001200",reserved_buffer_yuan:"00030"})){
    const input=getForm().elements.namedItem(name);input.value=value;
    input.dispatchEvent(new frame.contentWindow.Event("input",{bubbles:true}));
  }
  const ref=getForm().elements.namedItem("idempotency_key").value;
  const key=Object.keys(localStorage).find(name=>name.endsWith(ref));
  const beforeTrial=frame.contentDocument;
  getForm().requestSubmit(getForm().querySelector("[data-plan-preview]"));
  await until(()=>frame.contentDocument!==beforeTrial && ready(),"trial did not return original input");
  if(getForm().dataset.arrangementDraftPhase!=="editing" || JSON.parse(localStorage.getItem(key)).phase!=="editing")throw Error("Trial submitted a financial intent");
  getForm().requestSubmit(save());
  await until(()=>getForm().dataset.arrangementDraftPhase==="blocked" && !save().disabled,"refusal not retained");
  const review=getForm().querySelector("[data-arrangement-review]");
  if(review.hidden)throw Error("Explicitly rejected proposal cannot be reviewed");
  const beforeReview=frame.contentDocument;
  getForm().requestSubmit(review);
  await until(()=>frame.contentDocument!==beforeReview && ready(),"review did not prepare input");
  if(getForm().dataset.arrangementDraftPhase!=="editing" || getForm().elements.namedItem("expected_row_version").value!=="4")throw Error("Rejected proposal was not re-opened after explicit review");
  const prepared=JSON.parse(localStorage.getItem(key));
  if(prepared.values.savings_target_yuan!=="001200" || prepared.values.reserved_buffer_yuan!=="00030")throw Error("Review changed original amounts");
  getForm().requestSubmit(save());
  await until(()=>frame.contentDocument.querySelector("[data-confirmed]"),"reviewed arrangement did not confirm");
  window.__planningReview={ref,confirmed:true,originalRemoved:localStorage.getItem(key)===null};
})().catch(error=>window.__planningReview={error:String(error),stack:error.stack});
