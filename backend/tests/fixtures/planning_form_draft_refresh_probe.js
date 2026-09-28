(async () => {
  const results = [], pause = ms => new Promise(r => setTimeout(r, ms));
  const specs = [
    {kind:'budget', action:'/web/budgets/save', values:{total_amount_yuan:'009876',
      rollover_amount_yuan:'-0010', non_monthly_amount_yuan:'00200', excluded_categories:'原保留分类'},
      repeated:{category_budget_category:['原餐饮方案','原旅行方案','原学习方案'],
                category_budget_amount_yuan:['004000','003000','001000']}},
    {kind:'arrangement', action:'/web/budget-advise', values:{savings_target_yuan:'001200', reserved_buffer_yuan:'00030'}},
    {kind:'recurring-create', action:'/web/recurring/create', values:{merchant:'原创建方案',
      baseline_amount_yuan:'001500',next_expected_date:'2026-10-08'}},
    {kind:'recurring-edit', action:'/web/recurring/series-one/edit', values:{merchant:'原编辑方案',
      baseline_amount_yuan:'001800',next_expected_date:'2026-10-09'}}
  ];
  const read = f => [...new FormData(f).entries()].filter(([n])=>n!=='csrf_token').map(([n,v])=>
    [n,n==='draft_scope' ? JSON.stringify(Object.entries(JSON.parse(v)).sort(([a],[b])=>a.localeCompare(b))) : v]);
  const load = async (frame,url) => {
    const loaded = new Promise(r=>frame.onload=r); frame.src=url; await loaded; await pause(150);
  };
  for (const spec of specs) {
    const frame = document.createElement('iframe'); document.body.append(frame);
    const url = '/fixture?kind='+spec.kind;
    await load(frame,url);
    let f = frame.contentDocument.querySelector('form[method="post"][action="'+spec.action+'"]');
    if (!f) throw Error('real form not found: '+spec.kind);
    const set = (input,value) => {input.value=value; input.dispatchEvent(new frame.contentWindow.Event('input',{bubbles:true}));};
    for (const [n,v] of Object.entries(spec.values)) set(f.elements.namedItem(n),v);
    for (const [n,vs] of Object.entries(spec.repeated || {})) {
      const inputs=[...f.querySelectorAll('[name="'+n+'"]')];
      if (inputs.length < vs.length) throw Error('missing real category rows');
      vs.forEach((v,i)=>set(inputs[i],v));
    }
    if (spec.kind==='budget') for (const n of ['excluded_category','category_budget_remove']) {
      const input=f.querySelector('[name="'+n+'"]'); input.checked=true;
      input.dispatchEvent(new frame.contentWindow.Event('change',{bubbles:true}));
    }
    await pause(150); const before=read(f);
    await load(frame,url);
    f=frame.contentDocument.querySelector('form[method="post"][action="'+spec.action+'"]');
    const after=read(f);
    results.push({entry:spec.kind,before,after,retained:JSON.stringify(before)===JSON.stringify(after)});
    frame.remove();
  }
  window.__planningPreflight={results};
})().catch(e=>window.__planningPreflight={error:String(e),stack:e.stack});
