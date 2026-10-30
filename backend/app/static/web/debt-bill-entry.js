/* A new debt's original bill: the retained source, parse and discard stay with their server owners.
   Each key enters the debt draft before it is sent, so a lost reply is read back, never guessed. */
(function (window, document) {
  "use strict";
  const KEYS = ["bill_source_public_id", "bill_source_row_version", "bill_capture_key", "bill_parse_key",
    "bill_discard_key", "bill_file_name"];
  const views = new WeakMap();
  const field = (form, name) => form.elements.namedItem(name);
  const values = form => Object.fromEntries(KEYS.map(name => [name, field(form, name)?.value || ""]));
  const uuid = () => window.crypto.randomUUID();

  function view(form) {
    const root = form.querySelector("[data-debtbill]");
    if (!root) return null;
    if (!views.has(form)) views.set(form, {root, editable: false, busy: false, outcome: null, source: null});
    return views.get(form);
  }
  function say(form, text) { form.querySelector("[data-debtbill-status]").textContent = text; }
  // A change counts only once the draft store holds it; a key a reload cannot find is never sent.
  function retain(form, changes) {
    const names = Object.keys(changes);
    names.forEach(name => { field(form, name).value = changes[name]; });
    if (names.length) field(form, names[0]).dispatchEvent(new Event("input", {bubbles: true}));
    try {
      const raw = window.localStorage.getItem("ticketbox:debtcreation-create-draft:v1:" + field(form, "idempotency_key").value);
      const record = raw && JSON.parse(raw);
      return Boolean(record) && names.every(name => record.values?.[name] === changes[name]);
    } catch (_) { return false; }
  }
  async function call(form, path, options = {}) {
    const headers = {Accept: "application/json", "X-CSRF-Token": field(form, "csrf_token").value};
    if (options.json) headers["Content-Type"] = "application/json";
    const response = await window.fetch(path, {method: options.json || options.body ? "POST" : "GET", credentials: "same-origin",
      headers, body: options.json ? JSON.stringify(options.json) : options.body});
    let body = null;
    try { body = await response.json(); } catch (_) { body = null; }
    return {ok: response.ok, status: response.status, body};
  }
  function ledgerQuery(form) { return "?ledger_id=" + encodeURIComponent(field(form, "ledger_id").value); }
  function command(form, key) {
    return {ledger_id: field(form, "ledger_id").value, draft_scope: field(form, "draft_scope").value,
      idempotency_key: key, expected_row_version: Number(field(form, "bill_source_row_version").value)};
  }
  function refusal(response, fallback) { return response.body?.message || fallback; }

  async function capture(form, file) {
    const state = view(form);
    if (!state.editable || state.busy || values(form).bill_source_public_id) return;
    const key = uuid();
    if (!retain(form, {bill_capture_key: key, bill_file_name: file.name})) {
      retain(form, {bill_capture_key: "", bill_file_name: ""});
      say(form, "原稿暂时未能保留，没有发送原账单；请稍后再选择图片。");
      return;
    }
    const body = new window.FormData();
    body.set("file", file); body.set("ledger_id", field(form, "ledger_id").value);
    body.set("draft_scope", field(form, "draft_scope").value); body.set("creation_key", field(form, "idempotency_key").value);
    body.set("idempotency_key", key); body.set("csrf_token", field(form, "csrf_token").value);
    await busy(form, "正在保存原账单…", async () => {
      let response;
      try { response = await call(form, "/web/debt-bills", {body}); } catch (_) { response = null; }
      if (response && !response.ok && response.status < 500) {
        retain(form, {bill_capture_key: "", bill_file_name: ""});
        say(form, "原账单没有保存：" + refusal(response, "请换一张图片再试。")); return;
      }
      if (response?.ok) await adopt(form, response.body);
      else await resumeCapture(form);
    });
  }
  async function adopt(form, source) {
    retain(form, {bill_source_public_id: source.public_id, bill_source_row_version: String(source.row_version), bill_capture_key: ""});
    view(form).source = source;
    render(form);
    await parse(form);
  }
  async function resumeCapture(form) {
    const key = values(form).bill_capture_key;
    let response;
    try { response = await call(form, "/web/debt-bills/by-key/" + encodeURIComponent(key) + ledgerQuery(form)); } catch (_) { response = null; }
    if (response?.ok) { await adopt(form, response.body); return; }
    if (response?.status === 404) {
      retain(form, {bill_capture_key: "", bill_file_name: ""});
      say(form, "原账单没有保存成功，请重新选择图片。");
    } else say(form, "暂时无法确认原账单是否已保存；原稿已保留，回到此页会继续核对。");
    render(form);
  }

  async function parse(form) {
    const current = values(form);
    if (!current.bill_source_public_id || !view(form).editable) return;
    const key = current.bill_parse_key || uuid();
    if (!retain(form, {bill_parse_key: key})) { say(form, "原稿暂时未能保留，没有发送解析请求；请稍后再试。"); return; }
    const path = "/web/debt-bills/" + encodeURIComponent(current.bill_source_public_id);
    let response;
    try { response = await call(form, path + "/parse", {json: command(form, key)}); } catch (_) { response = null; }
    if (!response || response.status >= 500) {
      try { response = await call(form, path + "/parse-attempts/" + encodeURIComponent(key) + ledgerQuery(form)); } catch (_) { response = null; }
      if (!response?.ok) {
        say(form, "暂时无法确认识别结果；原账单已保存，可稍后点“解析原账单建议”继续原请求。");
        render(form); return;
      }
    }
    if (!response.ok) {
      retain(form, {bill_parse_key: ""});
      if (response.status === 409) await adoptLatest(form);
      say(form, "这次没有解析：" + refusal(response, "原账单刚有变化，请再试一次。"));
      render(form); return;
    }
    retain(form, {bill_source_row_version: String(response.body.row_version), bill_parse_key: ""});
    view(form).outcome = response.body;
    say(form, suggest(form, response.body));
    render(form);
  }
  // Suggestions only fill what the person left blank; the form stays theirs to check before saving.
  function suggest(form, outcome) {
    const suggestion = outcome.suggestion;
    if (outcome.status !== "succeeded" || !suggestion) return "原件已保存，建议暂不可用；可按原图手填后提交。";
    const filled = [];
    const fill = (name, value) => {
      const input = field(form, name);
      if (!input || input.value.trim() || value === null || value === undefined || value === "") return;
      input.value = String(value); input.dispatchEvent(new Event("input", {bubbles: true})); filled.push(name);
    };
    fill("counterparty_label", suggestion.merchant?.trim());
    // The provider reports CNY fen; another currency is left for the person rather than guessed.
    if (field(form, "currency_code").value === "CNY" && Number.isSafeInteger(suggestion.principal_amount_cents)) {
      const fen = String(suggestion.principal_amount_cents).padStart(3, "0");
      fill("amount_major", fen.slice(0, -2) + "." + fen.slice(-2));
    }
    fill("installment_count", suggestion.installment_count);
    fill("installment_period_months", suggestion.installment_period_months);
    if (filled.includes("installment_count") && field(form, "debt_kind").value === "one_off") {
      field(form, "debt_kind").value = "installment";
      field(form, "debt_kind").dispatchEvent(new Event("change", {bubbles: true}));
    }
    return filled.length ? "已按原账单建议补全空白项，请核对后提交。" : "原件已保存；建议没有可补全的空白项，请对照原图核对。";
  }

  async function discard(form) {
    const current = values(form);
    if (!current.bill_source_public_id || !view(form).editable) return;
    const key = current.bill_discard_key || uuid();
    if (!retain(form, {bill_discard_key: key})) { say(form, "原稿暂时未能保留，没有放弃这张账单；请稍后再试。"); return; }
    await busy(form, "正在放弃这张账单…", async () => {
      const path = "/web/debt-bills/" + encodeURIComponent(current.bill_source_public_id);
      let response;
      try { response = await call(form, path + "/discard", {json: command(form, key)}); } catch (_) { response = null; }
      if (!response || response.status >= 500) response = await refresh(form);
      if (response?.ok && response.body.status === "rejected") {
        retain(form, Object.fromEntries(KEYS.map(name => [name, ""])));
        view(form).source = null; view(form).outcome = null;
        say(form, "已不用这张账单；原件按保留设置另存，不会关联这笔往来。");
      } else if (response && response.status < 500 && !response.ok) {
        retain(form, {bill_discard_key: ""});
        if (response.status === 409) await adoptLatest(form);
        say(form, "这次没有放弃：" + refusal(response, "请刷新后再试。"));
      } else say(form, "暂时无法确认是否已放弃这张账单；原稿已保留，可再点一次继续原请求。");
      render(form);
    });
  }
  // A newer explicit action uses the source's current version; a replay keeps the original one.
  async function adoptLatest(form) {
    const response = await refresh(form);
    if (response?.ok) retain(form, {bill_source_row_version: String(response.body.row_version)});
  }
  async function refresh(form) {
    const id = values(form).bill_source_public_id;
    let response;
    try { response = await call(form, "/web/debt-bills/" + encodeURIComponent(id) + ledgerQuery(form)); } catch (_) { return null; }
    if (response.ok) view(form).source = response.body;
    return response;
  }

  async function busy(form, text, task) {
    const state = view(form);
    state.busy = true; say(form, text); render(form);
    try { await task(); } finally { state.busy = false; render(form); }
  }
  function render(form) {
    const state = view(form);
    if (!state) return;
    const current = values(form), source = state.source, outcome = state.outcome || source?.parse_outcome;
    const has = Boolean(current.bill_source_public_id), pending = Boolean(current.bill_capture_key);
    const usable = state.editable && !state.busy;
    form.querySelector("[data-debtbill-picker]").hidden = has || pending;
    form.querySelector("[data-debtbill-file]").disabled = !usable;
    form.querySelector("[data-debtbill-source]").hidden = !has && !pending;
    form.querySelector("[data-debtbill-file-name]").textContent = source?.file_name || current.bill_file_name ||
      (has ? "原账单已保存" : "");
    form.querySelector("[data-debtbill-actions]").hidden = !has;
    const original = form.querySelector("[data-debtbill-original]");
    original.hidden = !has;
    if (has) original.href = "/web/debt-bills/" + encodeURIComponent(current.bill_source_public_id) + "/original" + ledgerQuery(form);
    const parseButton = form.querySelector("[data-debtbill-parse]");
    parseButton.hidden = !has || outcome?.status === "succeeded";
    parseButton.disabled = !usable;
    form.querySelector("[data-debtbill-discard]").disabled = !usable;
  }
  // Restored drafts and native round trips both arrive here: read back what the page cannot know.
  async function resume(form) {
    const current = values(form), state = view(form);
    if (current.bill_capture_key && !current.bill_source_public_id) { await resumeCapture(form); return; }
    if (!current.bill_source_public_id) { render(form); return; }
    const response = await refresh(form);
    if (response && !response.ok && response.status < 500) {
      say(form, "这张原账单当前不可用：" + refusal(response, "可选择其他图片或手填。"));
    } else if (state.source?.status === "rejected") {
      if (state.editable) {
        retain(form, Object.fromEntries(KEYS.map(name => [name, ""])));
        state.source = null;
      }
      say(form, "这张账单已放弃，不会关联这笔往来。");
    } else if (state.source?.adopted_debt_public_id) say(form, "这张原账单已用于一笔往来。");
    else if (current.bill_parse_key && state.editable) { await parse(form); return; }
    else if (state.source?.parse_outcome) say(form, state.source.parse_outcome.status === "succeeded"
      ? "原件已保存。建议仅供填写参考，提交前请核对。" : "原件已保存，建议暂不可用；可按原图手填后提交。");
    render(form);
  }

  window.TicketboxDebtBill = {
    present(form) { if (view(form)) resume(form); },
    update(form, editable) {
      const state = view(form);
      if (!state) return;
      const opened = editable && !state.editable;
      state.editable = editable;
      render(form);
      if (opened && values(form).bill_parse_key) resume(form);
    },
  };
  document.querySelectorAll("form[data-debtcreation-draft-scope]").forEach(form => {
    const state = view(form);
    if (!state) return;
    state.root.hidden = false;
    form.querySelector("[data-debtbill-file]").addEventListener("change", event => {
      const file = event.target.files?.[0];
      event.target.value = "";
      if (file) capture(form, file);
    });
    form.querySelector("[data-debtbill-parse]").addEventListener("click", () => {
      if (!view(form).busy) busy(form, "正在识别原账单…", () => parse(form));
    });
    form.querySelector("[data-debtbill-discard]").addEventListener("click", () => discard(form));
    render(form);
    if (values(form).bill_source_public_id) resume(form);
  });
})(window, document);
