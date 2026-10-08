(async () => {
  const results = [], pause = ms => new Promise(r => setTimeout(r, ms));
  async function until(check, label) {
    for (let n=0; n<160; n++) { if (check()) return; await pause(25); }
    throw Error(label);
  }
  async function load(frame, url) {
    const ready = new Promise(resolve => frame.onload=resolve); frame.src=url; await ready;
  }
  const specs = [
    {kind:"budget", family:"budget", action:"/web/budgets/save", fields:{total_amount_yuan:"009876", rollover_amount_yuan:"-0020", non_monthly_amount_yuan:"0050"}},
    {kind:"arrangement", family:"arrangement", action:"/web/budget-advise", fields:{savings_target_yuan:"001200", reserved_buffer_yuan:"00030"}},
    {kind:"recurring-create", family:"recurring", action:"/web/recurring/create", fields:{merchant:"原创建方案",baseline_amount_yuan:"001500",next_expected_date:"2026-10-08"}},
    {kind:"recurring-edit", family:"recurring", action:"/web/recurring/series-one/edit", fields:{merchant:"原编辑方案",baseline_amount_yuan:"001800",next_expected_date:"2026-10-09"}},
    {kind:"tag-create", family:"tagcreation", action:"/web/reference/tag/create", fields:{name:"  原标签添加  "}},
    {kind:"category-create", family:"categorycreation", action:"/web/reference/category/create", fields:{name:"  原分类添加  "}},
    {kind:"merchant-create", family:"catalogcreation", action:"/web/merchants/catalog/create", fields:{display_name:"  原商家添加  "}},
    {kind:"alias-create", family:"aliascreation", action:"/web/merchants/aliases/create", fields:{canonical_merchant:"  原标准商家  ",alias:"  原别名添加  "}},
    {kind:"catalog-rename", family:"catalogrename", action:"/web/merchants/catalog/merchant-original/rename", fields:{display_name:"  原商家改名  "}},
    {kind:"catalog-toggle", family:"catalogtoggle", action:"/web/merchants/catalog/merchant-original/toggle", fields:{next_status:"hidden"}},
    {kind:"catalog-delete", family:"catalogdelete", action:"/web/merchants/catalog/merchant-original/delete", fields:{}},
    {kind:"catalog-merge", family:"catalogmerge", action:"/web/merchants/catalog/merchant-original/merge", fields:{target:"merchant-target:1",alias_policy:"create_source_alias"}},
    {kind:"rule-create", family:"ruledefinition", action:"/web/rules/create", fields:{keyword:"  原规则创建  ",category:"家庭餐饮",priority:"10",amount_min_yuan:"001200",source_contains:"  原来源  ",tag_contains:"  原标签  "}},
    {kind:"rule-edit", family:"ruledefinition", action:"/web/rules/41/edit", fields:{keyword:"  原规则编辑  ",category:"家庭交通",priority:"20",amount_min_yuan:"001500",source_contains:"",tag_contains:""}},
  ];
  for (const spec of specs) {
    const frame=document.createElement("iframe"); document.body.append(frame);
    const url="/fixture?kind="+spec.kind;
    const getForm=()=>frame.contentDocument.querySelector('form[method="post"][action="'+spec.action+'"]');
    const submit=form=>form.querySelector("[data-"+spec.family+"-submit]");
    await load(frame,url); await until(()=>getForm() && !submit(getForm()).disabled,"draft lease unavailable");
    let form=getForm();
    for (const [name,value] of Object.entries(spec.fields)) {
      const input=form.elements.namedItem(name); input.value=value;
      input.dispatchEvent(new frame.contentWindow.Event("input",{bubbles:true}));
    }
    if (spec.kind==="budget") {
      form.querySelectorAll('[name="excluded_category"]').forEach(input=>{input.checked=true;});
      form.querySelector('[name="category_budget_remove"]').checked=true;
      form.dispatchEvent(new frame.contentWindow.Event("change",{bubbles:true}));
    }
    const ref=form.elements.namedItem("idempotency_key").value;
    if (spec.kind === "catalog-delete") form.dispatchEvent(new frame.contentWindow.Event("change",{bubbles:true}));
    const storageRef=form.elements.namedItem("draft_ref")?.value || ref;
    const storageKey=Object.keys(localStorage).find(key=>key.endsWith(storageRef));
    if (!storageKey) throw Error("Original draft not retained");
    form.requestSubmit(submit(form));
    await until(()=>form.dataset[spec.family+"DraftPhase"]==="blocked" && !submit(form).disabled,"unknown receipt did not retain original");
    if (!form.querySelector("[data-"+spec.family+"-review]").hidden) throw Error("Unknown original must not offer a replacement key");
    const original=JSON.parse(localStorage.getItem(storageKey));
    await load(frame,url); await until(()=>getForm() && !submit(getForm()).disabled,"reopened original unavailable");
    form=getForm();
    const frozen=Object.keys(spec.fields).every(name=>form.elements.namedItem(name).readOnly || form.elements.namedItem(name).disabled);
    if (form.elements.namedItem("idempotency_key").value!==ref || JSON.stringify(JSON.parse(localStorage.getItem(storageKey)).values)!==JSON.stringify(original.values)) {
      throw Error("Reopening changed the original body: " + JSON.stringify({entry: spec.kind,
        originalRef: ref, reopenedRef: form.elements.namedItem("idempotency_key").value,
        before: original.values, after: JSON.parse(localStorage.getItem(storageKey)).values}));
    }
    form.requestSubmit(submit(form));
    await until(()=>frame.contentDocument.querySelector("[data-confirmed]"),"matching original receipt was not acknowledged");
    results.push({entry:spec.kind,confirmed:true,originalRemoved:localStorage.getItem(storageKey)===null,frozen});
    frame.remove();
  }
  window.__planningRecovery={results};
})().catch(error=>window.__planningRecovery={error:String(error),stack:error.stack});
