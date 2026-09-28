/* Income-create consumer of the shared bound draft store and original command receipt. */
(function (window, document) {
  "use strict";
  const form = document.querySelector("[data-income-draft-scope]");
  if (!form) return;
  const uuid = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
  const names = ["ledger_id", "home_currency_code", "intent_month", "label", "source_type", "frequency",
    "income_month", "income_month_year", "income_month_number", "amount_yuan", "pay_day"];
  const store = window.TicketboxDraftStore.createStore({prefix: "ticketbox:income-create-draft:v1:",
    fields: [...names, "amount_placeholder", "amount_inputmode"], validRef: uuid});
  const scope = JSON.parse(form.dataset.incomeDraftScope);
  const status = form.querySelector("[data-income-draft-status]");
  const submit = form.querySelector('[type="submit"]:not([name="review_new"])');
  if (!submit) return;
  const nativeLabel = submit.textContent;
  const nativeRef = form.elements.namedItem("idempotency_key").value;
  const amount = form.elements.namedItem("amount_yuan");
  const shelf = document.querySelector("[data-income-draft-shelf]");
  const review = form.querySelector("[data-income-review]");
  const discard = form.querySelector("[data-income-discard]");
  let ref = nativeRef, phase = "editing", held = false, retained = false, busy = false, accepted = false;
  let release = null, onlineOnly = false, blocked = false;
  let leaseVersion = 0;

  function field(name) { return form.elements.namedItem(name); }
  function values() {
    return {...Object.fromEntries(names.map(name => [name, field(name)?.value || ""])),
      amount_placeholder: amount.placeholder, amount_inputmode: amount.inputMode};
  }
  function notice(message) { status.hidden = false; status.textContent = message; }
  function controls() {
    const editing = !blocked && phase === "editing" && (held || onlineOnly);
    names.forEach(name => {
      const input = field(name);
      if (!input) return;
      if (input.tagName === "SELECT") input.disabled = !editing;
      else input.readOnly = !editing;
    });
    submit.disabled = blocked || busy || accepted || (!held && !onlineOnly);
    submit.textContent = phase === "editing" ? nativeLabel : "核实原收入计划";
    review.hidden = blocked || phase === "editing";
    review.disabled = busy || accepted;
    discard.hidden = blocked || !retained;
    discard.disabled = busy || accepted || !held;
    form.querySelector("[data-income-review-note]").hidden = review.hidden;
    form.dataset.incomeDraftPhase = phase;
  }
  function stop(message) { blocked = true; controls(); notice(message); }
  function restore(record) {
    if (!store.matches(record.scope, scope, false)) {
      stop("这份原稿属于其他账本或账户，请回到原账本继续。"); return false;
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
    if (saved.income_month && field("income_month").type === "hidden") {
      const label = document.createElement("label");
      label.className = "product-field"; label.textContent = "原预计月份";
      field("income_month").type = "text";
      label.append(field("income_month"));
      form.querySelector("fieldset").prepend(label);
    }
    amount.placeholder = saved.amount_placeholder;
    amount.inputMode = saved.amount_inputmode;
    form.querySelector('label[for="income-create-amount"]').textContent =
      "预计金额（" + (saved.home_currency_code || "币种待确认") + "）";
    form.querySelector("[data-income-intent]").textContent =
      "本次每月计划从 " + (saved.intent_month || "待确认月份") + " 生效。失败重试保留原月份和金额。";
    phase = record.phase; pointTo();
    if (!store.matches(record.scope, scope)) {
      stop("这是原浏览器身份的收入计划，输入仍保留；不会转移到当前身份提交。"); return false;
    }
    field("draft_scope").value = JSON.stringify(record.scope);
    return true;
  }
  function pointTo() { window.history.replaceState(null, "", "#income-create-" + ref); }
  function renderShelf() {
    const records = store.list(scope), list = shelf.querySelector("[data-income-draft-list]");
    list.replaceChildren();
    records.forEach(record => {
      const item = document.createElement("li"), link = document.createElement("a");
      link.href = "/web/income-plans?ledger_id=" + encodeURIComponent(scope.ledgerId) + "#income-create-" + record.clientRef;
      link.textContent = (record.values.label || "未命名收入计划") + " · " +
        (!store.matches(record.scope, scope) ? "原浏览器身份，待核对" : record.phase === "editing" ? "未提交" : "结果待核对");
      item.append(link); list.append(item);
    });
    shelf.hidden = records.length === 0;
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
    if (!held || busy || accepted || blocked || phase !== "editing") return;
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
    if (!result.receipt?.public_id || result.ack?.clientRef !== ref || !store.matches(result.ack.scope, scope)) {
      throw Error("unconfirmed_receipt");
    }
    const next = new URL(result.next, window.location.href);
    if (next.origin !== window.location.origin || next.pathname !== "/web/income-plans" ||
        next.searchParams.get("ledger_id") !== scope.ledgerId) throw Error("invalid_receipt_destination");
    accepted = true;
    if (!store.acknowledge(result.ack)) throw Error("original_not_acknowledged");
    notice("收入计划已保存，正在返回列表…");
    window.location.assign(next.href);
  }
  form.addEventListener("input", capture);
  form.addEventListener("change", capture);
  discard.addEventListener("click", () => {
    if (!held || busy || accepted || blocked) return;
    const message = phase === "editing" ? "放弃此浏览器保留的未提交输入？" :
      "请先核对已有收入计划。此操作只移除本地原稿，不会撤销已发出的请求或已保存的计划。确认放弃原稿？";
    if (!window.confirm(message)) return;
    try {
      const record = store.read(ref);
      if (!record || !store.discardLocal({scope, clientRef: ref, values: record.values, decision: "discard-local"})) {
        throw Error("original_changed");
      }
      accepted = true; controls();
      window.location.assign("/web/income-plans?ledger_id=" + encodeURIComponent(scope.ledgerId) + "&new_income=1#add-income");
    } catch (_) { notice("原稿未能移除，请保留页面并检查浏览器存储。"); }
  });
  form.addEventListener("submit", async event => {
    if (onlineOnly) return;
    // The existing explicit review prepares a fresh form without submitting a plan.
    if (event.submitter?.name === "review_new" && held && !busy && !blocked) {
      names.forEach(name => { if (field(name)?.tagName === "SELECT") field(name).disabled = false; });
      return;
    }
    event.preventDefault();
    if (!held || busy || accepted || blocked) return;
    busy = true; controls(); notice("正在提交原收入计划…");
    try { await send(); }
    catch (_) { notice(accepted ? "收入计划已保存，本地原稿暂未收起；请核对列表。" :
      "暂未收到保存回执。原稿仍保留，恢复连接后可核实原收入计划。"); }
    finally { busy = false; controls(); renderShelf(); }
  });
  function allowOnline() {
    if (window.location.hash.startsWith("#income-create-") || retained) {
      stop("浏览器暂时无法安全恢复这份原稿。请恢复存储能力后继续，原稿不会被覆盖。");
      return;
    }
    onlineOnly = true; controls();
    notice("此浏览器无法持久保留输入，仍可在本页在线提交；关闭或刷新前请先保存。");
  }
  function activate() {
    const currentLease = ++leaseVersion;
    blocked = false; controls();
    if (!window.navigator.locks) { allowOnline(); return; }
    try {
      const records = renderShelf();
      const wanted = /^#income-create-(.+)$/.exec(window.location.hash);
      const explicitNew = new URL(window.location.href).searchParams.get("new_income") === "1";
      const nativeResult = form.dataset.incomeNativeResult;
      const preferred = records.find(record => record.phase !== "editing") || records[0];
      ref = nativeResult ? nativeRef : wanted ? wanted[1] : !explicitNew && preferred ? preferred.clientRef : nativeRef;
      if (!uuid.test(ref)) { stop("原稿编号无法核对，请从保留的收入计划重新打开。"); return; }
      window.navigator.locks.request(store.key(ref), {ifAvailable: true}, async lock => {
        if (currentLease !== leaseVersion) return;
        if (!lock) { stop("这份原稿正在另一标签页使用。关闭那一页后，重新打开即可继续。"); return; }
        const record = store.read(ref);
        if (!record && (retained || (wanted && !nativeResult))) { stop("原稿已收起，请先核对收入计划列表。"); return; }
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
        notice(record ? phase === "editing" ? "已恢复原收入计划，保留原币种和生效月份。" :
          "原提交结果尚未确认。核实会沿用原内容和编号。" : "输入会保留在此浏览器，尚未提交。");
        return new Promise(resolve => { release = resolve; });
      }).catch(() => { if (!held) allowOnline(); else stop("原稿暂时无法恢复，请保留此页并检查浏览器存储。"); });
    } catch (_) { allowOnline(); }
  }
  window.addEventListener("pagehide", () => { leaseVersion += 1; held = false; if (release) release(); release = null; });
  window.addEventListener("pageshow", event => { if (event.persisted && !accepted) activate(); });
  window.addEventListener("hashchange", () => {
    if (window.location.hash.startsWith("#income-create-")) window.location.reload();
  });
  activate();
})(window, document);
