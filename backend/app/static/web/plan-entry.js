/* Income and spending-goal forms share draft leases and original command receipts. */
(function (window, document) {
  "use strict";
  const form = document.querySelector("[data-income-draft-scope], [data-goal-draft-scope]");
  if (!form) return;
  const isGoal = form.hasAttribute("data-goal-draft-scope");
  const family = isGoal ? "goal" : "income";
  const definition = {
    goal: {label: "消费目标", list: "/web/goals", amount: "target_amount_yuan",
      create: ["ledger_id", "home_currency_code", "month", "name", "target_amount_yuan", "category"],
      edit: ["ledger_id", "home_currency_code", "month", "name", "target_amount_yuan", "category",
        "public_id", "expected_row_version", "return_category", "return_month"]},
    income: {label: "收入计划", list: "/web/income-plans", amount: "amount_yuan",
      create: ["ledger_id", "home_currency_code", "intent_month", "label", "source_type", "frequency",
        "income_month", "income_month_year", "income_month_number", "amount_yuan", "pay_day"],
      edit: ["ledger_id", "home_currency_code", "intent_month", "public_id", "expected_row_version",
        "label", "source_type", "frequency", "income_month", "amount_yuan", "pay_day"]},
  }[family];
  const taskLabel = definition.label, listPath = definition.list;
  const selector = suffix => "[data-" + family + "-" + suffix + "]";
  const data = suffix => form.dataset[family + suffix];
  const uuid = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
  const createNames = definition.create, editNames = definition.edit;
  const planId = data("PlanId") || "";
  const names = planId ? editNames : createNames;
  const createStore = window.TicketboxDraftStore.createStore({prefix: "ticketbox:" + family + "-create-draft:v1:",
    fields: [...createNames, "amount_placeholder", "amount_inputmode"], validRef: uuid});
  const editStore = window.TicketboxDraftStore.createStore({prefix: "ticketbox:" + family + "-edit-draft:v1:",
    fields: [...editNames, "amount_placeholder", "amount_inputmode"], validRef: uuid});
  const store = planId ? editStore : createStore;
  const anchor = "#" + family + (planId ? "-edit-" : "-create-");
  const reviewName = planId ? "review_latest" : "review_new";
  const canWrite = data("CanWrite") !== "false";
  const archived = data("Archived") === "true";
  const editsAllowed = canWrite && !archived;
  const scope = JSON.parse(data("DraftScope"));
  const status = form.querySelector(selector("draft-status"));
  const submit = form.querySelector('[type="submit"]:not([name="review_new"]):not([name="review_latest"])');
  if (!submit) return;
  const nativeLabel = submit.textContent;
  const nativeRef = form.elements.namedItem("idempotency_key").value;
  const amount = form.elements.namedItem(definition.amount);
  const shelf = document.querySelector(selector("draft-shelf"));
  const review = form.querySelector(selector("review"));
  const discard = form.querySelector(selector("discard"));
  let ref = nativeRef, phase = "editing", held = false, retained = false, busy = false, accepted = false;
  let release = null, onlineOnly = false, blocked = false;
  let leaseVersion = 0;

  function field(name) { return form.elements.namedItem(name); }
  function belongsToForm(record) { return !planId || record.values.public_id === planId; }
  function freshHref() {
    const next = new URL(planId ? form.action : listPath, window.location.href);
    next.searchParams.set("ledger_id", scope.ledgerId);
    next.searchParams.set("new_" + family, "1");
    if (isGoal) {
      for (const name of ["month", "return_category", "return_month"]) {
        if (field(name)?.value) next.searchParams.set(name, field(name).value);
      }
    } else if (planId) next.searchParams.set("intent_month", data("ReviewMonth"));
    if (!planId) next.hash = isGoal ? "new-goal" : "add-income";
    return next.href;
  }
  function recordHref(record) {
    const saved = record.values;
    const next = new URL(listPath + (saved.public_id ? "/" + encodeURIComponent(saved.public_id) + "/edit" : ""), window.location.href);
    next.searchParams.set("ledger_id", scope.ledgerId);
    for (const name of isGoal ? ["month", "return_category", "return_month"] : ["intent_month"]) {
      if (saved[name]) next.searchParams.set(name, saved[name]);
    }
    next.hash = family + (saved.public_id ? "-edit-" : "-create-") + record.clientRef;
    return next.href;
  }
  function values() {
    return {...Object.fromEntries(names.map(name => [name, field(name)?.value || ""])),
      amount_placeholder: amount.placeholder, amount_inputmode: amount.inputMode};
  }
  function notice(message) { status.hidden = false; status.textContent = message; }
  function fieldsEditable() {
    return editsAllowed && !blocked && phase === "editing" && (held || onlineOnly);
  }
  function commandAllowed() { return canWrite && (!archived || phase !== "editing"); }
  function actionUnavailable() { return blocked || busy || accepted || (!held && !onlineOnly); }
  function controls() {
    const editing = fieldsEditable();
    names.forEach(name => {
      const input = field(name);
      if (!input) return;
      if (input.tagName === "SELECT") input.disabled = !editing;
      else input.readOnly = !editing;
    });
    submit.hidden = archived && phase === "editing";
    submit.disabled = !commandAllowed() || actionUnavailable();
    submit.textContent = phase === "editing" ? nativeLabel : "核实原" + taskLabel;
    review.hidden = !editsAllowed || blocked || phase === "editing";
    review.disabled = busy || accepted;
    discard.hidden = blocked || !retained;
    discard.disabled = busy || accepted || !held;
    form.querySelector(selector("review-note")).hidden = review.hidden;
    form.dataset[family + "DraftPhase"] = phase;
  }
  function stop(message) { blocked = true; controls(); notice(message); }
  function restore(record) {
    if (!store.matches(record.scope, scope, false) || !belongsToForm(record)) {
      stop("这份原稿属于另一项任务，请从保留的" + taskLabel + "打开原任务。"); return false;
    }
    const saved = record.values;
    names.forEach(name => {
      let input = field(name);
      if (!input) {
        input = document.createElement("input");
        input.type = "hidden"; input.name = name; form.append(input);
      }
      if (input.tagName === "SELECT" && ![...input.options].some(option => option.value === saved[name])) {
        input.add(new Option(saved[name], saved[name]));
      }
      input.value = saved[name];
    });
    if (!isGoal && saved.income_month && field("income_month").type === "hidden") {
      const label = document.createElement("label");
      label.className = "product-field"; label.textContent = "原预计月份";
      field("income_month").type = "text";
      label.append(field("income_month"));
      form.querySelector("fieldset").prepend(label);
    }
    amount.placeholder = saved.amount_placeholder;
    amount.inputMode = saved.amount_inputmode;
    form.querySelector(selector("amount-label")).textContent =
      (isGoal ? "目标金额（" : "预计金额（") + (saved.home_currency_code || "币种待确认") + "）";
    const intent = form.querySelector(selector("intent"));
    if (intent) intent.textContent = isGoal ?
      "本次目标属于 " + saved.month + "，失败重试保留原月份和金额。" :
      "本次每月计划从 " + (saved.intent_month || "待确认月份") + " 生效。失败重试保留原月份和金额。";
    phase = record.phase; pointTo();
    if (!store.matches(record.scope, scope)) {
      stop("这是原浏览器身份的" + taskLabel + "，输入仍保留；不会转移到当前身份提交。"); return false;
    }
    field("draft_scope").value = JSON.stringify(record.scope);
    return true;
  }
  function pointTo() { window.history.replaceState(null, "", anchor + ref); }
  function renderShelf() {
    const creates = createStore.list(scope), edits = editStore.list(scope);
    const records = (planId ? edits : creates).filter(belongsToForm);
    const list = shelf.querySelector(selector("draft-list"));
    list.replaceChildren();
    [...creates, ...edits].forEach(record => {
      const item = document.createElement("li"), link = document.createElement("a");
      link.href = recordHref(record);
      link.textContent = (record.values.public_id ? "修改 · " : "新建 · ") + (record.values[isGoal ? "name" : "label"] || "未命名" + taskLabel) + " · " +
        (!store.matches(record.scope, scope) ? "原浏览器身份，待核对" : record.phase === "editing" ? "未提交" : "结果待核对");
      item.append(link); list.append(item);
    });
    shelf.hidden = creates.length + edits.length === 0;
    return records;
  }
  function persist(nextPhase) {
    const original = store.read(ref);
    if (retained && !original) throw Error("original_removed");
    if (values().ledger_id !== scope.ledgerId || !store.matches(JSON.parse(field("draft_scope").value), scope)) {
      throw Error("draft_binding_changed");
    }
    const record = store.save(scope, ref, nextPhase, values());
    retained = true; phase = nextPhase; pointTo(); renderShelf();
    return record;
  }
  function capture() {
    if (!editsAllowed || !held || busy || accepted || blocked || phase !== "editing") return;
    try { persist("editing"); controls(); notice("输入已保留在此浏览器，尚未提交。"); }
    catch (_) { notice("最新输入未能保留，请暂勿关闭此页；恢复浏览器存储后可继续提交。"); }
  }
  async function send() {
    const sentLease = leaseVersion;
    const record = persist("submitted");
    controls();
    const body = new window.FormData();
    names.forEach(name => body.set(name, record.values[name]));
    body.set("csrf_token", field("csrf_token").value);
    body.set("draft_scope", JSON.stringify(record.scope));
    body.set("idempotency_key", ref);
    const response = await window.fetch(form.action, {method: "POST", body, credentials: "same-origin",
      headers: {Accept: "application/json"}});
    const result = await response.json();
    if (!held || sentLease !== leaseVersion) throw Error("draft_lease_changed");
    if (!response.ok) {
      phase = "blocked";
      store.save(scope, ref, phase, record.values);
      notice((result.message || "暂未确认提交结果。") + " 原稿仍保留，可沿原提交核实；需要修改时先核对已有计划。");
      return;
    }
    const next = receiptDestination(result, record);
    accepted = true;
    if (!store.acknowledge(result.ack)) throw Error("original_not_acknowledged");
    notice(taskLabel + "已保存，正在返回…");
    window.location.assign(next.href);
  }
  function receiptDestination(result, record) {
    if (!result.receipt?.public_id || (planId && result.receipt.public_id !== planId) ||
        result.ack?.clientRef !== ref || !store.matches(result.ack.scope, scope)) {
      throw Error("unconfirmed_receipt");
    }
    const next = new URL(result.next, window.location.href);
    const categoryReturn = isGoal && planId && record.values.return_category && next.pathname === "/web/categories";
    if (next.origin !== window.location.origin || (next.pathname !== listPath && !categoryReturn) ||
        next.searchParams.get("ledger_id") !== scope.ledgerId) throw Error("invalid_receipt_destination");
    return next;
  }
  form.addEventListener("input", capture);
  form.addEventListener("change", capture);
  discard.addEventListener("click", () => {
    if (!held || busy || accepted || blocked) return;
    const message = phase === "editing" ? "放弃此浏览器保留的未提交输入？" :
      "请先核对已有" + taskLabel + "。此操作只移除本地原稿，不会撤销已发出的请求或已保存的计划。确认放弃原稿？";
    if (!window.confirm(message)) return;
    try {
      const record = store.read(ref);
      if (!record || !store.discardLocal({scope, clientRef: ref, values: record.values, decision: "discard-local"})) {
        throw Error("original_changed");
      }
      accepted = true; controls();
      window.location.assign(freshHref());
    } catch (_) { notice("原稿未能移除，请保留页面并检查浏览器存储。"); }
  });
  form.addEventListener("submit", async event => {
    if (onlineOnly) return;
    // The existing explicit review prepares a fresh form without submitting a plan.
    if (event.submitter?.name === reviewName && editsAllowed && held && !busy && !blocked) {
      names.forEach(name => { if (field(name)?.tagName === "SELECT") field(name).disabled = false; });
      return;
    }
    event.preventDefault();
    if (!commandAllowed() || !held || busy || accepted || blocked) return;
    busy = true; controls(); notice("正在提交原" + taskLabel + "…");
    try { await send(); }
    catch (_) { notice(accepted ? taskLabel + "已保存，本地原稿暂未收起；请核对列表。" :
      "暂未收到保存回执。原稿仍保留，恢复连接后可核实原" + taskLabel + "。"); }
    finally { busy = false; controls(); renderShelf(); }
  });
  function allowOnline() {
    if (window.location.hash.startsWith(anchor) || retained) {
      stop("浏览器暂时无法安全恢复这份原稿。请恢复存储能力后继续，原稿不会被覆盖。");
      return;
    }
    onlineOnly = true; controls();
    notice("此浏览器无法持久保留输入，仍可在本页在线提交；关闭或刷新前请先保存。");
  }
  function activationNotice(record) {
    if (!canWrite) { notice(record ? "当前角色为只读，原稿仍保留；恢复编辑权限后可继续。" : "当前角色为只读，可核对已保存的计划。"); return; }
    if (archived && phase === "editing") { notice(record ? "计划已归档，原输入仍保留；请先恢复计划再核对修改。" : "计划已归档，请先恢复计划再修改。"); return; }
    notice(record ? phase === "editing" ? "已恢复原" + taskLabel + "，保留原币种、月份和目标版本。" :
      "原提交结果尚未确认。核实会沿用原内容和编号。" : "输入会保留在此浏览器，尚未提交。");
  }
  function activate() {
    const currentLease = ++leaseVersion;
    blocked = false; controls();
    if (!window.navigator.locks) { allowOnline(); return; }
    try {
      const records = renderShelf();
      const wanted = window.location.hash.startsWith(anchor) ? window.location.hash.slice(anchor.length) : "";
      const explicitNew = new URL(window.location.href).searchParams.get("new_" + family) === "1";
      const nativeResult = data("NativeResult");
      const preferred = records.find(record => record.phase !== "editing") || records[0];
      ref = nativeResult ? nativeRef : wanted || (!explicitNew && preferred ? preferred.clientRef : nativeRef);
      if (!uuid.test(ref)) { stop("原稿编号无法核对，请从保留的" + taskLabel + "重新打开。"); return; }
      window.navigator.locks.request(store.key(ref), {ifAvailable: true}, async lock => {
        if (currentLease !== leaseVersion) return;
        if (!lock) { stop("这份原稿正在另一标签页使用。关闭那一页后，重新打开即可继续。"); return; }
        const record = store.read(ref);
        if (!record && (retained || (wanted && !nativeResult))) { stop("原稿已收起，请先核对" + taskLabel + "列表。"); return; }
        retained = !!record;
        held = true;
        field("idempotency_key").value = ref;
        if (record) {
          if (!restore(record)) return;
        } else if (nativeResult === "blocked") {
          phase = "blocked";
        }
        if (!store.matches(JSON.parse(field("draft_scope").value), scope)) {
          stop("身份或账本已切换，原输入仍保留；请恢复原身份后继续。"); return;
        }
        if (!record && nativeResult) persist(phase);
        controls();
        activationNotice(record);
        return new Promise(resolve => { release = resolve; });
      }).catch(() => { if (!held) allowOnline(); else stop("原稿暂时无法恢复，请保留此页并检查浏览器存储。"); });
    } catch (_) { allowOnline(); }
  }
  window.addEventListener("pagehide", () => { leaseVersion += 1; held = false; if (release) release(); release = null; });
  window.addEventListener("pageshow", event => { if (event.persisted && !accepted) activate(); });
  window.addEventListener("hashchange", () => {
    if (window.location.hash.startsWith(anchor)) window.location.reload();
  });
  activate();
})(window, document);
