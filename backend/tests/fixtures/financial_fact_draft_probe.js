(async () => {
  const frame = document.createElement("iframe"); document.body.append(frame);
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  const load = async () => {
    const loaded = new Promise(resolve => { frame.onload = resolve; });
    frame.src = "/web/expenses/7/correct?ledger_id=owner"; await loaded;
    for (let n = 0; n < 160; n++) {
      const form = frame.contentDocument.querySelector(".correction-form");
      if (form && !form.querySelector('[type="submit"]').disabled) return form;
      await pause(25);
    }
    throw Error("Correction input did not become available: " + frame.contentDocument.querySelector('[data-correction-draft-status]')?.textContent);
  };
  const read = form => [...new FormData(form)].filter(([name]) => name !== "csrf_token").map(([name, value]) =>
    [name, name === "draft_scope" ? JSON.stringify(Object.entries(JSON.parse(value)).sort(([a], [b]) => a.localeCompare(b))) : value]);
  let form = await load();
  for (const [name, value] of Object.entries({reason: " 原更正依据 ", merchant: "原稿商家", amount_yuan: "0005.50",
      note: "原备注\n第二行", value_score: "4", regret_score: ""})) {
    form.elements.namedItem(name).value = value;
    form.dispatchEvent(new frame.contentWindow.Event("input", {bubbles: true}));
  }
  for (const [name, value] of Object.entries({item_name: "原商品修改", split_note: "原拆账输入"})) {
    form.querySelector('[name="' + name + '"]').value = value;
    form.dispatchEvent(new frame.contentWindow.Event("input", {bubbles: true}));
  }
  const before = read(form);
  form = await load();
  window.__financialDraftProbe = {before, after: read(form)};
})().catch(error => { window.__financialDraftProbe = {error: String(error), stack: error.stack}; });
